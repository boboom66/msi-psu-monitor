# msi-psu-monitor

Userspace Python CLI + daemon (stdlib only) reading MSI PSUs via USB HID hidraw.
Protocol rules live in `msi_psu_monitor/AGENTS.md` (auto-loaded via `opencode.json`);
`docs/protocol.md` is normative for the register map and 0xE0 bulk layouts.

## Commands

```bash
uv sync --group dev                                  # py>=3.10, dev toolchain (pytest/ruff/mypy), zero runtime deps
uv run --group dev pytest -q                         # 145 tests, no hardware needed
uv run --group dev pytest -q tests/test_state.py     # single file
uv run --group dev ruff check .                      # must be clean
uv run --group dev mypy msi_psu_monitor/             # must be clean
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --once      # full pipeline, no PSU attached
sudo msi-psu-monitor --once                          # one-shot; hidraw needs root (or the udev uaccess rule)
sudo msi-psu-monitor --watch 1                       # continuous, 1s poll
sudo msi-psu-monitor -f prometheus -O /var/lib/node_exporter/msi-psu.prom
msi-psu-monitor --dashboard --port 8899              # loopback charts over the daemon history
bash scripts/build_deb.sh                            # .deb into dist/
sudo ./scripts/install.sh                            # package + systemd daemon unit
```

`docs/verify.md` is the full no-hardware checklist — use it instead of improvising.
CI (`.github/workflows/ci.yml`) runs ruff + mypy + pytest on py3.10/3.12.

## Gotchas (agent would miss these)

- **Stdlib only**: never add a runtime dependency (`pyproject.toml` has zero
  `dependencies`), including for the dashboard and the demo mode.
- **Variant dispatch is by product-string substring, order matters**: `Ai1600TS` → mpg
  before the `Ai1600` → meg wildcard, then `Ai1300`/`Ai1000` (`protocol.py:MSIPSU.init`).
  Never dispatch by USB PID; `PSU_PRODUCT_IDS` (5 PIDs) and the variant map are
  maintained separately.
- **`BULK_*` offsets are Ai1600TS-only** (62B payload: 44B data + 18B zero pad, bail if
  bulk `<44B`). meg_ai1600 (20B) and ai1000p/ai1300p (40B) use inline slices in
  `get_sensors()` — do not "unify" them onto `BULK_*`.
- **Sensors dict shape**: ident keys (`vendor/product/fw_revision/serial`) are plain
  strings; readings are `(value, unit)` tuples. Formatters branch on
  `isinstance(v, tuple)` — keep that contract.
- **LINEAR11 call pattern, keep exactly**:
  `lin11_to_int(struct.unpack('<H', data[o:o+2])[0], scale, signed) / scale`, rounded at
  the call site (V/A 3dp, W 1dp, % 2dp, RPM int). `signed=False` only for fan RPM.
  Scales: V/A ×1000, W ×1e6, EFF ×100, TEMP ×1000.
- **HID framing**: always 64B reports, 250ms timeout, drain-before-write, strip 2-byte
  echo header, NAK (`0xFE`) → `None`.
- **Default run is one-shot**: `if args.once or args.watch is None` — do not require
  `--once`. `--watch` is text-format only (no JSON streaming) and flushes every frame.
- **Exit codes are load-bearing**: `0` normal / `1` program or argument fault / `2`
  alert active. Alerts go to stderr as `ALERT [severity] name: description`; the
  frozen tests in `tests/test_monitor_format.py` and `tests/test_cli_alerts.py` lock
  the exact output strings — update them deliberately, never to make a failure pass.
- **Alerts are edge-triggered with a consecutive-poll debounce** (`consecutive_required`,
  default 2). `collect_alerts()` also returns `have_data`: with no E1h answer and no pin
  mirror the status must read `Unknown`, never `Normal`.
- **`docs/protocol.md` now matches the code** for 0xE1 (alert status), 0xC1 (alert log),
  0x41/0x42 (fan), 0xC0 (OCP) and 0xF1 (save). Treat the code as truth where they differ
  again, but do not describe implemented registers as "unimplemented".
- **Persistent state**: `state.json` + `daily-YYYYMMDD.log` in
  `/var/lib/msi-psu-monitor` (systemd `StateDirectory`), XDG fallback, `MSI_PSU_STATE_DIR`
  override. Both writes are atomic (`.tmp` + `os.replace`); keep it that way.
- **`MSI_PSU_DEMO=1` is the only synthetic data path** (`demo.py`). It must stay opt-in;
  never let demo values reach a real read.
- **`systemd/msi-psu-monitor.service` is `Type=simple`/`Restart=always`** running the
  daemon. The old `msi-psu-monitor.timer` was deleted (D-02: one daemon, not a timer).
  The commented sandbox lines are intentional — do not add `PrivateDevices`, the daemon
  holds `/dev/hidraw*` open for its whole runtime.
- **`scripts/install.sh` only probes `ID_MODEL_ID=808c`** (Ai1600TS). The other 4 PIDs
  work at runtime via `PSU_PRODUCT_IDS` — a detection miss in the script is not a
  missing-device bug.
- **Line endings**: `.gitattributes` enforces LF; CRLF breaks the shell scripts.
- **`kernel/` patch is out-of-tree** (Proxmox 7.0 headers unavailable) — never build it
  here; the userspace tool is the supported path.
- **`ruff format` must not run repo-wide**: `protocol.py`, `__init__.py`, `__main__.py`
  and `tests/test_monitor.py` mix quote styles, so a full pass creates a churn diff.
  Format only the files you touched (`uv run --group dev ruff format <files>`).
