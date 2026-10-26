# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and releases use
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- **`--buzzer-toggle` is the documented name** for the C2h buzzer switch.
  `--buzzer-off` remains as a hidden deprecated alias. The hardware switch
  toggles and has no read-back, so the output still says "switch toggled",
  never "silenced".

## [1.0.1] - 2026-10-21

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
  RSS / file-descriptor ceilings and checks that the state files were written.
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

### Fixed in the 2026-10-22 full audit

- State/live data now rejects NaN/Infinity, deeply nested JSON, FIFOs and other
  special files instead of crashing or blocking the daemon/dashboard.
- Atomic writes preserve the existing file mode; `--export` also fsyncs the
  directory.
- HID `open()` is idempotent, close tolerates EBADF, framing rejects empty/
  oversized/invalid byte commands and bounds the drain loop; non-UTF-8 sysfs
  uevents no longer abort discovery.
- daemon discovery exceptions are throttled, a non-dict `get_sensors()` result
  counts as a failed read, and the prometheus failure branch survives non-OSError
  path errors.
- Alert thresholds/pin lists treat non-finite or overflowing values as missing,
  never as a recovery; >12 pins cannot create phantom pin alerts.
- `build_binary.sh` / `build_hardware_kit.sh` read the glibc version with `awk`
  instead of `head -1 | awk`, so `set -o pipefail` cannot turn the harmless
  SIGPIPE into a failed build.
- Regression tests now prove the rescan happens on the fifth consecutive failure
  (not merely on the configured constant) and that `--dump-thresholds` rejects a
  model without the 8-byte 0xC0 layout with the unsupported reason.
- `--dump-config` writes the real `[fan]` section and reports an unwritable `-O`
  as one error line; watch/once keep working when the state directory is unwritable.
- `--once` with `--export`/`--show-log`/`--show-alert-log`/`--ocp`/`--dump-thresholds`
  is now a usage error; config-sourced `output`/`serial` warn when a mode ignores them.
- 0xC0 `enabled` bytes other than 0/1 make the OCP read unusable instead of
  reporting the protection as disabled.
- demo non-TS models no longer report Zero Fan; release publishes `.sha256`
  sidecars and generates the SBOM after the hardware kit; soak fails when it
  measured no RSS/fd sample.
- `--quiet` now suppresses config/state/daemon warnings too.

Verification: **803 tests / 94% branch coverage / smoke 58 / soak 5000** on
Python 3.10.21, 3.12.3 and 3.13.15.

### Known issues

Software-level, all with machine-checked reproductions:

- The Prometheus exposition uses names that `promtool check metrics` flags as
  non-canonical: `_total` on non-counters (`msi_psu_power_total`,
  `msi_psu_current_12v_total`), counters without `_total`
  (`msi_psu_total_energy_kwh`, `msi_psu_uptime`, `msi_psu_ocp_total_time`)
  and abbreviated units in OCP metric names (`msi_psu_ocp_trigger_s`,
  `msi_psu_ocp_diff_trigger_s`, `msi_psu_ocp_warning_s`). Scraping is
  unaffected; renaming would break the `msi_psu_energy_kwh_total` alias
  required by the requirement sheet, so the decision is deferred.
- `--show-log` cannot distinguish "the device did not answer" from "the device
  holds no records"; both print the same line and exit 0.

Not verified in this release — no sample hardware was available:

- Real PSU reads and writes for all five models, including the per-model E1h
  bit order, VIN, the black box, OCP, the multirail switch, fan / Zero Fan /
  buzzer actions and power-cycle persistence.
- The 12V-2x6 OCP threshold write is a real protection write. It is exercised
  by the demo and by mocks only; it must be bench-validated before production
  use, and the original values must be restored afterwards.
- arm64 execution, a real root/systemd/udev install, a real desktop browser
  and the 24 h / 72 h soak.

## [1.0.0] - 2026-10-19

First public release: one-shot/watch CLI, JSON / Prometheus / text formats, the
resident systemd daemon with 1 s alert evaluation, 30 s node_exporter textfile,
history/energy persistence, local dashboard, fan/Zero Fan/buzzer/multirail
control, black-box and OCP inspection, source and self-contained binary
packaging, hardware acceptance kit, SBOM and release automation.
