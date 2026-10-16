# msi-psu-monitor

Userspace monitoring tool for MSI power supplies with a USB HID monitoring interface.

Supports **per-pin current monitoring** on the MPG Ai1600TS / MPG Ai1300TS (GPU
Safeguard+ feature) and standard voltage/current/power/temperature/fan readings on
MEG Ai1600(T), MEG Ai1300P, and MEG Ai1000P models.

Python standard library only — no third-party runtime dependencies.

## Features

- **One-shot, watch and machine-readable output** — text, JSON and Prometheus.
- **Per-pin 12V-2x6 current** with a software mirror of the PSU's own OCP thresholds
  (single pin > 12 A, spread > 5 A per connector).
- **Alerting with exit codes** — hardware alert bits (E1h) plus the software mirror,
  debounced, reported on stderr; `0` normal / `1` fault / `2` alert.
- **Fan display and control** — read mode/duty/Zero Fan (41h/42h), write and save a
  custom duty (41h + F1h) with read-back verification.
- **Black-box dump** — the last 10 GPU Safeguard+ trip records (`--show-log`).
- **OCP threshold inspection** — display the 12V-2x6 OCP configuration (pin trip point,
  pin spread, trigger and warning times) and the per-connector state, read-only (`--ocp`).
- **Resident daemon** — 1 s alert evaluation, 30 s atomic Prometheus textfile,
  60 s history line, rescan after 5 read failures (unplug/replug recovery).
- **Cumulative statistics** — average power/efficiency and integrated energy (kWh)
  persisted across restarts, daily buckets kept for 30 days.
- **History export** — 9-column CSV over any `m/h/d` window, to a file or stdout.
- **Local dashboard** — loopback-only charts (7 live curves + weekly energy) drawn
  from the daemon history, with per-chart PNG/CSV export.
- **Fan profile restore** — the daemon re-asserts a configured fan mode/duty every time
  it (re)opens the PSU, so a custom curve survives AC loss (`[fan]` in the config file).
- **No-hardware demo mode** — exercise the whole pipeline with `MSI_PSU_DEMO=1`, including every supported model via `MSI_PSU_DEMO_MODEL` (`ai1300p`, `meg_ai1600`, ...).

## Supported Hardware

| PSU Model | USB ID | 0xE0 Payload | Features |
|-----------|--------|--------------|----------|
| MPG Ai1600TS | `0db0:808c` | 62 bytes | Per-pin current monitoring (GPU Safeguard+), combined 12V rail |
| MPG Ai1300TS | `0db0:aa6f` | 62 bytes | Per-pin current monitoring (GPU Safeguard+), combined 12V rail |
| MEG Ai1600T | `0db0:c9eb` | 20 bytes | Combined 12V rail, no per-pin monitoring |
| MEG Ai1300P | `0db0:56d4` | 40 bytes | 5 per-rail 12V plus a combined rail, CPU/GPU wattage |
| MEG Ai1000P | `0db0:e749` | 40 bytes | 5 per-rail 12V plus a combined rail, CPU/GPU wattage |

The variant is chosen from the product string reported by the PSU, never from the USB
PID, so a re-badged device with a known product name still parses correctly.

## Install

```bash
# Debian/Ubuntu package (installs the CLI, the daemon, the udev rule and the unit)
bash scripts/build_deb.sh
sudo apt install ./dist/msi-psu-monitor_*_all.deb

# Or from source (this fork; the upstream base is linked under Attribution)
git clone <this repository>
cd msi-psu-monitor
pip install -e .

# Or a dev checkout with the test/lint toolchain
uv sync --group dev && uv run --group dev pytest -q
```

## Quick start

```bash
# One-shot read (hidraw needs root, or the udev rule grants uaccess to your session)
sudo msi-psu-monitor --once

# No PSU at hand? Drive the whole pipeline with the synthetic device
MSI_PSU_DEMO=1 msi-psu-monitor --once
MSI_PSU_DEMO=1 MSI_PSU_DEMO_MODEL=ai1300p msi-psu-monitor --once   # multi-rail model

# Continuous text refresh
sudo msi-psu-monitor --watch        # or --watch 1 for a 1s interval

# Prometheus textfile for node_exporter
sudo msi-psu-monitor -f prometheus -O /var/lib/node_exporter/msi-psu.prom
```

## Usage

```
msi-psu-monitor [-h] [-f {text,json,prometheus}] [-w [WATCH]] [-i INTERVAL] [-o]
                [-O OUTPUT] [--serial SERIAL] [--fan-mode {auto,customized}]
                [--fan-duty 0-100] [--export] [--from FROM_SPEC]
                [--columns COLUMNS] [--dashboard] [--port PORT] [--show-log]
                [--ocp] [--no-alerts] [--config CONFIG] [--verbose] [--quiet]
                [--version]

  -f, --format     Output format: text (default), json, prometheus
  -w, --watch      Watch mode; optional refresh seconds (default 2.0)
  -i, --interval   Polling interval in seconds (legacy; pairs with --watch)
  -o, --once       Read sensors once and exit (also the default)
  -O, --output     Write output to a file instead of stdout (with --watch the
                   frames are appended to that file)
      --serial     Select one of several PSUs by serial number
      --fan-mode   Write the fan control mode (41h) and save it (F1h)
      --fan-duty   Custom fan duty in percent; implies --fan-mode customized,
                   and is refused together with --fan-mode auto
      --export     Export the daemon history as CSV
      --from       Export window: 30m, 2h, 7d, ... (required with --export)
      --columns    Export columns (default: all)
      --dashboard  Serve local charts on 127.0.0.1
      --port       Dashboard port (default 8899)
      --show-log   Dump the PSU black-box alert records (C1h)
      --ocp        Show the OCP view (C0h/C1h): 12V-2x6 thresholds + state on
                   the MPG TS models, the multirail flag on the MEG P models
      --no-alerts  Skip the E1h alert poll
      --config     Explicit config file
```

Exit codes: `0` normal, `1` program/argument fault (a read failed), `2` alert active
or an argparse usage error (`2` is argparse's own convention and is not remapped).

### Examples

```bash
# Machine-readable output for scripting
sudo msi-psu-monitor -f json

# Per-pin trip history (GPU Safeguard+ black box)
sudo msi-psu-monitor --show-log

# Read-only 12V-2x6 OCP limits and per-connector state
sudo msi-psu-monitor --ocp

# Fan control: set 75% and verify, then hand back to the PSU curve
sudo msi-psu-monitor --fan-duty 75
sudo msi-psu-monitor --fan-mode auto

# Last two hours of temperature and fan as CSV
sudo msi-psu-monitor --export --from 2h --columns temp,fan -O psu-2h.csv

The `cpu`/`gpu` columns are wattages derived the way MSI Center derives them —
CPU from the 12V2 rail and GPU from 12V3+12V4+12V5 — so they are populated on the
multi-rail MEG models and stay `N/A` on the single-rail ones.

# Local charts (reads the daemon history, never touches the PSU)
msi-psu-monitor --dashboard --port 8899
```

## Example Output

```
MSI PSU: MPG Ai1600TS
  Vendor: MSI
  FW: 1.0  Serial: DEMO00000001

  +12V    :   12.092 V
  +5V     :    5.047 V
  +3.3V   :    3.310 V
  12V TOTAL:    5.168 A
  5V      :    1.800 A
  3.3V    :    0.800 A
  Per-pin currents (12V-2x6 GPU Safeguard+):
    Conn1 Pin1:    0.431 A
    ...
    Conn2 Pin6:    0.435 A
  12V-2x6 Status: Normal
  POWER   :     67.9 W   (AVG 67.90 W)
  EFF     :    88.00 %   (AVG 88.00 %)
  TEMP    :     29.0 °C
  FAN     :        0 RPM
  Zero Fan: on    Mode: auto
  Uptime     : 0d 00:00:00
  Total uptime: 5d 04:00:00
  Total energy: 0.0 kWh
```

`sudo msi-psu-monitor --ocp` adds the read-only 12V-2x6 OCP view:

```
MSI PSU: MPG Ai1600TS
12V-2x6 OCP configuration (0xC0):
  Enabled         : yes
  Pin OCP point   : 12.0 A   (range 10-14)
  Pin difference  : 5.0 A   (range 4-8)
  OCP trigger     : 20 s   (range 5-30)
  Diff trigger    : 20 s   (range 5-30)
  Warning time    : 180 s   (range 30-240)

12V-2x6 state (0xC1, 5 s averages):
  Conn1: Normal               uptime 0d 00:00:00 / total 5d 04:00:00
    Pin currents (A): 0.4  0.4  0.4  0.4  0.4  0.4
  Conn2: Normal               uptime 0d 00:00:00 / total 5d 04:00:00
    Pin currents (A): 0.4  0.4  0.4  0.4  0.4  0.4
```

`0xC0` is overloaded, so `--ocp` adapts to the model: the MPG TS models get the 8-byte
12V-2x6 thresholds and live state, the MEG P models get the 1-byte multirail flag
(`msi_psu_multirail_ocp`), and the MEG Ai1600T — which answers neither — prints that the
feature is unavailable and exits `0` (the same choice `--show-log` makes for an empty
black box, so scripts can call it unconditionally).

## Prometheus integration

The `prometheus` format targets the
[node_exporter textfile collector](https://github.com/prometheus/node_exporter#textfile-collector)
and exports `msi_psu_up` (`1` only when the sample carried sensor readings, so an
ident-only or rejected read cannot look healthy), `msi_psu_error_info{reason}` while
it is `0`, `msi_psu_info{product,vendor,fw,serial}`, rail voltages/currents,
`msi_psu_rail_voltage{rail}`/`msi_psu_rail_current{rail}` plus
`msi_psu_cpu_watts`/`msi_psu_gpu_watts` on the multi-rail MEG models,
`msi_psu_pin_current{connector,pin}`, `msi_psu_power_total`, `msi_psu_power_avg`,
`msi_psu_efficiency`, `msi_psu_efficiency_avg`, `msi_psu_temperature`,
`msi_psu_fan_speed`, `msi_psu_zero_fan{state}`,
`msi_psu_status_12v_2x6{status}`, `msi_psu_total_energy_kwh`,
`msi_psu_alert{alert}` and the uptime counters. `--ocp -f prometheus` exports the OCP
limits as `msi_psu_ocp_enabled`, `msi_psu_ocp_pin_point_a`, `msi_psu_ocp_pin_diff_a`,
`msi_psu_ocp_trigger_s`, `msi_psu_ocp_diff_trigger_s`, `msi_psu_ocp_warning_s`,
`msi_psu_ocp_status{connector}`, `msi_psu_ocp_run_time{connector}` and
`msi_psu_ocp_total_time{connector}`.

The daemon replaces the file atomically (`.tmp` + rename), so scrapers never read a
partial file:

```bash
sudo cp systemd/99-msi-psu.rules /etc/udev/rules.d/
sudo cp systemd/msi-psu-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now msi-psu-monitor

systemctl status msi-psu-monitor
journalctl -u msi-psu-monitor -f          # ALERT lines land here
```

## Configuration

Optional INI file, resolved as `/etc/msi-psu-monitor.conf` then
`~/.config/msi-psu-monitor/config.ini`; CLI flags always win. See
[`docs/msi-psu-monitor.conf.example`](docs/msi-psu-monitor.conf.example).

The optional `[fan]` section re-applies a fan profile on every daemon (re)open — the
way MSI Center re-asserts its profile when it takes the device over. It is off unless
`mode` is set, so a stock install never writes to the PSU:

```ini
[fan]
mode = customized   ; auto | customized
duty = 60           ; 0-100, ignored by the PSU in auto mode
```

State lives in `/var/lib/msi-psu-monitor` (created by the unit's
`StateDirectory`), falling back to `$XDG_STATE_HOME/msi-psu-monitor`; override with
`MSI_PSU_STATE_DIR`. It holds `state.json` (cumulative counters) and
`daily-YYYYMMDD.log` (one CSV line per minute, 30-day retention).

## Verifying without hardware

One command runs the whole chain on the synthetic PSU (all three formats, the alert
exit code, the black box, OCP, a fan write, the daemon → Prometheus + history path and
the dashboard HTTP endpoints):

```bash
bash scripts/smoke.sh
```

See [`docs/verify.md`](docs/verify.md) for the full no-hardware checklist —
quality gates, the `MSI_PSU_DEMO=1` demo mode, alert paths, the daemon + dashboard
chain, `.deb` construction, and the list of items that still require a real PSU.

[`docs/requirements-traceability.md`](docs/requirements-traceability.md) maps every
line of the requirements document to the code, the test that covers it and the
verification method, so acceptance can be ticked off item by item.

## Kernel Module
## Kernel Module

**Not usable yet — the patch in `kernel/` is an unbuilt draft.** Jack Doan's
[msi-psu](https://github.com/JackDoan/msi-psu) driver supports MEG Ai1300P and MEG
Ai1000P. `kernel/msi-psu-ai1600ts.patch` sketches MPG Ai1600TS support, but it has
never been compiled, it does not apply to a reviewed upstream revision, and its
header lists the fatal hunks (stray case labels, an undefined `iout_pins_fops`,
and no code that fills the new 62-byte struct). Treat it as notes, not as a
deliverable.

Finishing it needs the pinned upstream `msi-psu.c`, the target kernel headers and
a real 62-byte device — none of which are available here. **The supported path is
the user-space tool**; there is no kernel module to build today.

## Protocol

See [`docs/protocol.md`](docs/protocol.md) for full protocol documentation, including
the 62-byte `0xE0` bulk read layout and the register map.

## Attribution

This tree is a fork of [HesiPullupTimbo/msi-psu-monitor](https://github.com/HesiPullupTimbo/msi-psu-monitor) v1.0.0 (MIT): the
device discovery, the HID transport and the original sensor parsing come from there.
Everything added on top — the variant-aware 0xE0 parsing, the E1h alert engine, the
black-box reader, the OCP views, the daemon, the dashboard, the packaging and the
tests — is described in [`DEV_PROGRESS.md`](DEV_PROGRESS.md) and
[`docs/requirements-traceability.md`](docs/requirements-traceability.md).

The protocol details were cross-checked against the CWT REV6 USB command
specification that ships with the PSU and against MSI Center's own reading
behaviour; no vendor code was copied.

## License

MIT — see [`LICENSE`](LICENSE). The upstream MIT notice is retained verbatim in that
file, which is what the license requires of a redistribution.
