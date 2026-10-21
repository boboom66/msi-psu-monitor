# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and releases use
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Local threshold alerts** (`[alerts]` in the INI config): total power,
  temperature, per-pin current/imbalance, per-connector current and the 12V / 5V /
  3.3V rail currents. `0` disables an individual limit. They share the alert
  engine's debounce, stderr `ALERT` line, exit code `2` and `alerts-*.log` audit
  trail, and are exported as JSON `threshold_alerts` / `threshold_limits` and
  Prometheus `msi_psu_threshold_*`.
- **Hardware OCP threshold write**: `--ocp-set` and `--load-thresholds` write the
  MPG TS 0xC0 8-byte configuration plus `F1h`, validate the ranges strictly and
  verify by read-back (3 attempts); `--dump-thresholds` exports it as text/JSON.
  Re-applying the current values is a no-op. This is a real protection write and
  still needs bench acceptance on real hardware.
- **Prometheus alert rules** in `docs/prometheus-rules.yml` for down, stale,
  scrape-error, hardware-alert and local-threshold conditions; shipped by the
  source .deb, the binary tarball and the hardware kit.
- `--dump-config` prints the effective configuration (including all `[alerts]`
  limits) as INI or JSON without touching a PSU.
- The energy counter is exported under both `msi_psu_total_energy_kwh` and the
  requirement name `msi_psu_energy_kwh_total`.
- The 0xFA51 init handshake retries 3 times with 0.5/1.0 s backoff.
- `scripts/soak.sh`: reproducible accelerated demo soak (5k samples in CI) with
  RSS / file-descriptor ceilings and state-file freshness checks.
- A strict text-exposition parser test acts as the local promtool substitute.

### Changed

- Prometheus empty-label series use the canonical `metric{} value` spelling.
- Threshold `ALERT` lines include the measured value and the configured limit.
- `--help` documents the 5 s averaging, the efficiency source and the connector
  pin order.
- The hardware-kit acceptance script also checks the local-threshold path and
  `--dump-config`.

### Fixed

- The daemon's live-dashboard payload carries the history column aliases, so
  every chart advances with `latest.json` instead of only the temperature chart.
- `--set-rail` is a no-op when the PSU already holds the requested mode.
- The buzzer switch is described as toggled/acknowledged (it has no read-back),
  never as "silenced".
- MEG serial numbers are read with their fixed 24-byte framing instead of being
  truncated.
- `-O` / `--export -O` write through symlinks, FIFOs and device nodes
  (`/dev/stdout`) instead of renaming the link away.
- The hourly state-dir prune can no longer raise out of the daemon tick.
- A failed payload read no longer clears latched per-pin or threshold alerts.

## [1.0.0] - 2026-10-19

First public release: one-shot/watch CLI, JSON / Prometheus / text formats, the
resident systemd daemon with 1 s alert evaluation, 30 s node_exporter textfile,
history/energy persistence, local dashboard, fan/Zero Fan/buzzer/multirail
control, black-box and OCP inspection, source and self-contained binary
packaging, hardware acceptance kit, SBOM and release automation.
