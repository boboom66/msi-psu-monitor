# Fix log — Phase 5 deep audit

Baseline `fdfc97d`; all changes below are **uncommitted** (this audit task forbids committing or
publishing without explicit authorization). Every row names the regression test that fails on the
old code path and passes now.

| Bug | Files changed | Change | Regression evidence |
|---|---|---|---|
| DEF-022 | `msi_psu_monitor/monitor.py` | added `_must_write_through()`; `emit()` and `run_export()` write through symlinks/FIFOs/devices instead of `os.replace()`-ing their names | 3 new CLI/e2e tests; reproduced first: `emit('x', link)` left `link` as a regular file and the real target unchanged |
| DEF-023 | `msi_psu_monitor/dashboard.py` | added `LIVE_HISTORY_KEYS` + `_live_view()`; `/api/live` returns raw sensor keys **and** daily-log column names | HTTP key test + Node harness executing the shipped page JS (before: 3 rows, 1 point on 12V; after: 3/3) |
| DEF-024 | `msi_psu_monitor/daemon.py` | `tick()` prune block wrapped; OSError/unexpected → warning, next prune in an hour | reproduced by monkeypatching `prune_history` to raise `PermissionError` after 3601 s; old code raised out of `tick()` |
| DEF-025 | `msi_psu_monitor/monitor.py` | `collect_alerts()` drops E1h-True mirror bits only; on a payload-less poll it removes mirror-owned False names from the update and keeps `pin_imbalance` in `retain()`'s known set | reproduced: old code logged RECOVERED `ocp_pin1` and silently dropped `pin_imbalance`; new test asserts both stay latched, existing model-swap test still drops them |
| DEF-026 | `scripts/smoke.sh`, `tests/test_e2e_cli.py`, `tests/test_docs_consistency.py` | version parsed from `pyproject.toml` (single home); e2e compares against `msi_psu_monitor.__version__`; guard test scans shell scripts for literal artifact versions | `test_shell_scripts_do_not_hardcode_the_release_artifact_version`; old smoke path was a literal `1.0.0` while build_deb.sh derives `${VERSION}`; the guard test rejects a stale literal after a bump |
| DEF-027 | `scripts/build_hardware_kit.sh` | capture `GLIBC=$(ldd --version ...)`, use it in `BUILD-INFO` and substitute `__GLIBC__` in `START-HERE.md` | `test_the_kit_start_page_reports_the_real_build_glibc` |
| DEF-028 | `msi_psu_monitor/daemon.py` | empty `--config`/`--state-dir`/`--prom-path` → argparse usage error (exit 2) | 3-parameter `test_empty_path_arguments_are_usage_errors` |
| DEF-029 | `msi_psu_monitor/state.py` | `iter_alert_log()` streams into `deque(maxlen=limit)` instead of loading all lines first | `test_iter_alert_log_limit_keeps_the_newest_lines_in_order`; existing order/rotation tests stay green |
| DEF-030 | `msi_psu_monitor/daemon.py` | corrected `--iterations` help and `run()` docstring to describe loop passes, not "positive samples" | manual `--help` output recorded in TEST_REPORT |
| DEF-031 | `msi_psu_monitor/dashboard.py` | state-directory gate only for the four real API routes; unknown API path stays 404 | `test_an_unknown_api_route_is_404_even_without_a_state_dir` |

## Verification after the batch

```text
pytest -q                        659 passed
ruff check . / format --check    clean
mypy msi_psu_monitor/            Success: no issues found in 10 source files
coverage (branch)                92% (2586 stmts, 188 missed; 874 branches)
bash scripts/smoke.sh            58 passed, 0 failed
shellcheck -S warning            clean
systemd-analyze verify           clean
udevadm verify                   Success: 1 / Fail: 0
```

## Docs updated with the fixes

- `tests/test_docs_consistency.py`: new guard against literal release-artifact versions in shell scripts.
- `AGENTS.md` / `msi_psu_monitor/AGENTS.md`: recorded the output-path rule, live-view contract,
  guarded housekeeping, and the single version source.
- `docs/testing/bug-report.md§10`, `docs/testing/fix-log.md§Phase 5`, `docs/testing/test-cases.md`,
  `docs/testing/test-report.md§11`: Phase 5 evidence.
- `bug-audit/`: this ledger, test report, code audit, release readiness.
## psu-file 对比轮（DEF-032..035）

| Bug | Files changed | Change | Regression evidence |
|---|---|---|---|
| DEF-032 | `msi_psu_monitor/monitor.py`, `protocol.py`, README/docs/AGENTS, `scripts/smoke.sh` | C2h reported as a toggle, never as "silenced"; help/audit/README/verify updated | `test_buzzer_off_writes_and_reports_the_switch`; smoke needle updated and re-run |
| DEF-033 | `msi_psu_monitor/monitor.py` | `apply_rail_mode()` reads before writing and skips a same-value 0xC0+F1h write | `test_set_rail_is_a_noop_when_already_in_the_requested_mode` |
| DEF-034 | `msi_psu_monitor/dashboard.py`, `tests/test_dashboard.py` | seven charts now match MSI Center; efficiency has its own percent-axis card | `test_the_seven_charts_match_the_msi_dashboard` |
| DEF-035 | `msi_psu_monitor/protocol.py`, `docs/protocol.md` | MEG serial read fixed at 24 bytes; TS keeps the length prefix | `test_a_meg_serial_is_cut_to_the_msi_fixed_length` |

Verification: 661 passed / ruff / format / mypy / coverage 92% / smoke 58.

## Threshold/alert completion (FEAT-01, 2026-10-19)

User decision: desktop notifications are not needed; local thresholds + alerting
must exist. The old draft `thresholds.yaml` was replaced by the stdlib-only INI
`[alerts]` section (no YAML dependency): `power_w`, `temp_c`, `pin_max_a`,
`pin_imbalance_a`, `connector_a`, `rail_12v_a`, `rail_5v_a`, `rail_3v3_a`;
0 disables one. Defaults are the REQ-14 initial values.

- `alerts.py`: `THRESHOLD_ALERT_NAMES`, `evaluate_threshold_alerts()`,
  `configured_threshold_names()`, configurable `evaluate_pin_alerts()`.
- `config.py`: keys/defaults/validation + `threshold_limits()`.
- `monitor.py`: `attach_alerts()` single entry point; text `Thresholds:` line;
  JSON `threshold_alerts`/`threshold_limits`; Prometheus
  `msi_psu_threshold_alert`/`msi_psu_threshold_limit`; exit 2 covers thresholds.
- `daemon.py`: samples through `attach_alerts()`, so threshold edges/recoveries
  land in `alerts-*.log` and the textfile.
- Design: names are distinct from E1h; missing readings are omitted so a latched
  threshold alert is not cleared by a failed payload read; `--no-alerts` disables both.

Regression: 680 passed, ruff/format/mypy clean, coverage 92%, smoke 58/58.

## Ops/CLI polish (FEAT-02, 2026-10-19)

- `monitor.format_prometheus()`: canonical exposition for empty label sets
  (`metric{} value`, no space) and the energy counter exported under both
  `msi_psu_total_energy_kwh` and REQ-8's `msi_psu_energy_kwh_total`.
- `docs/prometheus-rules.yml`: ready-to-use rules (down/stale/scrape-error,
  hardware alert, local threshold alert), shipped by the source deb, binary tar and
  hardware kit; `tests/test_packaging.py` asserts the wiring.
- `--dump-config`: effective config as INI text or JSON, including all `[alerts]`
  limits, with no PSU/history/page side effects; conflicting flags are usage errors.
- `--help` notes: 5 s average for per-pin/12V current, efficiency source (0xE0
  offset 32), Conn1/Conn2 pin order.
- Threshold ALERT descriptions now include measured vs limit.
- Regression: 689 passed, ruff/format/mypy clean, coverage 92%, smoke 58/58.

## Hardware OCP threshold write (FEAT-03, 2026-10-19)

- `protocol.set_ocp_thresholds()`: 8-byte C0h payload (amps as LINEAR11 exp -4:
  `value<<4, 0xE0`; times as whole seconds) followed by F1h; refuses out-of-range
  values and unknown models without writing.
- `monitor`: `--dump-thresholds`/{B}--ocp-set`/{B}--load-thresholds`;
  range validation at argparse/load time, upsert + read-back x3, no-op when unchanged,
  audit line, unsupported model EXIT_ERROR; `--ocp` remains read-only.
- `protocol._handshake()`: 3 attempts with 0.5/1.0 s backoff (REQ-18).
- `tests/test_prometheus_exposition.py`: strict stdlib promtool substitute.
- Regression: 735 passed. Hardware write verification remains BLOCKED (no PSU).

## Reliability/release close-out (QUAL-01..03, 2026-10-19)

- `scripts/soak.sh`: reproducible 5k-sample CI gate, 50k local run exit 0
  (peak RSS 16.4 MB, fd=3, state dir 28 KB); `tests/test_soak.py` covers bad
  arguments and a short run.
- `tests/test_robustness.py`: deterministic fuzz over 400 random 0xE0 payloads
  x 5 models, 120 random config files and 120 random `--ocp-set` specs.
- `tests/test_monitor_format.py`: multi-rail 12V1-5 voltages/currents and the
  CPU/GPU split, including Prometheus rail labels.
- OCP write diagnostics now distinguish unsupported model / failed read / read-back
  mismatch, and `--load-thresholds` rejects unknown JSON keys.
- `CHANGELOG.md` added and shipped by source deb, binary deb, tarball and kit;
  dual Python 3.12.3 / 3.13.15 runs both pass 735 tests.
