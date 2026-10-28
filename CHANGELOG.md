# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and releases use
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Menu visual refresh**: the interactive menu is now a boxed card with a
  title/version and a colour-coded `last:` status (green ok, red exit, yellow
  stopped), group headings with item counts, aligned action/command columns and
  a full-width reverse-video selection bar. It uses only standard 8/16-colour
  SGR, keeps `NO_COLOR`, and falls back to ASCII borders on `TERM=linux` or a
  non-UTF-8 locale so the VGA console cannot hit a UnicodeEncodeError.
- **`psu` front door**: the installed `psu` command opens the interactive menu
  with no arguments and passes any explicit arguments through unchanged
  (`psu --once` == `msi-psu-monitor --once`). Shipped by the source install,
  the tarball and both `.deb` packages.
- **REV6 command coverage**: IOUT_12+4 (`0x2C`) is now read directly by
  `--pins` (12 currents as 5 s averages, text/JSON/Prometheus, menu entry), and
  `MFR_MODEL` (`0x11`, 12 ASCII bytes) repairs an 11-byte handshake that would
  otherwise truncate "MPG Ai1600TS" to "MPG Ai1600T". When the 0xE0 bulk frame
  is missing or short, the sample falls back to the individual
  `0x24`-`0x2B`/`0x30`/`0x40` registers (plus `0x2C` on the 12+4 models) and
  reports `read_mode=registers` instead of pretending the PSU measured nothing.
- **The menu covers every action**: snapshot (text/JSON/Prometheus), live view
  (fixed or prompted interval), terminal and web dashboards, CSV export
  (last hour or prompted window/columns), OCP view, pin currents, threshold
  dump, black box, alert log, fan auto/custom duty, Zero Fan, buzzer, rail
  mode, OCP write/load, effective config, and the serial filter — 23 entries in
  four groups. Every write prompts for its parameters and asks for explicit
  confirmation before touching the PSU.
- **Menu thresholds entry**: a read-only `--dump-thresholds` view joins
  the `--menu` command list, so the MPG TS 0xC0 configuration can be inspected
  from the menu like `--ocp`, without a write path anywhere near it.
- **Menu alert-log entry**: `--show-alert-log` runs from `--menu` without
  touching hidraw, so a running daemon keeps the device. The menu footer and
  the numbered prompt now follow the item count instead of a hard-coded `1-7`.
- **Dashboard live badge**: the 1 s `/api/live` poll now drives a visible
  `● live` / `○ not updating` badge, so a stopped daemon stops *looking* live
  after ten missed polls while the history keeps serving.
- **PTY evidence tests** (`tests/test_pty_watch.py`): `--watch` in-place redraw
  with cursor restore, pipe mode with no escape codes, `--dashboard-text`
  SIGINT cleanliness, and a too-small PTY falling back to streaming.

### Changed

- **`--menu` rewritten as a grouped interactive menu**. Arrow keys (both the
  `CSI` and the `ESC O` application-cursor spellings that tmux/vim leave
  behind) move the selection, digits jump, `q`/`Esc` quit, `?` toggles the key
  legend, the list scrolls on short terminals, `NO_COLOR` is honoured and the
  VGA console (`TERM=linux`) stays on the main screen. The menu draws on the
  alternate screen while idle but leaves it for each action, so action output
  survives on the normal screen, and the header keeps the last action's
  result (`Snapshot ok` / `exit 2` / `stopped`). Entries are grouped
  (Monitor/History/System) and dispatch is a data-driven action table; the
  interaction model follows simple-term-menu, console-menu, pick and
  PyTermGUI (all four MIT licence files verified against their sdists), but no
  third-party library is used — the zero-runtime-dependency rule holds.
- **`--buzzer-toggle` is the documented name** for the C2h buzzer switch.
  `--buzzer-off` remains as a hidden deprecated alias. The hardware switch
  toggles and has no read-back, so the output still says "switch toggled",
  never "silenced".

### Fixed

- **AC input voltage lost sub-volt precision**: VIN was decoded with an integer
  LINEAR11 shift, so a device encoding such as 461 x 2^-1 V (230.5 V) was shown
  as 230.0 V while the frame prints 0.1 V. It now uses the same floating decode
  as MSI's `ValueCalc`.
- **Energy stopped accumulating at slow sampling cadences**: the 300 s gap guard
  also capped the normal interval, so `--watch 600` or
  `[daemon] sample_interval = 600` skipped every sample and froze the kWh total
  (the average kept moving, which hid it). Callers now pass a gap budget of
  `max(300, interval * 2)`, and the daemon uses its injected wall clock for the
  integral it writes next to the history.
- **Daemon sampled nothing without saying why**: `[monitor] serial` that matched
  no attached device, and devices that all failed to open, were only logged at
  debug level once per five seconds. Discovery misses now raise one warning per
  distinct reason and reset after a successful open.
- **A symlink in the state directory could hang the daemon or dashboard**:
  `Path.is_file()` follows symlinks, so a symlink to a FIFO or `/dev/zero` passed
  the special-file guards and blocked the open forever. All state/history/
  alert-log/live reads and appends now decide with `lstat`.
- **Undefined 0xC0 multirail byte reported as "single rail"**: bytes other than
  the two defined states (1 = combined, 2 = per-rail) now make the read
  unusable instead of claiming a protection mode the PSU never sent.
- **`--dump-config --menu` silently ignored `--menu`**, and `--dashboard-text`
  silently ignored a config-sourced `[monitor] output`; both now behave like the
  other modes (usage error / explicit warning).
- **Confusing `--dashboard-text --menu` rejection**: the error named `--watch`
  although the user never passed it.
- **Terminal dashboard box alignment with colour**: padding counted ANSI escape
  bytes as columns, so the right border wandered nine columns to the left for
  every coloured value. Rows are now padded by visible width.
- **Terminal dashboard truncation**: a narrow terminal could cut the header
  inside a colour sequence and garble the frame; long identity strings and wide
  rows are now cut on visible-width boundaries with colours re-closed.
- **Menu `?` key**: it was decoded as "help" but silently ignored; it now
  toggles the key legend, and `0` quits the arrow-key menu like the numbered
  prompt always did.
- **Cursor not restored when a live view is interrupted**: `run_watch` and
  `run_dashboard_text` restored the cursor on their own paths, but an
  interruption that escaped the loop's `finally` (a signal arriving between
  frames) could leave the cursor hidden for the rest of the terminal session.
  The process exit path now restores it unconditionally on a TTY.
- **Dashboard live badge**: a stopped daemon kept the page looking live until
  the history poll caught up; the 1 s `/api/live` poll now drives a visible
  `● live` / `○ not updating` badge (10 missed polls turn it amber).

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
