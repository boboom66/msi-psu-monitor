# PACKAGE INSTRUCTIONS — msi_psu_monitor/

Stdlib-only package (`os/glob/struct/select/time/argparse/json/sys/csv/fcntl/signal/
math/logging/http.server/dataclasses/pathlib/datetime`). Never add third-party
runtime imports.

## Module map

| Module | Role |
|--------|------|
| `protocol.py` | HID framing, register map, variant dispatch, init-handshake retry, `MSIPSU.get_sensors()`, per-register fallback (`read_register_sensors`), MFR_MODEL (`read_model`), IOUT_12+4 (`read_pin_currents`), fan/Zero Fan/buzzer/multirail/OCP-threshold writes, VIN, alert/black-box/OCP reads, `HIDDevice` + `flock` |
| `monitor.py` | CLI: argument validation, three sensor formatters + three `--ocp`/`--pins` formatters, exit codes, fan/Zero Fan/buzzer/multirail/OCP-threshold writes, `--dump-thresholds`/`--ocp-set`/`--load-thresholds`, `--export`, `--show-log`, `--show-alert-log`, `--ocp`, `--pins`, `--dump-config`, device selection, `open_psu()` |
| `state.py` | `MonitorState` (avg + energy integral), `state.json` atomic persistence, `daily-*.log` history, `alerts-*.log` audit trail, `latest.json` live cache, `--from`/`--columns`/`build_export` |
| `daemon.py` | Resident sample loop: 1 s alerts, 30 s atomic prometheus incl. the OCP block (`msi_psu_ocp_*` on TS / `msi_psu_multirail_ocp` on MEG P; variant-gated, refreshed every write because C1h is a 5 s rolling average), the same file rewritten with `msi_psu_up 0` + reason on a failed read, 1 s `latest.json`, alert-log append, 60 s history, rescan after 5 failures |
| `dashboard.py` | Loopback-only `http.server` reading the history/`latest.json` files; non-loopback Host → 421, CSP/Permissions-Policy on every response; charts are hand-drawn `<canvas>` JS |
| `termdash.py` | ANSI terminal dashboard for `--dashboard-text`: width-based bars + threshold colours, no browser and no third-party packages |
| `menu.py` | Grouped numbered menu for `--menu`: arrow-key interactive selection on a tty (stdlib `termios`/`select`, no third-party code), numbered line prompt otherwise; pages long output and restores the terminal on exit |
| `alerts.py` | `AlertEngine` (edge-triggered + consecutive debounce), severities, per-pin OCP/imbalance mirror, local threshold evaluation (power/temperature/rails/connector) |
| `config.py` | INI config, precedence CLI > file > `DEFAULTS`; `[alerts]` local limits via `threshold_limits()` |
| `demo.py` | `MSI_PSU_DEMO=1` synthetic PSU; the only synthetic source in the package |

## Protocol (normative: docs/protocol.md)

- HID framing: 64-byte reports (`CMD_BUFFER_SIZE`), 250ms timeout
  (`CMD_TIMEOUT_MS`), 2-byte echo header stripped, NAK (`0xFE`) → `None`. On top of that,
  `0xC0` and `0xC1` are **overloaded addresses** (see Invariants) — the model gate, not the
  payload length, decides which command you are talking to.
- Registers: `0x10-0x13` ident (`0x11` MFR_MODEL is 12 ASCII bytes and is authoritative over the 11-byte handshake), `0x20` VIN (non-TS MSI-compatible extra), `0x22-0x42` sensors, `0x2C` IOUT_12+4 (24 bytes, 12 pins, 5 s averages), `0x41` fan setting,
  `0x42` fan duty, `0x43` Zero Fan enable (write-only), `0xC2` buzzer switch,
  `0xC0` multirail **or** 12V-2x6 OCP config (TS only),
  `0xC1` OCP state (InfoID 0) / alert log (InfoID 1-10), `0xD0/0xD1` control,
  `0xE0` bulk read, `0xE1` alert status, `0xF1` save settings.
- LINEAR11 call pattern (keep exactly):
  `lin11_to_int(struct.unpack('<H', data[o:o+2])[0], scale, signed) / scale`,
  rounded at the call site: V/A 3dp, W 1dp, % 2dp, RPM int.
  `signed=False` — always: REV6 and MSI's `ValueCalc` both leave the
  mantissa unsigned (`((High & 7) << 8) + Low`), so the default must not be
  flipped back to `True`. Scales: V/A ×1000, W ×1e6, EFF ×100, TEMP ×1000.
- Variant dispatch is by **product-string substring** (`Ai1600TS`→mpg before the
  `Ai1600`→meg wildcard, then `Ai1300`/`Ai1000`), never by USB PID.
- `BULK_*` offsets describe the MPG TS layout only (44B of data in a 62B frame).
  Each `VARIANTS` entry carries `bulk_size` (frame the device returns) and
  `payload_size` (shortest decodable frame); `get_sensors()` gates on the latter, so
  the Ai1600T's 20-byte payload is decoded rather than dropped.
- Sensors dict: ident keys are plain strings; readings are `(value, unit)` tuples;
  formatters branch on `isinstance(v, tuple)`.

## Invariants added with the daemon/state work

- **Exit codes**: `EXIT_OK=0`, `EXIT_ERROR=1`, `EXIT_ALERT=2`. Alerts print
  `ALERT [severity] name: description` on **stderr**; stdout stays machine-parseable.
- **Init handshake retries 3x**: `MSIPSU._handshake()` tries FA51 up to 3 times
  (`HANDSHAKE_RETRY_DELAYS = (0.5, 1.0)`, REQ-18) before declaring the device
  unresponsive. Only the handshake retries; sampling failures stay on the daemon's
  5-failure rescan path, and tests monkeypatch `protocol.time.sleep`.
- **A device error is a failure, never an exception**: every ``os.read``/``os.write``/
  ``select`` in ``HIDDevice.send_command`` maps ``OSError`` (ENODEV on unplug, EBADF on a
  closed fd) to ``None``, exactly like a NAK. The daemon rescan counts those; a traceback
  would kill the loop before it ever reaches five.
- **Ident-only is not a sample**: ``get_sensors()`` returns ident+uptime when the 0xE0
  payload never arrived, which is a failed read (``monitor.has_readings()``). One-shot
  exits 1, the daemon counts a failure — but an active E1h alert still exits 2, because
  alerting outranks the payload read.
- **A history file is identified by its header, not its existence**: ``append_history()``
  writes the header whenever the file is missing *or empty*, so a crash between open and
  the header cannot leave a day file whose first data row DictReader reads as columns.
- **Atomic writes apply to data files, not to output targets**: `state.json` and the
  prometheus textfile use scratch+fsync+`os.replace`; `-O`/`--export -O` on a
  symlink/FIFO/device is written through instead (renaming the name would replace the link
  itself, and `/dev/stdout` is a link).
- **Every data write is atomic and fsynced**: `path.with_name(name + '.tmp')` +
  `flush` + `os.fsync` + `os.replace()`, then a best-effort directory fsync, for
  `state.json` and the prometheus textfile. Never write the target in place: a rename
  that outruns the data can leave a complete-looking empty file after a power cut.
- **A failed payload read is not a recovery**: when the 0xE0 frame is missing, E1h-only names
  still update, but mirror-owned names (`ocp_pin*`, `pin_imbalance`) are left out of the
  poll so the engine keeps them latched; `retain()` must keep `pin_imbalance` while the model
  reports `ocp_pin*` bits (DEF-025).
- **Daemon housekeeping is guarded**: the hourly prune is wrapped; an `OSError` from a state
  dir that changed under the daemon must never escape `tick()` (DEF-024).
- **A failed read must not leave a healthy-looking textfile behind**: the daemon
  rewrites it with `msi_psu_up 0` + `msi_psu_error_info{reason}` (once per distinct
  reason, not once per tick), because node_exporter re-exports the last file forever.
- **Energy integral is frozen**: `wh += watts * dt / 3600`, and gaps longer than
  `MAX_SAMPLE_GAP_S` (300 s) advance the clock without integrating.
- **`collect_alerts()` returns `(fired, active_security, have_e1h, threshold_active)`**:
  `have_e1h` says whether the E1h bitmap answered. The pin mirror only sees the OCP pins
  and their imbalance, not `opp`/`otp`/`fan`, so a poll without the bitmap renders as
  `Unknown`, never as `Normal` — and it never clears an alert the engine already fired.
  A poll that answers does the opposite: `retain()` drops the names this device cannot
  report, so a model swap cannot leave a foreign alert latched (a name with no bit never
  gets the `False` that would clear it).
- **Local thresholds ride the same engine, but differently**: `[alerts]` limits are
  evaluated by `alerts.evaluate_threshold_alerts()`; their names are in
  `THRESHOLD_ALERT_NAMES` and deliberately distinct from E1h names. They are returned as
  `threshold_active` (not in the 12V-2x6 status), share debounce/exit-2/alert-log, and a
  missing sensor reading is omitted so `retain()` keeps a latched threshold alert.
  `configured_threshold_names()` supplies the retain() capability (connector limits need
  per-pin sensing). Never fold them into `sensors['alerts']`.
- **The E1h bit order is per model** (`ALERT_INDEXES`, mirroring the three
  `Alert_Index_*` arrays at `CPSU.cs:1046`): byte 0 is 12V OVP on a MEG and 12V OCP on
  a MPG TS, and the Ai1600T sends 13 bytes, not 18. Never index that bitmap with a
  flat table, and never name a bit for an unknown model — return `None` and let the
  status read `Unknown`.
- **The demo must stay opt-in**: `demo.enabled()` reads `MSI_PSU_DEMO`; nothing may
  import synthetic data on the production path. The black box is part of that: REV6 p.13
  defines InfoID 1 as the newest trip, so the demo's slot 1 must stay newest and its
  counters must agree, or an acceptance run trains on an order the real path never
  prints.
- **`--watch` is text-only** and flushes each frame (pipes must see every sample).
- **`[monitor] no_alerts` is honoured by the daemon too**, not only by the CLI: with it
  on, `sample()` sets neither `status` nor `alerts`, so no Status line, no alert metric and
  no `ALERT` line appears, and 0xE1 is not polled at all (the daemon logs one line at
  start-up so "nothing reported" is not mistaken for "all normal").
- **`--ocp` is read-only and model-gated**: `MSIPSU.supports_ocp_config` (TS variants only,
  mirroring `CPSU.cs:843`) guards the read; a MEG model gets the explanation and `EXIT_OK`,
  never an error. The 8-byte threshold write is the separate `--ocp-set` /
  `--load-thresholds` path (`--dump-thresholds` is its read-only dump), also gated on
  `supports_ocp_config`: values are range-validated (never clamped), the amp fields are
  written as `value << 4` + `0xE0`, the three times as whole seconds, then `F1h` saves
  them, and the command verifies by read-back (3 attempts, `EXIT_ERROR` on mismatch).
  Re-applying the current config is a no-op; the write method itself rejects out-of-range
  or unknown-model requests. CI only proves demo/mock behaviour -- bench acceptance is
  required. The separate 1-byte multirail switch is `--set-rail` (MEG P only, write +
  `F1h` + read-back); never merge the two C0 meanings.
- **`--pins` is the read-only 0x2C view**: `MSIPSU.supports_pin_currents` (TS variants
  only) guards `read_pin_currents()`; a MEG model gets the explanation and `EXIT_OK`.
  REV6 defines 24 bytes = 12 LINEAR11 pin currents (12V5 pins 1-6, then 12V3 pins 7-12)
  as **5-second averages**. Do not merge it with `--ocp`: 0x2C is the raw pin view,
  0xC1 is the alert/black-box state. A supported model that NAKs 0x2C is a real read
  failure (`EXIT_ERROR`).
- **0x11 MFR_MODEL is the model source of truth**: `init()` reads the 12-byte block and
  prefers it when it names a model containing `Ai`. The 0xFA51 handshake may be 11 bytes
  and would truncate `MPG Ai1300TS` to `MPG Ai1300T`, which must never be decoded as a
  MEG. If 0x11 also fails, the truncated name stays refused (`variant=None`).
- **A failed 0xE0 read falls back to single registers**: `read_register_sensors()` reads
  `0x24`-`0x2B`, `0x30`, `0x40` individually (plus `0x2C` on TS), merges only the
  registers that answered, and sets `read_mode="registers"`. A short frame keeps
  `payload_error` for diagnosis; the text format then prints a `NOTE` instead of hiding
  the values, and Prometheus exports `msi_psu_register_fallback 1`. An unknown model
  still refuses to parse (the byte order is model-dependent).
- **VIN is an extra, not REV6**: `read_vin()` is tried on the non-TS models only and is
  omitted on NAK; `format_text` calls it `AC Input` and Prometheus exports
  `msi_psu_input_voltage`. Units are volts (`ValueCalc` direct), not millivolts.
- **Alert audit trail**: `state.append_alert_log()` writes `alerts-YYYYMMDD.log`
  (5 MiB rotation to `.1`, fsync per line, 30-day prune); the daemon records fired and
  recovered edges from `AlertEngine.take_cleared()`; `--show-alert-log` reads local files
  only. A write failure is warned and never breaks sampling.
- **Live dashboard**: the daemon writes `latest.json` without fsync every sample; the page
  polls `/api/live` once a second. The endpoint adds the history column aliases
  (`dashboard._live_view`) because the page reuses its history rows array; without them only
  `temp` matches the daemon snapshot keys and every other chart stands still. A
  stale/missing file must be 503, never a frozen chart.
- **Dashboard Host/CSP**: a non-loopback `Host` is 421 (DNS-rebinding defence), and every
  response carries a self-contained CSP plus Permissions-Policy. GET and HEAD share
  `_route()`; do not add a second response path.
- `HISTORY_COLUMNS` is append-only: `cpu_w`/`gpu_w` were added for the multi-rail
  models, and older 9-column files must keep loading (absent columns export as `N/A`).
- `state.rail_watts()` is the single definition of the CPU/GPU split (CPU = 12V2,
  GPU = 12V3+12V4+12V5, `UC_Dashboard_Page.xaml.cs:203`); do not re-derive it in the
  formatters.

## Audit invariants (2026-10-22)

- **`--once` is a mode, not a harmless extra**: it is rejected with
  `--export/--show-log/--show-alert-log/--ocp/--pins/--dump-thresholds` (exit 2), because those
  modes would ignore it. Control/threshold writes may still carry `--once`.
- **Config-derived defaults warn when a mode ignores them**: `[monitor] output/serial`
  on `--dashboard`, and `serial` on `--export`/`--show-alert-log`, log a warning; explicit
  CLI equivalents remain usage errors.
- **0xC0 `enabled` accepts only 0/1**: any other byte makes the whole C0h read unusable
  (`None`), never "disabled". CLI exits 1; daemon clears the OCP block.
- **State/live reads reject special files**: FIFO/device `latest.json`, history and alert
  logs must not block a daemon/dashboard thread. Non-finite readings are omitted, not
  written as NaN; deeply nested JSON is damaged state, not a crash.
- **Atomic writes preserve the existing mode**; export also fsyncs the directory.
- **Logging is configured on the `msi_psu` package logger**, so `--quiet` suppresses
  config/state/daemon warnings too.

## Anti-patterns

- Do NOT add pip runtime dependencies, and never make the official download depend on
  Python: the release tarball/.deb are frozen with PyInstaller (`build` group) and
  `scripts/install_binary.sh` must not call `python3`/`pip`. `tests/test_packaging.py`
  enforces both.
- Do NOT touch `BULK_*` for non-TS variants.
- `protocol.py` (and the other three legacy files) are listed in
  `[tool.ruff.format] exclude` with `force-exclude = true`, so the formatter cannot
  churn their quote style even when they are named explicitly. Re-apply semantic
  edits on top of `git checkout` if a formatter run ever slips through.
- Do NOT gate `0xC0` on payload length: `supports_ocp_config` (8 bytes, MPG TS) and
  `supports_multirail_ocp` (1 byte, MEG P) are complementary variant checks.
- Fan writes go through `monitor.apply_fan_setting(psu, mode, duty)` — one place for the
  41h write + F1h save + read-back verify, shared by `--fan-mode` and the daemon's
  `[fan]` restore. Zero Fan uses the matching `apply_zero_fan_setting(psu, enabled)`
  (43h + F1h + 42h byte-4 read-back); the daemon restores `[fan] zero_fan` with the
  same helper. Never add a second write path. `silence_buzzer()` is the one-shot C2h
  switch with no read-back, gated to the TS models like `CPSU.cs:1148-1159`; it
  toggles, so never report it as "silenced" -- only as acknowledged.
- `dashboard.py` resolves a request once in `_route()` and both `do_GET`/`do_HEAD`
  consume that tuple: never write a second response path, or HEAD starts lying about
  404s and Content-Length.
- Dashboard transport errors go through `DashboardServer.handle_error`: a client that
  hangs up is debug-level, anything else keeps its traceback via `logger.exception`.
  Never let `socketserver` print a raw traceback into the journal.
- Text IO is explicit UTF-8 everywhere: read `utf-8-sig` (a BOM is an encoding detail),
  write `utf-8`. A unit inheriting `LC_ALL=C` must still read a config with non-ASCII
  comments and a hand-edited state.json.
- USB IDs live in five places that `tests/test_pid_consistency.py` cross-checks:
  `PSU_PRODUCT_IDS`, `MSIPSU.VARIANTS[*]["pid"]`, `systemd/99-msi-psu.rules`,
  `scripts/install.sh` and the README table. Adding a model means touching all five.
- `tests/test_stdlib_only.py` imports every shipped module in a `python -I`
  subprocess: the stdlib-only promise is enforced, not just declared.
- The demo's model table lives in `demo.MODEL_WATTS`; a new variant must be added
  there too, or `MSI_PSU_DEMO_MODEL` cannot reach it.
- Do NOT harden `systemd/*.service` with `PrivateDevices` (needs `/dev/hidraw*`).
- Do NOT let the dashboard touch hidraw — it is read-only over `daily-*.log` and `latest.json`.
- `--once or not watch` means the default run is one-shot; keep it.

## Verification (no hardware required)

```bash
uv run --group dev pytest -q              # full suite: lin11 vectors, formatters, ocp, state, daemon, dashboard, demo
uv run --group dev ruff check .           # must be clean
uv run --group dev mypy msi_psu_monitor/  # must be clean
uv run --group dev coverage run --branch -m pytest -q
uv run --group dev coverage report --fail-under=90
```

`ruff format --check .` is safe repo-wide and is a CI gate: the four legacy files
that mix quote styles are excluded by `[tool.ruff.format] exclude` with
`[tool.ruff] force-exclude = true`, which also blocks them when named explicitly.
Format the files you touch (`ruff format <path>`); the exclusion list is the fix, so
do not re-add a repo-wide warning.

`tests/test_prometheus_exposition.py` is the stdlib promtool stand-in: it parses our
exposition output strictly (HELP/TYPE, labels/escapes, finite values, duplicate
series, canonical `metric{} value`).

Full no-hardware walkthrough (demo mode, daemon + dashboard chain, `.deb`):
`docs/verify.md`.
