# msi-psu-monitor

Userspace Python CLI (stdlib only) reading MSI PSUs via USB HID hidraw.
Protocol rules live in `msi_psu_monitor/AGENTS.md` (auto-loaded via `opencode.json`); `docs/protocol.md` is normative for 0xE0 bulk layouts only (see divergence note below).

## Commands

```bash
pip install -e .                                    # py>=3.10, setuptools, zero dependencies
python -m pytest tests/ -q                          # no hardware needed; install pytest first (not vendored)
python -m pytest tests/test_protocol_lin11.py -q    # single file
sudo msi-psu-monitor --once                         # one-shot; hidraw needs root (PermissionError otherwise)
sudo msi-psu-monitor --watch                        # continuous, default 2s poll
sudo msi-psu-monitor -f prometheus -O /var/lib/node_exporter/msi-psu.prom
sudo ./scripts/install.sh                           # package + systemd timer
```

No CI, no lint/typecheck gate, no `[tool.ruff|mypy|pytest]` section in `pyproject.toml`.

## Gotchas (agent would miss these)

- **Stdlib only**: `os/glob/struct/select/time/argparse/json/sys`. Never add a runtime dependency (`pyproject.toml` has zero `dependencies`).
- **Variant dispatch is by product-string substring, order matters**: `Ai1600TS` → mpg before the `Ai1600` → meg wildcard, then `Ai1300`/`Ai1000` (`protocol.py:MSIPSU.init`). Never dispatch by USB PID; `PSU_PRODUCT_IDS` (4 PIDs) and the variant map are maintained separately.
- **`BULK_*` offsets are Ai1600TS-only** (62B payload: 44B data + 18B zero pad, bail if bulk `<44B`). meg_ai1600 (20B) and ai1000p/ai1300p (40B) use inline slices in `get_sensors()` — do not "unify" them onto `BULK_*`.
- **Sensors dict shape**: ident keys (`vendor/product/fw_revision/serial`) are plain strings; readings are `(value, unit)` tuples. Formatters branch on `isinstance(v, tuple)` — keep that contract.
- **LINEAR11 call pattern, keep exactly**: `lin11_to_int(struct.unpack('<H', data[o:o+2])[0], scale, signed) / scale`, rounded at call site (V/A 3dp, W 1dp, % 2dp, RPM int). `signed=False` only for fan RPM. Scales: V/A ×1000, W ×1e6, EFF ×100, TEMP ×1000.
- **HID framing**: always 64B reports, 250ms timeout, drain-before-write, strip 2-byte echo header, NAK (`0xFE`) → `None`.
- **Default run is one-shot**: `if args.once or not args.watch` — do not require `--once`. `--watch` clears the screen and is text-format only (no JSON streaming).
- **`docs/protocol.md` has diverged from code**: the working tree adds unimplemented rows (0xE1 alert status, 0xC1 alert log, 8-byte 0xC0 multirail block, fan-duty tuple, ASCII revision, length-prefixed serial). None of this exists in `protocol.py`/`monitor.py` — code is truth; do not implement from those rows without hardware to verify.
- **`scripts/install.sh` only probes `ID_MODEL_ID=808c`** (Ai1600TS). The other 3 PIDs work at runtime via `PSU_PRODUCT_IDS` — detection miss in the script is not a missing-device bug.
- **`systemd/*.service` hardening**: the commented-out sandbox lines are intentional. Do not add `PrivateDevices` — the service needs `/dev/hidraw*`. Service is `Type=oneshot`, timer is `OnCalendar=*:*:0/30`.
- **Line endings**: `.gitattributes` enforces LF; CRLF breaks `install.sh`.
- **`kernel/` patch is out-of-tree** (Proxmox 7.0 headers unavailable) — never build it here; the userspace tool is the supported path.
- **Lint state**: `ruff check` currently reports 6 pre-existing violations (F541, RUF059, BLE001, I001, RUF012). Do not claim clean, bulk-fix, or run `ruff format` repo-wide (mixed quote styles → churn diff).
