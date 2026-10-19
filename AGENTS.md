# msi-psu-monitor

Userspace Python CLI + daemon (stdlib only) reading MSI PSUs via USB HID hidraw.
Protocol rules live in `msi_psu_monitor/AGENTS.md` (auto-loaded via `opencode.json`);
`docs/protocol.md` is normative for the register map and 0xE0 bulk layouts.

## Commands

```bash
uv sync --group dev                                  # py>=3.10, dev toolchain (pytest/ruff/mypy), zero runtime deps
uv run --group dev pytest -q                         # 630 tests, no hardware needed
uv run --group dev pytest -q tests/test_state.py     # single file
uv run --group dev ruff check .                      # must be clean
uv run --group dev mypy msi_psu_monitor/             # must be clean
uv run --group dev coverage run --branch -m pytest -q
uv run --group dev coverage report --fail-under=90   # source statement floor
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --once      # full pipeline, no PSU attached
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --ocp       # 12V-2x6 OCP thresholds + state (read-only)
MSI_PSU_DEMO_MODEL=ai1300p MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --set-rail multi
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --show-alert-log
sudo msi-psu-monitor --once                          # one-shot; hidraw needs root (or the udev uaccess rule)
sudo msi-psu-monitor --watch 1                       # continuous, 1s poll
sudo msi-psu-monitor -f prometheus -O /var/lib/node_exporter/msi-psu.prom
msi-psu-monitor --dashboard --port 8899              # loopback charts over the daemon history
bash scripts/build_deb.sh                            # dev/CI source .deb into dist/
bash scripts/build_binary.sh                          # self-contained tarball (build group)
bash scripts/build_deb_binary.sh                      # zero-Python .deb from the binaries
bash scripts/build_hardware_kit.sh                    # test-machine kit (binary + source fallback)
sudo ./scripts/install.sh                            # package + systemd daemon unit
```

`docs/verify.md` is the full no-hardware checklist — use it instead of improvising.
CI (`.github/workflows/ci.yml`) runs ruff + mypy + pytest on py3.10/3.12/3.13.

## Gotchas (agent would miss these)

- **Stdlib only**: never add a runtime dependency (`pyproject.toml` has zero
  `dependencies`), including for the dashboard and the demo mode.
- **Variant dispatch is by product-string substring, order matters**: `Ai1600TS` → mpg
  before the `Ai1600` → meg wildcard, then `Ai1300`/`Ai1000` (`protocol.py:MSIPSU.init`).
  Never dispatch by USB PID; `PSU_PRODUCT_IDS` (5 PIDs) and the variant map are
  maintained separately.
- **`BULK_*` offsets are the MPG TS layout only** (44B of data inside a 62B frame).
  `VARIANTS[...]['payload_size']` is the per-variant minimum: 44 for the TS, 40 for
  ai1000p/ai1300p, 20 for meg_ai1600 — a single 44B gate silently drops every
  Ai1600T sensor. The non-TS branches use inline slices in `get_sensors()`; do not
  "unify" them onto `BULK_*`.
- **MSI's `ValueCalc` is `mantissa * 2**exponent`** (`CPSU.cs:1248`), so the unit comes
  from the exponent; the 11-bit mantissa means 3.3 V needs a negative exponent
  (−7 → 3.296 V) and cannot be written as 3300 mV.
- **Sensors dict shape**: ident keys (`vendor/product/fw_revision/serial`) are plain
  strings; readings are `(value, unit)` tuples. Formatters branch on
  `isinstance(v, tuple)` — keep that contract.
- **`fw_revision` is *exactly* two ASCII digits** (`len == 2 and isdigit()`), the device's
  "10" rendered as `1.0` with the dot MSI Center inserts itself. Anything else is passed
  through verbatim — `>= 2` used to truncate `b'1234'` into "1.2", a revision the device
  never sent.
- **LINEAR11 call pattern, keep exactly**:
  `lin11_to_int(struct.unpack('<H', data[o:o+2])[0], scale, signed) / scale`, rounded at
  the call site (V/A 3dp, W 1dp, % 2dp, RPM int). `signed=False` — always: REV6 and MSI's `ValueCalc` both leave the
  mantissa unsigned (`((High & 7) << 8) + Low`), so the default must not be
  flipped back to `True`.
  Scales: V/A ×1000, W ×1e6, EFF ×100, TEMP ×1000.
- **HID framing**: always 64B reports, 250ms timeout, drain-before-write, strip 2-byte
  echo header, NAK (`0xFE`) → `None`. `0xFE` is a *payload* byte, never byte 0: a read
  NAK is `[0x51, 0xFE]`, a refused write is `[0x50, <reg>, 0xFE]`, and a data reply whose
  first payload byte happens to be `0xFE` (11.984 V = `0xCEFE`, or an uptime that lands on
  it) is ordinary data — it must not be discarded as a refusal (`docs/protocol.md` §NAK).
- **Default run is one-shot**: `if args.once or args.watch is None` — do not require
  `--once`. `--watch` is text-format only (no JSON streaming) and flushes every frame.
- **Exit codes are load-bearing**: `0` normal / `1` program or argument fault / `2`
  alert active. Alerts go to stderr as `ALERT [severity] name: description`; the
  frozen tests in `tests/test_monitor_format.py` and `tests/test_cli_alerts.py` lock
  the exact output strings — update them deliberately, never to make a failure pass.
- **Alerts are edge-triggered with a consecutive-poll debounce** (`consecutive_required`,
  default 2). `collect_alerts()` also returns `have_e1h` (did the E1h bitmap answer?):
  only that read covers every alert bit, so a mirror-only poll (or no answer at all)
  must make the status read `Unknown`, never `Normal`. Names left out of a poll keep the
  engine's state, so a failed read never clears an alert that is already firing. The other
  half of that rule: a poll that *does* answer calls `AlertEngine.retain()` with the names
  the device reported, because a name a model has no bit for (``ocp_pin1`` on a MEG) would
  otherwise stay latched forever after a model swap -- exporting and printing an alert the
  attached PSU cannot produce.
- **`docs/protocol.md` now matches the code** for 0xE1 (alert status), 0xC1 (alert log
  + OCP state), 0x41/0x42 (fan), 0xC0 (OCP) and 0xF1 (save). Treat the code as truth where
  they differ again, but do not describe implemented registers as "unimplemented".
- **0xC0 is an overloaded register**: the same address is `MULTIRAIL_OCP` (1 byte, `==2`,
  MEG P models only) and `OCP12V2x6_CONFIG` (8 bytes, MPG TS models only), with
  complementary model gates and MEG Ai1600T answering neither (`CPSU.cs:823-832` vs
  `CPSU.cs:840-856`). Gate on `MSIPSU.supports_ocp_config`, never on payload length.
- **0xC1 is overloaded too**: InfoID `0x00` is the 42-byte OCP state, InfoID `1..10` is the
  black-box log (`read_ocp_state` vs `read_blackbox`). Do not swap them. REV6 p.13
  defines InfoID `1` as the latest record, so `read_blackbox` returns newest-first and
  `format_blackbox` displays it in that order; the cumulative counters are shown next to
  each line but never used to reorder it (they can wrap or reset). Keep the demo's slot
  numbers and counters in the same direction.
- **`--ocp` is read-only by scope**: 一期 only *inspects* the thresholds. The write
  (`0xC0` 8 bytes + `0xF1`, clamped to 10-14 A / 4-8 A / 5-30 s / 30-240 s) is a separate,
  separately approved batch — do not add it while "fixing" the display. The *other*
  meaning of 0xC0, the MEG P 1-byte multirail switch, is exposed explicitly as
  `--set-rail` (write + `F1h` + read-back); it is not the threshold write and must stay
  model-gated.
- **An unsupported model is not an error**: `--ocp` on a MEG prints the reason and exits
  `0`, matching how `--show-log` treats an empty black box. Keep scripts callable blindly.
- **`argparse` exits `2`** for usage errors and it is deliberately not remapped, so `2`
  means "alert **or** usage error" (`docs/verify.md` §6). `1` is reserved for real faults.
- **Persistent state**: `state.json` + `daily-YYYYMMDD.log` + `alerts-YYYYMMDD.log` +
  the ephemeral `latest.json` in `/var/lib/msi-psu-monitor` (systemd `StateDirectory`),
  XDG fallback, `MSI_PSU_STATE_DIR` override. Durable writes are atomic (`.tmp` +
  `os.replace`); `latest.json` is a no-fsync 1 s cache and must stay small.
  `[daemon] alert_log/live_snapshot` can turn either off.
- **`MSI_PSU_DEMO=1` is the only synthetic data path** (`demo.py`). It must stay opt-in;
  never let demo values reach a real read.
- **`systemd/msi-psu-monitor.service` is `Type=simple`/`Restart=always`** running the
  daemon. The old `msi-psu-monitor.timer` was deleted (D-02: one daemon, not a timer).
  The sandbox lines are **active** (`ProtectSystem=full`, `ProtectHome=yes`, `PrivateTmp=yes`,
  `NoNewPrivileges=yes`, `RestrictAddressFamilies=AF_UNIX AF_NETLINK`,
  `CapabilityBoundingSet=`) — do not "uncomment the sandbox" (there is nothing to uncomment)
  and never add `PrivateDevices`: the daemon holds `/dev/hidraw*` open for its whole runtime.
  `CapabilityBoundingSet=` is intentional: root owns the device node and systemd creates the
  state directory, so no capability is needed; do not re-add one.
- **`scripts/install.sh` probes all 5 PIDs** (`808c aa6f 56d4 e749 c9eb`) and installs the
  udev rule, the unit and `/etc/msi-psu-monitor.conf` (only when absent). The unit must
  not pin `--config` at a path nothing installs: it used to, so the daemon died on start
  and `Restart=always` looped forever while `apt` reported success.
  `tests/test_packaging.py` holds this invariant — read the script, do not trust a
  comment (one here claimed `808c` only, and that was wrong).
- **Both installers ship a config**: `build_deb.sh` stages
  `/etc/msi-psu-monitor.conf` (a dpkg conffile) and `install.sh` writes it if missing.
  The example is all comments — `tests/test_packaging.py` proves installing it changes
  no value — and `install.sh` never overwrites the user's copy.
- **`daemon.main` catches `ConfigError`** and prints one `Error: ...` line (exit `1`), the
  same as the CLI. A traceback here is a systemd restart loop with 400 lines per cycle.
- **`build_deb.sh` stages with `install -m 644`, never bare `cp`**: under `umask 077` a
  `cp` shipped root-only modules and `.service` files, breaking the uaccess use case the
  udev rule exists for. `scripts/smoke.sh` builds the `.deb` under `umask 077` and reads
  the modes back out of the archive.
- **Text IO is locale-independent**: config/state/history read `utf-8-sig` and write
  `utf-8`; systemd can inherit `LC_ALL=C`. `state.atomic_write_text` fsyncs the scratch
  file and the directory, so a power cut cannot leave an empty `state.json` behind.
- **Device strings are untrusted input**: `protocol._clean_identity()` keeps printable
  ASCII and caps length; `monitor._label()` also strips C0 controls. Do not log/export a
  raw serial/product/revision before that filter — a CR/LF would forge a log or
  Prometheus line (CRA ST-008).
- **Write audit lines**: successful control writes log one INFO with mode/duty,
  `verified=true|false`, product and firmware (never the serial). Keep the model/firmware
  fields for the incident trail; the buzzer has no read-back, so it logs `verified=false`.
- **Dashboard live path**: the daemon writes `latest.json` every sample (no fsync) and the
  page polls `/api/live` once a second, overlaying it on the one-minute history; it never
  touches hidraw. A stopped daemon must leave the endpoint 503/stale, not a frozen chart.
- **Dashboard Host/CSP**: `_route()` rejects a non-loopback `Host` with 421
  (DNS-rebinding defence), and every response carries a self-contained CSP plus
  Permissions-Policy. GET and HEAD share `_route()`; do not add a second response path.
- **Official releases are self-contained**: `scripts/build_binary.sh` freezes two
  PyInstaller onefile executables (pinned `build` group; never a runtime dependency),
  built on Ubuntu 22.04/glibc 2.35 for x86_64 + arm64. The tarball installer and the
  binary `.deb` must never mention `python3`/`pip`; `tests/test_packaging.py` checks
  the dependency line and the scripts. Onefile extracts under `/tmp`, so the unit's
  `PrivateTmp=yes` is required (never add `PrivateDevices`).
- **Line endings**: `.gitattributes` enforces LF; CRLF breaks the shell scripts.
- **`kernel/` patch is out-of-tree** (Proxmox 7.0 headers unavailable) — never build it
  here; the userspace tool is the supported path.
- **`ruff format --check .` is safe repo-wide** (and is a CI gate): the four legacy files
  that mix quote styles (`protocol.py`, `__init__.py`, `__main__.py`, `tests/test_monitor.py`)
  are excluded by `[tool.ruff.format] exclude` with `[tool.ruff] force-exclude = true`, which
  also blocks them when named explicitly. Do not re-add a "don't format repo-wide" warning —
  the exclusion list is the fix, and an outdated warning here contradicted `docs/verify.md`.
