# Bug tracker — full-project deep audit (Phase 5)

- Repository: `msi-psu-monitor` (`/home/timzhang/projects/project/msi-psu-monitor`)
- Audit date: 2026-10-19; **updated 2026-10-22 after the second full audit**
- Audit baseline: `fdfc97d`; this ledger covers the 2026-10-22 second full audit and its follow-up doc commits. Test counts and coverage below are historical; the current gate and blockers are tracked in [RELEASE_READINESS.md](RELEASE_READINESS.md).
- Earlier ledger: [docs/testing/bug-report.md](../docs/testing/bug-report.md) DEF-001..DEF-021.
  This file is the continuing global ledger; DEF-001..DEF-021 keep their status there.

Status vocabulary: `CONFIRMED` / `FIXED` (source changed, not fully verified yet) / `VERIFIED`
(fix + regression test executed) / `BLOCKED` / `OPEN` / `REJECTED`.

Every entry below was reproduced against the real code before the fix. No entry is marked
VERIFIED on static reasoning alone.

## New findings (reproduced and fixed in this phase)

| ID | Sev | Status | Files | Category | Trigger | Actual before fix | Root cause / fix | Regression test |
|---|---|---|---|---|---|---|---|---|
| DEF-022 | P1 | VERIFIED | `msi_psu_monitor/monitor.py` | data/output safety | any `-O` / `--export -O` path that is a symlink, especially `-O /dev/stdout` with stdout redirected to a regular file | `os.replace()` replaced the symlink itself: user link became a regular file, target untouched; as root `/dev/stdout` could be replaced; otherwise exit 1 with a permission error | `emit()`/`run_export()` only take the atomic path for real files; `_must_write_through()` treats symlink/FIFO/device as direct-write targets | `test_output_through_a_symlink_keeps_the_symlink`, `test_export_through_a_symlink_keeps_the_symlink`, `test_output_to_dev_stdout_follows_the_symlink` |
| DEF-023 | P2 | VERIFIED | `msi_psu_monitor/dashboard.py` | cross-module data contract | daemon running; dashboard open; wait >1 s without a new history minute | 9 of 10 chart series never moved on the 1 s `/api/live` overlay: latest.json uses sensor keys (`vout_12v`, `power_total`) while page rows/charts use CSV column names (`12v`, `power`); only `temp` existed under both names | `/api/live` now serves `_live_view(payload)`: raw keys kept plus the history column aliases; page pushes it straight into the row array | `test_the_live_snapshot_can_feed_every_charted_series` (HTTP) and `test_the_live_overlay_actually_moves_every_chart_series` (executes shipped page JS under Node) |
| DEF-024 | P1 | VERIFIED | `msi_psu_monitor/daemon.py` | lifecycle/robustness | hourly prune while the state dir became unreadable (chmod, filesystem error) | `OSError` escaped `tick()` → daemon exited; systemd `Restart=always` restarted it into the same failure every hour | prune block wrapped in `try/except OSError/Exception`: warn, keep sampling, retry next hour | `test_a_failing_prune_does_not_kill_the_daemon` |
| DEF-025 | P2 | VERIFIED | `msi_psu_monitor/monitor.py` | alerts/state consistency | 0xE0 payload read fails while E1h still answers, after a pin-mirror alert fired | E1h `False` bits were read as a recovery the mirror never measured: pin alert disappeared (RECOVERED logged) and `pin_imbalance` was dropped silently by `retain()` | on a payload-less poll, mirror-owned names are removed from the update dict so the engine keeps them latched; `retain()` keeps `pin_imbalance` while the model still reports `ocp_pin*` bits | `test_a_failed_payload_read_does_not_clear_a_mirror_alert`; existing model-swap test still passes |
| DEF-026 | P2 | VERIFIED | `scripts/smoke.sh`, `tests/test_e2e_cli.py`, `tests/test_docs_consistency.py` | release process | version bump in `pyproject.toml` | smoke.sh inspected a hardcoded `msi-psu-monitor_1.0.0_all.deb` (stale/missing artifact); the real-entry-point test asserted the literal `1.0.0` | smoke.sh reads the version from pyproject; e2e asserts the package `__version__`; a docs-consistency test forbids literal artifact versions in `scripts/**/*.sh` | `test_shell_scripts_do_not_hardcode_the_release_artifact_version`, updated `test_the_real_entry_point_reports_its_version` |
| DEF-027 | P3 | VERIFIED | `scripts/build_hardware_kit.sh` | hardware-acceptance correctness | build kit on glibc != 2.39 (CI builds on Ubuntu 22.04 / 2.35) | `START-HERE.md` claimed the binary was built on glibc 2.39 while `BUILD-INFO` recorded the real floor; tester reads the wrong compatibility floor | `GLIBC` captured once, substituted into START-HERE (`__GLIBC__`) and BUILD-INFO | `test_the_kit_start_page_reports_the_real_build_glibc` |
| DEF-028 | P3 | VERIFIED | `msi_psu_monitor/daemon.py` | CLI robustness | `--state-dir "$DIR"` / `--prom-path "$P"` with the variable unset (empty string) | flag accepted and silently ignored; daemon used the packaged/default paths | daemon `main()` rejects empty `--config`/`--state-dir`/`--prom-path` with argparse exit 2, matching the CLI empty-path rule | `test_empty_path_arguments_are_usage_errors` (3 params) |
| DEF-029 | P3 | VERIFIED | `msi_psu_monitor/state.py` | resource/memory | `--show-alert-log` after weeks of 5 MiB alert logs (plus rotated copies) | every line of every log was materialised in a list before taking the newest 200 — potentially hundreds of MB on a small monitoring host | `iter_alert_log()` streams into `deque(maxlen=limit)` when a limit is given (same newest-N result, bounded memory) | `test_iter_alert_log_limit_keeps_the_newest_lines_in_order` |
| DEF-030 | P4 | VERIFIED | `msi_psu_monitor/daemon.py` | docs/behavior mismatch | `msi-psu-monitor-daemon --help` | help promised "Stop after N positive samples" while the loop counts every pass, including failed reads | help/docstring now say "sample-loop passes (failed reads still count)"; bounded smoke semantics unchanged | verified by `--help` output (text-only fix) |
| DEF-031 | P3 | VERIFIED | `msi_psu_monitor/dashboard.py` | HTTP semantics | `/api/typo` on a host where the daemon has never run | state-directory gate ran before route matching, so a client typo got 503 "no state directory" instead of 404 | gate now applies only to the four real API routes; unknown paths fall through to 404 | `test_an_unknown_api_route_is_404_even_without_a_state_dir` |


## psu-file 对比轮（2026-10-19，DEF-032..035）

触发来源：对照 `psu-file/01_需求文档/*`、`04_MSI-Center源码` 与 `05_截图` 的逐项复核；
完整矩阵见 [docs/testing/psu-file-gap-analysis.md](../docs/testing/psu-file-gap-analysis.md)。

| ID | Sev | Status | Files | Category | Trigger | Actual before fix | Root cause / fix | Regression test |
|---|---|---|---|---|---|---|---|---|
| DEF-032 | P2 | VERIFIED | `msi_psu_monitor/{monitor,protocol}.py`, README, docs, smoke | misleading success report | `--buzzer-off` | printed `Buzzer: silenced` and docs claimed silence, but C2h is MSI's no-value, no-read-back `BUZZER_SWITCH`: a second run re-arms the buzzer while the user thinks it is off | output/help/audit/README/协议统一为 "switch toggled (no read-back)"；method docstring cites CPSU.cs:1148-1159 | `test_buzzer_off_writes_and_reports_the_switch`, audit-line test, smoke 58 |
| DEF-033 | P2 | VERIFIED | `msi_psu_monitor/monitor.py` | idempotency/flash wear | `--set-rail <mode>` when already in that mode | always wrote 0xC0 + F1h; draft REQ-11 says read first and return on equal value (hardware errors on same-value write) | `apply_rail_mode()` pre-reads and returns `(mode, False)`; output "already set", audit has `changed=...` | `test_set_rail_is_a_noop_when_already_in_the_requested_mode` |
| DEF-034 | P3 | VERIFIED | `msi_psu_monitor/dashboard.py` | UI parity | dashboard open | 7 cards were 12V/5V/3.3V/12V-total-current/temp/fan/power(eff mixed in); MSI's set is temp/12V/5V/3.3V/fan/efficiency/wattage | CHARTS now 12V/5V/3.3V/efficiency/temp/fan/power(CPU/GPU/Total); total current stays in history/export/Prometheus | `test_the_seven_charts_match_the_msi_dashboard`, Node live harness |
| DEF-035 | P3 | VERIFIED | `msi_psu_monitor/protocol.py` | data correctness | MEG model 0x13 reply with non-zero tail | serial took the whole reply and relied on zero padding after 24 bytes | model-aware framing: MPG TS length prefix, MEG fixed 24 bytes (CPSU.cs:515-528), unknown model keeps the heuristic | `test_a_meg_serial_is_cut_to_the_msi_fixed_length` |

修复后回归：661 passed；ruff/format/mypy clean；coverage 92%；smoke 58/58。

## Needs review / not fixed (honest residue)

| ID | Sev | Status | What | Why it is not fixed / next step |
|---|---|---|---|---|
| NR-001 | P3 | **RESOLVED (re-run 2026-10-22)** | `promtool 2.45.3` on the current 1.0.1 daemon textfile accepts `metric{} value` (no space) with **no syntax errors**; it reports 8 naming-policy warnings (`_total`/`_s` suffixes), not parse errors. `promtool check rules docs/prometheus-rules.yml` → SUCCESS (5 rules). The naming decision remains open, not a parser bug. |
| NR-002 | P3 | **FIXED / VERIFIED** | Negative count/energy/daily values are clamped/dropped at load with a warning; `test_negative_state_counters_do_not_produce_negative_totals`, `test_negative_daily_energy_buckets_are_dropped`. |
| NR-003 | P3 | **FIXED / VERIFIED** | Config-sourced `output`/`serial` now print an explicit warning when the selected mode does not use them (`--dashboard`, `--export`, `--show-alert-log`); explicit CLI combinations still exit 2. Tests: `test_config_*_not_silently_ignored_by_*`. |
| NR-004 | P3 | OPEN | `--show-log` cannot distinguish a NAK/timeout on C1h from "device holds no records"; both print "No black-box alert records stored." and exit 0 | The protocol returns `None` both for "slot absent" and "no answer", and the documented contract treats an empty black box as success. Needs a device capture to distinguish. |
| NR-005 | P2 | BLOCKED | Real PSU reads/writes, per-model E1h, VIN, black box, OCP, multirail, fan/Zero Fan/buzzer, unplug/reconnect | No MSI PSU attached in this environment. Kit ready: [docs/hardware-acceptance.md](../docs/hardware-acceptance.md). |
| NR-006 | P2 | BLOCKED | arm64 binary execution; real root/systemd/udev install; real desktop browsers; 24 h/72 h soak | Environment limits (x86_64 WSL, no passwordless root, headless Chromium shell now missing `libnspr4`). CI builds arm64 but only executes x86_64. |

## Previously open item still open

- DEF-002 (P3, metadata: Beta classifier, example e-mail, upstream URLs) — unchanged from
  [docs/testing/bug-report.md](../docs/testing/bug-report.md). Release decision pending.
## Second full audit (2026-10-22)

AUD-01..AUD-14 (NaN/FIFO/Recursion/permissions/contracts/release/docs/soak) are
recorded with their regression tests in
[FIX_LOG.md §全项目审计第二轮](FIX_LOG.md). The contract changes from that round are:

- `--once` + `--export/--show-log/--show-alert-log/--ocp/--dump-thresholds` → usage error (exit 2).
- Config `output`/`serial` ignored by a mode → explicit warning; explicit CLI flags still exit 2.
- 0xC0 `enabled` bytes other than 0/1 → C0h read unusable (not “disabled”).

## Independent re-audit (2026-10-27)

Scope: the whole `work/product-v2` tree (protocol/state/daemon/dashboard/alerts/
config/demo/menu/termdash, scripts, unit, udev, CI). Method: line-by-line read,
cross-check against `docs/protocol.md` and CPSU.cs anchors already quoted in the
tree, local ruff/format/mypy, and the full Linux suite via fork CI (Windows cannot
collect the POSIX-only modules). Existing tests were re-read, not trusted by name.

| ID | Sev | Status | Files | Category | Trigger | Actual before fix | Root cause / fix | Regression test |
|---|---|---|---|---|---|---|---|---|
| DEF-036 | P2 | **VERIFIED** | `msi_psu_monitor/protocol.py` | data correctness | VIN (0x20) on a MEG model encoded with a negative LINEAR11 exponent | integer shift truncated sub-volt values: 461 x 2**-1 V (230.5 V) was reported as 230.0 V while the CLI prints 0.1 V and MSI's `ValueCalc` is floating (`CPSU.cs:1248`) | `read_vin()` decodes with `_lin11_float()` | `test_read_vin_keeps_sub_volt_precision` |
| DEF-037 | P2 | **VERIFIED** | `msi_psu_monitor/daemon.py` | diagnosability/ops | daemon with `[monitor] serial` that matches nothing (typo, or the wrong unit plugged in) | every discovery miss was a debug line once per 5 s: the unit stayed "active", sampled nothing, and the journal had no visible reason | `_discover()` keeps `available`/`blocked`; `_note_discovery_miss()` warns once per distinct reason and resets after a successful open | `test_an_unattached_serial_is_explained_once`, `test_unopenable_devices_are_explained_once` |
| DEF-038 | P3 | **VERIFIED** | `msi_psu_monitor/monitor.py` | CLI contract | `--dump-config --menu` | `--menu` was accepted and silently ignored (dump-config exits before the menu) | `--menu` added to the dump-config conflict list → usage error, exit 2 | `test_dump_config_rejects_menu` |
| DEF-039 | P3 | **VERIFIED** | `msi_psu_monitor/monitor.py` | CLI contract | `[monitor] output = ...` together with `--dashboard-text` | the config-sourced path was accepted and silently ignored; the live view owns the terminal | explicit "ignoring [monitor] output" warning, matching `--dashboard` | `test_config_output_is_not_silently_ignored_by_dashboard_text` |
| DEF-040 | P3 | **VERIFIED** | `msi_psu_monitor/protocol.py` | protection-state correctness | 0xC0 multirail byte other than 1/2 (0, 3, 0xFF) | `data[0] == 2` reported every other byte as "single rail": a protection mode the PSU never stated | undefined bytes return `None` (like an invalid `enabled` byte in the 8-byte 0xC0 read) | `test_read_multirail_ocp_refuses_an_undefined_byte` |
| DEF-041 | P3 | **VERIFIED** | `msi_psu_monitor/monitor.py` | CLI clarity | `--dashboard-text --menu` | rejected, but the message named `--watch` (dashboard-text injects a synthetic watch value before the menu check) | the dashboard-text conflict list names `--menu` itself | `test_dashboard_text_and_menu_conflict_names_the_menu_flag` |

Not re-fixed / still open after this pass: NR-004 (black box NAK vs empty
indistinguishable), NR-005/NR-006 (hardware, arm64, root install, 24 h). The
`--watch` path still does not reopen a device that disappears (documented as a
daemon-only recovery); no change made, recorded here so it is not mistaken for
covered.
### Round 2 of the same pass

| ID | Sev | Status | Files | Category | Trigger | Actual before fix | Root cause / fix | Regression test |
|---|---|---|---|---|---|---|---|---|
| DEF-042 | P2 | **VERIFIED** | `msi_psu_monitor/{monitor,daemon}.py` | statistics correctness | `--watch 600`, or `[daemon] sample_interval` above 300 s | `MAX_SAMPLE_GAP_S` (300 s, the suspend/outage guard) also capped the *normal* gap, so every sample was skipped and the kWh integral froze for the whole run while the AVG kept moving | callers pass a gap budget of `max(300, interval * 2)`; `apply_stats()` takes the caller's `ts` so the daemon's injected wall clock is used consistently (the mismatch was found by the new test) | `test_a_slow_cadence_integrates_with_a_wider_gap_guard`, `test_energy_integrates_at_a_slow_configured_cadence` |
### Round 3 of the same pass (deep hardening vs the module's own invariant)

| ID | Sev | Status | Files | Category | Trigger | Actual before fix | Root cause / fix | Regression test |
|---|---|---|---|---|---|---|---|---|
| DEF-043 | P2 | **VERIFIED** | `msi_psu_monitor/state.py` | special-file guard evasion | state directory containing a symlink aimed at a FIFO (or `/dev/zero`) | `Path.is_file()` follows symlinks, so every "reject special files" guard passed and the reader then blocked forever — daemon history write, dashboard history listing, alert-log viewer, `state.json`/`latest.json` load | `state.is_regular_file()` decides by lstat; six open sites use it | `test_symlinks_to_special_files_are_rejected_like_their_target` |
