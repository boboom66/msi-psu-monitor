# Naming and units matrix — TUI vs text vs JSON vs Prometheus vs live overlay

Baseline: `work/product-v2` @ `2a8b680`. Evidence: code reading on this commit.
Each concept must have one name and one unit per surface; TTY text may be
human-friendly, machine keys must be stable.

## Concepts

| Concept | TUI (termdash) | text (`--once`) | JSON keys | history/CSV column | Prometheus metric | live overlay alias |
|---|---|---|---|---|---|---|
| 12 V rail voltage | `+12V` | `+12V` | `vout_12v` | `12v` | `msi_psu_voltage_volts{rail="12v"}` | `12v` ← `vout_12v` |
| 5 V rail voltage | `+5V` | `+5V` | `vout_5v` | `5v` | `msi_psu_voltage_volts{rail="5v"}` | `5v` ← `vout_5v` |
| 3.3 V rail voltage | `+3.3V` | `+3.3V` | `vout_3v3` | `3v3` | `msi_psu_voltage_volts{rail="3v3"}` | `3v3` ← `vout_3v3` |
| 12 V total current | — | `12V TOTAL` | `iout_12v_total` | `total_a` | `msi_psu_current_amps{rail="12v"}` | `total_a` ← `iout_12v_total` |
| 5 V current | — | `5V` | `iout_5v` | (not in history) | `msi_psu_current_amps{rail="5v"}` | — |
| 3.3 V current | — | `3.3V` | `iout_3v3` | (not in history) | `msi_psu_current_amps{rail="3v3"}` | — |
| Per-pin currents | `Conn1 P1…P6`, `Conn2 P1…P6` | `Conn1 Pin1…` | `iout_pins` | (not in history) | `msi_psu_pin_current_amps{conn=…,pin=…}` | — |
| Total power | `POWER` | `POWER` | `power_total` | `power` | `msi_psu_power_watts` | `power` ← `power_total` |
| Efficiency | `EFF` | `EFF` | `efficiency` | `eff` | `msi_psu_efficiency_ratio` (×100 %) | `eff` ← `efficiency` |
| Temperature | `TEMP` | `TEMP` | `temp` | `temp` | `msi_psu_temperature_celsius` | `temp` (same name) |
| Fan speed | `FAN` | `FAN` | `fan_rpm` | `fan` | `msi_psu_fan_speed_rpm` | `fan` ← `fan_rpm` |
| 12 V-2x6 status | `12V-2x6 Status` | `12V-2x6 Status` | `status` | (not in history) | `msi_psu_ocp_state{…}` | — |
| CPU power (P models) | — | — | `cpu_w` | `cpu_w` | `msi_psu_power_watts{rail="cpu"}` | `cpu_w` (same) |
| GPU power (P models) | — | — | `gpu_w` | `gpu_w` | `msi_psu_power_watts{rail="gpu"}` | `gpu_w` (same) |

## Verified consistent

- TUI labels match the `text` formatter for every shared concept (`+12V`,
  `+5V`, `+3.3V`, `POWER`, `EFF`, `TEMP`, `FAN`) — checked by reading
  `termdash._ROWS` against `monitor.format_text`.
- The live overlay (`dashboard.LIVE_HISTORY_KEYS`) covers **every** charted
  series; the page JS test (`test_the_live_overlay_actually_moves_every_chart_series`)
  executes the shipped script with the real payload shape.
- Units in TUI and text: V/A/W/%/°C/RPM with the same decimal places (V/A 3,
  W 1, % 2, RPM integer).

## Gaps found

| # | Gap | Severity | Action |
|---|---|---|---|
| G-1 | JSON `fan_rpm` value is a **float** (`1240.0`) while TUI/text render an integer; JSON consumers formatting with `%.0f` see `1240.000000` | P3 cosmetic | Not changed in v2 (schema stability); document in `--help` |
| G-2 | `EFF` is the only TUI label that does not spell out its unit; it prints `93.60 %` — fine — but the label is `EFF`, not `Efficiency` | P3 cosmetic | Accept: MSI Center uses the same abbreviation |
| G-3 | Prometheus efficiency is exported as `msi_psu_efficiency_ratio` while every other surface speaks percent; the ratio is ×100 of the displayed number | P2 naming | Existing behaviour kept for compatibility; the naming-policy decision (B-008) already tracks it |
| G-4 | The 5 s rolling-average nature of `iout_12v_total` and the pin currents is documented in `--help` but invisible in TUI and dashboard | P3 | Accepted: repeating it on every frame would cost width |
| G-5 | `12V TOTAL` in text vs no total row in TUI: the TUI shows the 12 V *voltage* bar but not the total *current* | P2 UX | Candidate for a later TUI row; not fixed here (space budget at 80 cols) |

## Conclusion

No blocking inconsistency. Machine-facing surfaces (JSON/CSV/Prometheus/live)
use one canonical key each; human-facing surfaces (TUI/text) agree on labels
and units. The gaps above are recorded for G2 instead of being changed now.
