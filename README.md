# msi-psu-monitor

Userspace monitoring tool for MSI power supplies with a USB HID monitoring interface.

Supports **per-pin current monitoring** on the MPG Ai1600TS / MPG Ai1300TS (GPU
Safeguard+ feature) and standard voltage/current/power/temperature/fan readings on
MEG Ai1600(T), MEG Ai1300P, and MEG Ai1000P models.

Python standard library only — no third-party runtime dependencies.

## Features

- **One-shot, watch and machine-readable output** — text, JSON and Prometheus.
- **Per-pin 12V-2x6 current** with a software mirror of the PSU's own OCP thresholds
  (single pin ≥ 12 A — the C0h trip point is inclusive — spread > 5 A per connector).
- **Local threshold alerts** — configurable early-warning limits for total power,
  temperature, 12V-2x6 pin current/spread, per-connector current and rail current
  (`[alerts]` in the config file; set a limit to 0 to disable it). They use the
  same debounce/exit-code/alert-log path as the hardware alerts.
- **Alerting with exit codes** — hardware alert bits (E1h) plus the software mirror,
  debounced, reported on stderr; `0` normal / `1` fault / `2` alert. The daemon also
  appends every alert edge and recovery to `alerts-YYYYMMDD.log` (5 MiB rotation,
  30-day retention), and `--show-alert-log` prints it (MSI Center's AlertLog/ViewLog).
- **Fan display and control** — read mode/duty/Zero Fan (41h/42h), write and save a
  custom duty (41h + F1h) or toggle Zero Fan (43h + F1h), both with read-back
  verification; toggle the 12+4 OCP buzzer switch (C2h, no read-back); `performance` is accepted as the
  PCIE5 Cooling Wizard's name for the PSU curve (`auto`).
- **Rail protection mode** — switch the MEG Ai1000P/Ai1300P between single-rail and
  multi-rail OCP (`--set-rail`, C0h 1 byte + F1h) and verify the read-back.
- **12V-2x6 OCP threshold write** — dump (`--dump-thresholds`), write (`--ocp-set`) or
  load (`--load-thresholds`) the 8-byte configuration (C0h + F1h) with strict range
  validation and read-back verification (MPG TS models; a real protection write that
  still needs bench acceptance).
- **AC input voltage** — `vin` on the MEG models (0x20, an MSI-compatible extra
  removed from the REV6 table), shown as `AC Input` and exported as
  `msi_psu_input_voltage`.
- **Black-box dump** — the last 10 GPU Safeguard+ trip records (`--show-log`).
- **OCP threshold inspection** — display the 12V-2x6 OCP configuration (pin trip point,
  pin spread, trigger and warning times) and the per-connector state (`--ocp`, read-only);
  the same configuration is dumpable/writable as JSON via `--dump-thresholds` /
  `--load-thresholds`.
- **Resident daemon** — 1 s alert evaluation, 30 s atomic Prometheus textfile,
  60 s history line, rescan after 5 read failures (unplug/replug recovery).
- **Cumulative statistics** — average power/efficiency and integrated energy (kWh)
  persisted across restarts, daily buckets kept for 30 days.
- **History export** — 9-column CSV over any `m/h/d` window, to a file or stdout.
- **Local dashboard** — loopback-only charts (7 cards + weekly energy, including
  CPU/GPU wattage) that overlay the daemon's 1 s `latest.json` snapshot on the
  one-minute history, with per-chart PNG/CSV export and a stale-daemon marker.
- **Fan profile restore** — the daemon re-asserts a configured fan mode/duty/Zero Fan
  every time it (re)opens the PSU, so a custom curve survives AC loss (`[fan]` in the
  config file).
- **No-hardware demo mode** — exercise the whole pipeline with `MSI_PSU_DEMO=1`, including every supported model via `MSI_PSU_DEMO_MODEL` (`ai1300p`, `meg_ai1600`, ...).
- **No Python on the target machine** — the official tarball and `.deb` contain
  self-contained executables (x86_64 + arm64), built on Ubuntu 22.04 for glibc 2.35+.

## Supported Hardware

| PSU Model | USB ID | 0xE0 Reply | Features |
|-----------|--------|--------------|----------|
| MPG Ai1600TS | `0db0:808c` | 62 bytes (44 data) | Per-pin current monitoring (GPU Safeguard+), combined 12V rail |
| MPG Ai1300TS | `0db0:aa6f` | 62 bytes (44 data) | Per-pin current monitoring (GPU Safeguard+), combined 12V rail |
| MEG Ai1600T | `0db0:c9eb` | 20 bytes | Combined 12V rail, no per-pin monitoring |
| MEG Ai1300P | `0db0:56d4` | 40 bytes | 5 per-rail 12V plus a combined rail, CPU/GPU wattage |
| MEG Ai1000P | `0db0:e749` | 40 bytes | 5 per-rail 12V plus a combined rail, CPU/GPU wattage |

The reply size is the frame the device returns. A parenthesised number is the shortest
payload the parser can decode: an MPG TS frame is 62 bytes, but only the first 44 carry
sensor data, and that 44 is the gate a short reply has to clear.

The variant is chosen from the product string reported by the PSU, never from the USB
PID, so a re-badged device with a known product name still parses correctly.

## Install

The official download is **self-contained: the target machine needs no Python**.

```bash
tar xzf msi-psu-monitor_<version>_linux_x86_64.tar.gz
cd msi-psu-monitor_<version>_linux_x86_64
sudo ./install.sh
```

The tarball ships the CLI and daemon executables, the udev rule, the systemd unit,
the config example and the docs; `install.sh` copies the executables to
`/usr/local/bin`, installs the unit/udev rule and starts the daemon. arm64 tarballs
are published too. Check the download with the adjacent checksum:

```bash
sha256sum -c msi-psu-monitor_<version>_linux_x86_64.tar.gz.sha256
```

Prefer apt? The `.deb` is built from the same executables and does **not** depend
on `python3`:

```bash
sudo apt install ./msi-psu-monitor_<version>_amd64.deb
```

Building the release artifacts yourself (developers; Python 3.10+ on the build
host only):

```bash
git clone <this repository>
cd msi-psu-monitor
uv sync --group dev --group build
uv run --group dev pytest -q
bash scripts/build_binary.sh      # self-contained tarball + checksums
bash scripts/build_deb_binary.sh  # zero-Python .deb
```

See [docs/release.md](docs/release.md) for the build matrix (Ubuntu 22.04 /
glibc 2.35, x86_64 + arm64), checksums and signing status. `pip install -e .`
still works for development; it is not the official download.

## Quick start

```bash
# One-shot read (hidraw needs root, or the udev rule grants uaccess to your session)
sudo msi-psu-monitor --once

# No PSU at hand? Drive the whole pipeline with the synthetic device
MSI_PSU_DEMO=1 msi-psu-monitor --once
MSI_PSU_DEMO=1 MSI_PSU_DEMO_MODEL=ai1300p msi-psu-monitor --once   # multi-rail model
MSI_PSU_DEMO=1 MSI_PSU_DEMO_MODEL=mpg_ai1300ts msi-psu-monitor --once  # 1300W TS model

# Continuous text refresh
sudo msi-psu-monitor --watch        # or --watch 1 for a 1s interval

# Prometheus textfile for node_exporter
sudo msi-psu-monitor -f prometheus -O /var/lib/node_exporter/msi-psu.prom
```

## Usage

```
msi-psu-monitor [-h] [-f {text,json,prometheus}] [-w [WATCH]] [-i INTERVAL] [-o]
                [-O OUTPUT] [--serial SERIAL] [--fan-mode {auto,performance,customized}]
                [--fan-duty 0-100] [--zero-fan {on,off}] [--buzzer-off]
                [--set-rail {multi,single}]
                [--export] [--from FROM_SPEC]
                [--columns COLUMNS] [--dashboard] [--port PORT] [--show-log]
                [--show-alert-log]
                [--ocp] [--dump-thresholds] [--ocp-set ...]
                [--load-thresholds FILE] [--no-alerts] [--config CONFIG]
                [--dump-config] [--verbose] [--quiet] [--version]

  -f, --format     Output format: text (default), json, prometheus
  -w, --watch      Watch mode; optional refresh seconds (default: [monitor]
                   interval, 2.0)
  -i, --interval   Polling interval in seconds (only valid with --watch)
  -o, --once       Read sensors once and exit (also the default)
  -O, --output     Write output to a file instead of stdout (with --watch the
                   frames are appended to that file; --dashboard has no output)
      --serial     Select one of several PSUs by serial number
      --fan-mode   Write the fan control mode (41h) and save it (F1h);
                   performance is an alias for the PSU curve (auto)
      --fan-duty   Custom fan duty in percent; implies --fan-mode customized,
                   and is refused together with --fan-mode auto/performance
      --zero-fan   Enable/disable Zero Fan (43h) and save it (F1h); 12+4
                   (MPG TS) models only
      --buzzer-off Toggle the 12+4 OCP buzzer switch (C2h); write-only, no
                   read-back; MPG TS models only. The
                   method is a switch on the PSU (no read-back): test the second
                   invocation on hardware before treating it as idempotent
      --set-rail   Switch 12V protection between multi and single rail
                   (C0h + F1h); MEG Ai1000P/Ai1300P only, verified by read-back
      --export     Export the daemon history as CSV
      --from       Export window: 30m, 2h, 7d, ... (required with --export)
      --columns    Export columns (default: all)
      --dashboard  Serve local charts on 127.0.0.1 (it reads the history
                   files: --once/--serial/--format/-O do not apply)
      --port       Dashboard port (default 8899)
      --show-log   Dump the PSU black-box alert records (C1h; this format is
                   project-defined because MSI Center never reads that log)
      --show-alert-log  Print the local alerts-*.log (MSI AlertLog equivalent)
      --ocp        Show the OCP view (C0h/C1h): 12V-2x6 thresholds + state on
                   the MPG TS models, the multirail flag on the MEG P models
      --dump-thresholds / --ocp-dump
                   Print the hardware 12V-2x6 OCP thresholds (C0h 8 bytes) as
                   text or JSON; read-only
      --ocp-set POINT,DIFF,TRIGGER,DIFF_TRIGGER,WARNING[,on|off]
                   Write the hardware OCP thresholds (C0h + F1h) and verify by
                   read-back; MPG TS only. Ranges: 10-14 A / 4-8 A / 5-30 s /
                   5-30 s / 30-240 s. REAL PROTECTION WRITE: test on a bench PSU
                   first and have the previous values ready
      --load-thresholds FILE / --ocp-load FILE
                   Load the same values from a JSON dump and write + verify
      --no-alerts  Skip the E1h alert poll
      --config     Explicit config file
      --dump-config  Print the effective configuration (including all [alerts]
                   limits) and exit; text or json; no PSU access
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

# Zero Fan toggle and buzzer switch (MPG TS models)
sudo msi-psu-monitor --zero-fan off
sudo msi-psu-monitor --buzzer-off

# PSU curve (the PCIE5 "Performance" mode) and the MEG P rail mode
sudo msi-psu-monitor --fan-mode performance
sudo msi-psu-monitor --set-rail multi

# Local alert audit trail and its viewer
sudo msi-psu-monitor --show-alert-log

# Hardware OCP thresholds: inspect, then write + verify (MPG TS only)
sudo msi-psu-monitor --dump-thresholds -f json > ocp.json
sudo msi-psu-monitor --ocp-set 13,6,10,12,60
sudo msi-psu-monitor --load-thresholds ocp.json

# Effective settings (including [alerts] limits), no PSU needed
msi-psu-monitor --dump-config
msi-psu-monitor --dump-config -f json

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

`--dump-thresholds` prints the same configuration as text or JSON. `--ocp-set` /
`--load-thresholds` **change the PSU's protection points**: the ranges are validated
(10-14 A / 4-8 A / 5-30 s / 5-30 s / 30-240 s, no silent clamp), the 8-byte write is
followed by `F1h` and read-back (up to 3 attempts), and re-applying the current values
is a no-op. Keep a `--dump-thresholds -f json` copy first, verify on a bench unit, and
restore with `--load-thresholds`; never call it from automation.

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
`msi_psu_alert{alert}`, the local thresholds as
`msi_psu_threshold_limit{name}`/`msi_psu_threshold_alert{alert}`, and the uptime
counters. The energy counter is exported under both its descriptive name and the
REQ-8 name: `msi_psu_total_energy_kwh` and `msi_psu_energy_kwh_total` carry the same
value. Empty label sets are written in canonical exposition form (`metric{} value`,
no space). Ready-to-use alerting rules ship as
[`docs/prometheus-rules.yml`](docs/prometheus-rules.yml) (down/stale/scrape-error,
hardware alerts and threshold alerts). `--ocp -f prometheus` exports the OCP
limits as `msi_psu_ocp_available` (`1` when this model answers the C0h/C1h registers),
`msi_psu_ocp_enabled`, `msi_psu_ocp_pin_point_a`, `msi_psu_ocp_pin_diff_a`,
`msi_psu_ocp_trigger_s`, `msi_psu_ocp_diff_trigger_s`, `msi_psu_ocp_warning_s`,
`msi_psu_ocp_status{connector}`, `msi_psu_ocp_run_time{connector}` and
`msi_psu_ocp_total_time{connector}`.

The daemon refreshes the same OCP block once per prometheus write (30 s by default —
the 0xC1h state is a rolling 5 s average, so it must not be cached for the whole
session). On models without those registers — the MEG units, where 0xC1h is the
26-byte black box — it exports `msi_psu_ocp_available 0` instead of nothing, so a
dashboard can tell "not supported" from "exporter broken"; the multi-rail MEG
models add `msi_psu_multirail_ocp` (1 = per-rail protection) from the same address.

A failed read does not leave the last healthy file behind either: the daemon rewrites
the same file with `msi_psu_up 0` and the reason (`msi_psu_error_info{reason="..."}`),
once per distinct reason rather than once per second — otherwise a PSU unplugged an
hour ago still reads as `up 1` with its last wattage on every scrape.

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

The `[alerts]` section also carries the local early-warning limits
(`power_w`, `temp_c`, `pin_max_a`, `pin_imbalance_a`,
`connector_a`, `rail_12v_a`, `rail_5v_a`, `rail_3v3_a`);
0 disables one. They are separate from the PSU's own E1h protection bits and
show up as `Thresholds: ...` in text, `threshold_alerts`/
`threshold_limits` in JSON, and `msi_psu_threshold_alert`/
`msi_psu_threshold_limit` in Prometheus.

The optional `[fan]` section re-applies a fan profile on every daemon (re)open — the
way MSI Center re-asserts its profile when it takes the device over. It is off unless
`mode` or `zero_fan` is set, so a stock install never writes to the PSU:

```ini
[fan]
# Off unless `mode`/`zero_fan` is set: `auto` hands the fan back to the PSU,
# `customized` holds the fixed `duty` (0-100); `zero_fan` is the 43h switch.
mode = customized
duty = 60
zero_fan = on
```

Both installers (`apt install`, `scripts/install.sh`) drop
`docs/msi-psu-monitor.conf.example` at `/etc/msi-psu-monitor.conf`; it is entirely
commented out, so installing it changes no behaviour, and `install.sh` never
overwrites a file the user has edited.

Keep trailing comments off the value lines: ConfigParser does not strip them, so
`mode = customized   ; auto | customized` is read as the literal value
`customized   ; auto | customized`, which is no known mode — the daemon warns and
ignores the whole section. This snippet shipped in exactly that broken form until a
review caught it.

State lives in `/var/lib/msi-psu-monitor` (created by the unit's
`StateDirectory`), falling back to `$XDG_STATE_HOME/msi-psu-monitor`; override with
`MSI_PSU_STATE_DIR`. It holds `state.json` (cumulative counters and the last
sample), `latest.json` (ephemeral 1 s snapshot for the live charts; disable with
`[daemon] live_snapshot = no`), `daily-YYYYMMDD.log` (one CSV line per minute) and
`alerts-YYYYMMDD.log` (alert edges/recoveries). History and alert logs are pruned
after `retention_days` (30).

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

## Hardware test kit

When the sample machine arrives, build the ready-to-run kit (self-contained
binaries + source fallback + setup and acceptance scripts):

```bash
bash scripts/build_hardware_kit.sh
# copy dist/msi-psu-monitor-hardware-kit-*.tar.gz to the test machine
```

On the test machine: unpack, `sudo ./setup.sh`, connect the PSU USB data cable, then
`sudo ./acceptance.sh` (read-only) or `sudo ./acceptance.sh --writes`. It writes a
report and evidence tarball under `/var/log/msi-psu-acceptance/`. See
[`docs/hardware-acceptance.md`](docs/hardware-acceptance.md) for the full step-by-step
guide, including the 22.04 glibc fallback and troubleshooting. The OS install
checklist (Ubuntu ISO/USB, native vs VM, offline) is in
[`docs/machine-setup.md`](docs/machine-setup.md).

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

A Chinese walkthrough of the major features added on top of the upstream tool —
what each one does, how it is implemented, and which parts still need real hardware
— is in [`docs/新增功能与实现方案.md`](docs/新增功能与实现方案.md).

## Security and support

- [SECURITY.md](SECURITY.md) — reporting a vulnerability, security properties and
  the supply-chain baseline (SBOM, SHA-256, no runtime Python).
- [docs/support.md](docs/support.md) — support window, end-of-support and the manual
  update channel.
- [docs/incident-response.md](docs/incident-response.md) — evidence preservation and
  release-withdrawal runbook.

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

See [CHANGELOG.md](CHANGELOG.md) for the unreleased changes and the
1.0.0 release notes.

## License

MIT — see [`LICENSE`](LICENSE). The upstream MIT notice is retained verbatim in that
file, which is what the license requires of a redistribution.
