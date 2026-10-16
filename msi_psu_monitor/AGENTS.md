# PACKAGE INSTRUCTIONS — msi_psu_monitor/

Stdlib-only package (`os/glob/struct/select/time/argparse/json/sys`). Never add
third-party runtime imports.

## Protocol (normative: docs/protocol.md)

- HID framing: 64-byte reports (`CMD_BUFFER_SIZE`), 250ms timeout
  (`CMD_TIMEOUT_MS`), 2-byte echo header stripped, NAK (`0xFE`) → `None`.
- Registers: `0x10-0x13` ident, `0x20-0x42` sensors, `0xC0/0xD0/0xD1/0xE0` control.
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

## Anti-patterns

- Do NOT add pip runtime dependencies.
- Do NOT touch `BULK_*` for non-TS variants.
- Do NOT harden `systemd/*.service` with `PrivateDevices` (needs `/dev/hidraw*`).
- `--once or not watch` means the default run is one-shot; keep it.

## Verification (local only, no CI in this repo; no `[tool.ruff|mypy|pytest]` section in `pyproject.toml`)

```bash
python -m pytest tests/ -q                # needs pytest installed; lin11 vectors + 3 formatters, no hardware
ruff check msi_psu_monitor/ tests/        # 6 pre-existing violations; no repo gate
```

`ruff format` must NOT be enforced repo-wide: legacy files mix quote styles and a
format pass would create a large churn diff.
