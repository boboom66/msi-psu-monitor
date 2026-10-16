# PACKAGE INSTRUCTIONS — msi_psu_monitor/

Stdlib-only package (`os/glob/struct/select/time/argparse/json/sys/csv/fcntl/signal/
math/logging/http.server/dataclasses/pathlib/datetime`). Never add third-party
runtime imports.

## Module map

| Module | Role |
|--------|------|
| `protocol.py` | HID framing, register map, variant dispatch, `MSIPSU.get_sensors()`, fan/alert/black-box/OCP reads, `HIDDevice` + `flock` |
| `monitor.py` | CLI: argument validation, three sensor formatters + three `--ocp` formatters, exit codes, fan write, `--export`, `--show-log`, `--ocp`, device selection, `open_psu()` |
| `state.py` | `MonitorState` (avg + energy integral), `state.json` atomic persistence, `daily-*.log` history, `--from`/`--columns`/`build_export` |
| `daemon.py` | Resident sample loop: 1 s alerts, 30 s atomic prometheus, 60 s history, rescan after 5 failures |
| `dashboard.py` | Loopback-only `http.server` reading the history files; charts are hand-drawn `<canvas>` JS |
| `alerts.py` | `AlertEngine` (edge-triggered + consecutive debounce), severities, per-pin OCP/imbalance mirror |
| `config.py` | INI config, precedence CLI > file > `DEFAULTS` |
| `demo.py` | `MSI_PSU_DEMO=1` synthetic PSU; the only synthetic source in the package |

## Protocol (normative: docs/protocol.md)

- HID framing: 64-byte reports (`CMD_BUFFER_SIZE`), 250ms timeout
  (`CMD_TIMEOUT_MS`), 2-byte echo header stripped, NAK (`0xFE`) → `None`. On top of that,
  `0xC0` and `0xC1` are **overloaded addresses** (see Invariants) — the model gate, not the
  payload length, decides which command you are talking to.
- Registers: `0x10-0x13` ident, `0x20-0x42` sensors, `0x41` fan setting,
  `0x42` fan duty, `0xC0` multirail **or** 12V-2x6 OCP config (TS only),
  `0xC1` OCP state (InfoID 0) / alert log (InfoID 1-10), `0xD0/0xD1` control,
  `0xE0` bulk read, `0xE1` alert status, `0xF1` save settings.
- LINEAR11 call pattern (keep exactly):
  `lin11_to_int(struct.unpack('<H', data[o:o+2])[0], scale, signed) / scale`,
  rounded at the call site: V/A 3dp, W 1dp, % 2dp, RPM int.
  `signed=False` only for fan RPM. Scales: V/A ×1000, W ×1e6, EFF ×100, TEMP ×1000.
- Variant dispatch is by **product-string substring** (`Ai1600TS`→mpg before the
  `Ai1600`→meg wildcard, then `Ai1300`/`Ai1000`), never by USB PID.
- `BULK_*` offsets describe the Ai1600TS 62-byte layout only (44B data + 18B zero
  pad; bail if bulk `<44B`). Other variants use inline slices in `get_sensors()`.
- Sensors dict: ident keys are plain strings; readings are `(value, unit)` tuples;
  formatters branch on `isinstance(v, tuple)`.

## Invariants added with the daemon/state work

- **Exit codes**: `EXIT_OK=0`, `EXIT_ERROR=1`, `EXIT_ALERT=2`. Alerts print
  `ALERT [severity] name: description` on **stderr**; stdout stays machine-parseable.
- **Every write is atomic**: `path.with_name(name + '.tmp')` + `os.replace()` for
  `state.json` and the prometheus textfile. Never write the target in place.
- **Energy integral is frozen**: `wh += watts * dt / 3600`, and gaps longer than
  `MAX_SAMPLE_GAP_S` (300 s) advance the clock without integrating.
- **`collect_alerts()` returns `have_data`**; a PSU that answers neither E1h nor the
  pin mirror must render as `Unknown`, never as `Normal`.
- **The demo must stay opt-in**: `demo.enabled()` reads `MSI_PSU_DEMO`; nothing may
  import synthetic data on the production path.
- **`--watch` is text-only** and flushes each frame (pipes must see every sample).
- **`--ocp` is read-only and model-gated**: `MSIPSU.supports_ocp_config` (TS variants only,
  mirroring `CPSU.cs:843`) guards the read; a MEG model gets the explanation and `EXIT_OK`,
  never an error. The C0/C1 write path stays frozen for a later approved batch.
- History CSV columns are frozen (`HISTORY_COLUMNS`); `--export` renames some and
  maps `cpu`/`gpu` to `N/A` because the 7ZPU single-rail layout cannot split them.

## Anti-patterns

- Do NOT add pip runtime dependencies.
- Do NOT touch `BULK_*` for non-TS variants.
- Do NOT harden `systemd/*.service` with `PrivateDevices` (needs `/dev/hidraw*`).
- Do NOT let the dashboard touch hidraw — it is read-only over `daily-*.log`.
- `--once or not watch` means the default run is one-shot; keep it.

## Verification (no hardware required)

```bash
uv run --group dev pytest -q              # 183 tests: lin11 vectors, formatters, ocp, state, daemon, dashboard, demo
uv run --group dev ruff check .           # must be clean
uv run --group dev mypy msi_psu_monitor/  # must be clean
```

`ruff format` must NOT be enforced repo-wide: `protocol.py`, `__init__.py`,
`__main__.py` and `tests/test_monitor.py` mix quote styles and a full format pass
would create a churn diff (formatting `protocol.py` alone rewrites ~200 lines of
unrelated quote styles). Format only the files you touched, and revert format-only
churn in `protocol.py` — it is deliberately left in its original style.

Full no-hardware walkthrough (demo mode, daemon + dashboard chain, `.deb`):
`docs/verify.md`.
