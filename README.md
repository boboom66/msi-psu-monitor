# msi-psu-monitor

Userspace monitoring tool for MSI power supplies with USB HID monitoring interface.

Supports **per-pin current monitoring** on the MPG Ai1600TS (GPU Safeguard+ feature)
and standard voltage/current/power/temperature/fan readings on MEG Ai1600(T),
MEG Ai1300P, and MEG Ai1000P models.

## Supported Hardware

| PSU Model | USB ID | 0xE0 Payload | Features |
|-----------|--------|-------------|----------|
| MPG Ai1600TS | `0db0:808c` | 62 bytes | Per-pin current monitoring (GPU Safeguard+), combined 12V rail |
| MEG Ai1600(T) | `0db0:c9eb` | 20 bytes | Combined 12V rail, no per-pin monitoring |
| MEG Ai1300P | `0db0:56d4` | 40 bytes | 6 per-rail 12V, multi-rail switching |
| MEG Ai1000P | `0db0:e749` | 40 bytes | 6 per-rail 12V, multi-rail switching |

## Quick Start

```bash
# Install
pip install msi-psu-monitor

# Or install from source
git clone https://github.com/msi-psu-monitor/msi-psu-monitor
cd msi-psu-monitor
pip install -e .

# Run (requires root for hidraw access)
sudo msi-psu-monitor --once
```

## Usage

```
msi-psu-monitor [-h] [-f {text,json,prometheus}] [-w] [-i INTERVAL] [-o] [-O OUTPUT]

Options:
  -f, --format    Output format: text (default), json, or prometheus
  -w, --watch     Continuous monitoring mode
  -i, --interval  Polling interval in seconds (default: 2.0)
  -o, --once      Read sensors once and exit
  -O, --output    Write output to file instead of stdout
```

### Examples

```bash
# One-shot text output
sudo msi-psu-monitor --once

# JSON output for scripting
sudo msi-psu-monitor --format json

# Prometheus output for node_exporter textfile collector
sudo msi-psu-monitor --format prometheus --output /var/lib/node_exporter/msi-psu.prom

# Continuous monitoring
sudo msi-psu-monitor --watch
```

## Example Output

```
MSI PSU: MPG Ai1600TS
  Vendor: MSI
  FW: 49.48  Serial:

  +12V    :   12.062 V
  +5V     :    5.007 V
  +3V3    :    3.304 V
  12V TOTAL:   82.000 A
  5V      :    8.187 A
  3V3     :    3.375 A
  Per-pin currents (12V-2x6 GPU Safeguard+):
    Conn1 Pin1:    5.312 A    Conn1 Pin2:    5.187 A
    Conn1 Pin3:    5.500 A    Conn1 Pin4:    5.312 A
    Conn1 Pin5:    5.437 A    Conn1 Pin6:    5.687 A
    Conn2 Pin1:    5.375 A    Conn2 Pin2:    5.500 A
    Conn2 Pin3:    5.375 A    Conn2 Pin4:    5.312 A
    Conn2 Pin5:    5.437 A    Conn2 Pin6:    5.437 A
  POWER   :   1040.0 W
  EFF     :    94.50 %
  TEMP    :     51.0 °C
  FAN     :      536 RPM
  Uptime     : 3d 23:37:20
  Total uptime: 9d 10:50:20
```

## Prometheus Integration

The Prometheus output format is designed for use with the
[node_exporter textfile collector](https://github.com/prometheus/node_exporter#textfile-collector).

### Automatic polling via systemd timer

```bash
# Install service and timer
sudo cp systemd/* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now msi-psu-monitor.timer

# Verify
systemctl status msi-psu-monitor.timer
```

This polls the PSU every 30 seconds and writes Prometheus metrics to
`/var/lib/node_exporter/msi-psu.prom`.

## Kernel Module

For kernel-level integration (hwmon sysfs interface), see the `kernel/` directory.
Jack Doan's [msi-psu](https://github.com/JackDoan/msi-psu) driver supports MEG Ai1300P
and MEG Ai1000P. The included patch adds MPG Ai1600TS support.

**Note:** The 7.0.x Proxmox kernel headers are not yet available in the package
repositories. Once they are released, the module can be built with:

```bash
cd kernel
patch -p1 < msi-psu-ai1600ts.patch
make -C /lib/modules/$(uname -r)/build M=$(pwd) modules
```

## Protocol

See `docs/protocol.md` for full protocol documentation, including the 62-byte
0xE0 bulk read layout and register map.

## License

MIT
