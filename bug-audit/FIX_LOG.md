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

## 全项目审计第二轮（2026-10-22）

基线为上一轮收口的 736 项；本轮继续逐模块审查、补测试与修复，最终 **803 passed**，分支覆盖率
**94%**（3166 stmts / 183 missed；1174 branches / 78 partial），`ruff check`、`ruff format --check`、`mypy`、`smoke 58/58`、
`soak 5000` 全绿。所有验证均为无硬件模拟；真机验收仍为 **BLOCKED**。

| ID | 位置 | 缺陷 / 修复 | 回归测试 |
|---|---|---|---|
| AUD-01 | `state.write_live_snapshot` / `read_live_snapshot` | NaN/Infinity 写入 `latest.json` 后浏览器 `JSON.parse` 拒绝整帧；写入/读取均过滤非有限值，时间戳非有限拒绝 | `test_live_snapshot_never_writes_non_finite_json`、`test_live_reader_rejects_a_non_finite_reading` |
| AUD-02 | `state.MonitorState.load/read_live_snapshot` | 深层嵌套 JSON 抛 `RecursionError`（非 `ValueError`），可造成 daemon 启动崩溃循环；捕获为损坏状态 | `test_deeply_nested_json_is_damaged_state_not_a_recursion_crash` |
| AUD-03 | `state.from_dict/_daily_buckets` | 负 count/能量/日均值会显示负均值/负 kWh；载入时告警并归零/丢弃 | `test_negative_state_counters_do_not_produce_negative_totals`、`test_negative_daily_energy_buckets_are_dropped` |
| AUD-04 | `state` 文件读取 | `latest.json`/history/alert log 为 FIFO 时会永久阻塞 daemon 或 dashboard 线程；统一拒绝非普通文件 | `test_live_snapshot_reader_does_not_block_on_a_fifo`、`test_history_and_alert_appenders_refuse_a_fifo` |
| AUD-05 | `state.atomic_write_text` / `monitor.run_export` | `os.replace` 用临时文件默认权限覆盖已有文件，0600 导出件变 0644；保留原 mode；导出补目录 fsync | `test_atomic_writes_keep_the_existing_file_mode`、`test_export_keeps_the_existing_output_mode` |
| AUD-06 | `alerts` | 阈值/读数/pin 为 NaN/inf 时被当成“未超限”而清除闩锁告警；非有限视为缺失，>12 pin 不产生幻影 pin13/14 | `test_threshold_alerts_treat_non_finite_readings_as_missing`、`test_pin_alerts_ignore_phantom_pins_and_non_finite_values` |
| AUD-07 | `protocol.HIDDevice` | `open()` 重复调用泄漏 fd；空/超 64B/非法字节命令抛异常；drain 无上限可挂死；非 UTF-8 uevent 中断扫描；2 字节非 NAK 回包误判为 ACK | `test_hid_open_is_idempotent_and_does_not_leak_a_fd`、`test_send_command_rejects_empty_and_oversize`、`test_send_command_drain_is_bounded`、`test_detect_devices_skips_non_utf8_uevent`、`test_write_command_requires_non_empty_reply` |
| AUD-08 | `daemon` | `select_device()` 异常在 try 外可杀死常驻进程；`get_sensors()` 返回非 dict 触发 TypeError；失败分支只捕 OSError | `test_daemon_discovery_exception_is_a_throttled_miss`、`test_daemon_survives_a_sensor_reader_that_returns_none` |
| AUD-09 | `dashboard` | `Host: [::1]:80:90` 等畸形 authority 被接受；历史读取 OSError 丢弃连接而非 503 | `test_host_header_parser_rejects_every_non_loopback_shape`、`test_a_history_read_error_is_a_503_not_a_dropped_connection` |
| AUD-10 | `monitor` 输出/状态 | `--dump-config` 的 `[fan]` 段永远为空（键名不匹配）；`--dump-config -O /dev/full` 抛未捕获 OutputError traceback；watch/once 状态目录不可写会终止/隐藏读数 | `test_dump_config_writes_the_fan_section`、`test_dump_config_output_error_is_a_clean_exit_not_a_traceback`、`test_watch_survives_an_unwritable_state_directory`、`test_once_still_prints_the_frame_when_state_cannot_be_saved` |
| AUD-11 | `monitor` 显示/校验 | 自定义风扇 duty 未进文本帧；`read_fan_state()` 返回 None 时 `read_fan_fields` 抛 AttributeError；OCP JSON 的 inf/nan 触发 OverflowError；`--from` 400 位溢出为 inf 后静默导出全部 | `test_text_frame_shows_the_customize_duty`、`test_read_fan_fields_tolerates_a_non_dict_result`、`test_ocp_threshold_file_rejects_non_finite_numbers`、`test_parse_from_rejects_a_window_that_overflows_to_infinity` |
| AUD-12 | `demo` | `read_blackbox(-1)` 返回 1 条（真实实现 0 条）；非 TS 机型错误报告 Zero Fan 状态（真实 42h 不解释该字段） | `test_demo_blackbox_negative_limit_matches_the_real_reader`、`test_demo_non_ts_models_do_not_report_zero_fan` |
| AUD-13 | 发布/文档 | release 未上传 README 引用的 `.sha256` 旁车；SBOM 在 hardware kit 之前生成导致缺 kit 哈希；`docs/verify` 硬编码 1.0.0 产物名；kit 文件名文档与实现不符；Prometheus down 规则引用 `msi_psu_up` 没有的 `reason` 标签 | `test_release_publishes_the_checksum_sidecars_the_docs_reference`、`test_the_sbom_is_generated_after_every_artifact_it_hashes`、`test_verify_doc_uses_a_version_agnostic_artifact_name`、`test_the_down_rule_does_not_reference_a_label_the_metric_lacks` |
| AUD-14 | 安装/长稳 | source install 在无 udev/systemd 的主机上中途退出；hardware uninstall 在非 systemd 主机不删 unit；soak 零次轮询仍 PASS；`--quiet` 配置加载 warning 泄漏；`--dump-config` 未反映 fan 配置 | `test_install_sh_tolerates_missing_udev_and_systemd`、`test_hardware_uninstall_removes_the_unit_without_systemd`、`test_soak_fails_when_it_could_not_measure_anything`、`test_quiet_suppresses_config_load_warnings` |

### 未解决 / 外部条件

- **真机写 ACK**：文档同时描述“回显写入数据”和“首字节 0xFC”；为避免误拒真实写操作，保留
  “非空非 NAK”判定，只拒绝 2 字节空回包。0xFC 语义需 bench 复核（`--writes` 验收）。
- **真实硬件**：5 机型读数、OCP 阈值写/断电保持、风扇/Zero Fan/蜂鸣器/多轨、黑盒顺序均
  **NOT RUN**；无 PSU，所有结论仅来自 demo/mock。
- **环境**：本机只有 x86_64 Python 3.12/3.13；3.10/arm64 由 CI 矩阵与静态 3.10 语法检查覆盖。
- **覆盖率余量**：94% 中未覆盖的主要是 `pragma: no cover` 防御分支、`__main__.py` 入口、
  以及 daemon/dashboard 的传输层错误分支；未发现新的可复现逻辑缺陷。

### 契约收口（2026-10-22 追加）

上一版报告把三处“歧义行为”列为未改；本轮按维护者授权收紧：

| 行为 | 决定 | 回归测试 |
|---|---|---|
| `--once` + `--export/--show-log/--show-alert-log/--ocp/--dump-thresholds` | 拒绝（exit 2），不再静默忽略 `--once`；写控制仍允许 `--once`（写动作本身即一次执行） | `test_once_is_rejected_with_a_mode_that_would_ignore_it` |
| 配置 `[monitor] output/serial` 在 `--dashboard`（output+serial）、`--export`/`--show-alert-log`（serial）下被忽略 | 保留运行，但对来自配置文件的默认值打印明确 warning；显式 CLI 组合仍按原规则 exit 2 | `test_config_serial_is_not_silently_ignored_by_export` 等 3 项 |
| 0xC0 `enabled` 字节为 2/0xFF 等未定义值 | 不再报 `enabled: false`（会被误读为保护关闭）；整个 C0h 读取视为不可用，`--ocp`/`--dump-thresholds` exit 1，daemon 清空 OCP 块并告警 | `test_read_ocp_thresholds_rejects_an_undefined_enable_byte` |

`docs/protocol.md` 的 0xC0 行同步写明“enable 仅定义 0/1；其他值视为读取失败，不猜成 disabled”。
