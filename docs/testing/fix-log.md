# 修复台账（Fix Log）

- 项目：msi-psu-monitor
- 更新时间：2026-10-19
- 当前测试：803 passed；分支覆盖率 94%；smoke 58/58
- 约定：只有真实执行并通过的回归测试才记为“已验证”。

## 已修复缺陷

| ID | 级别 | 根因 | 修改文件 | 回归测试 | 状态 |
|---|---|---|---|---|---|
| DEF-003 | P2 | Dashboard 未校验 Host，DNS rebinding 可读本地遥测 | `msi_psu_monitor/dashboard.py` | `test_dashboard.py` Host 421/CSP 用例 | 已修复/已验证 |
| DEF-004 | P3 | `--iterations 0/-1` 被 argparse 接受后静默跑 1 次 | `msi_psu_monitor/daemon.py` | `test_daemon_rejects_zero_or_negative_iterations` | 已修复/已验证 |
| DEF-005 | P2 | `emit` 让 OSError 逃逸；main 只处理 BrokenPipe，stdout ENOSPC 退出 120 | `msi_psu_monitor/monitor.py` | 输出路径/`/dev/full` 三入口回归 | 已修复/已验证 |
| DEF-006 | P2 | `[monitor] interval` 非正未校验；裸 `--watch` 忙循环/`sleep` 抛错 | `msi_psu_monitor/config.py` | `test_a_non_positive_monitor_interval_falls_back` | 已修复/已验证 |
| DEF-007 | P3 | `[fan] mode=performance` 仍保留 duty | `msi_psu_monitor/config.py` | `test_performance_mode_drops_a_configured_duty` | 已修复/已验证 |
| DEF-008 | P3 | `--columns all,wattage` 先遇到 all 就静默全选 | `msi_psu_monitor/state.py` | `test_parse_columns_order_dedup_and_all` | 已修复/已验证 |
| DEF-009 | P3 | `iter_alert_log(limit=0)` 的 `[-0:]` 返回全部 | `msi_psu_monitor/state.py` | `test_iter_alert_log_zero_limit_returns_nothing` | 已修复/已验证 |
| DEF-010 | P2 | daemon `open()` 后 `init()` 失败未关闭 fd | `msi_psu_monitor/daemon.py` | `test_a_failed_init_closes_the_already_open_device` | 已修复/已验证 |
| DEF-011 | P3 | Dashboard `/api/export` 用字符串拼接，逗号/引号值错列 | `msi_psu_monitor/dashboard.py` | `test_export_endpoint_quotes_a_comma_in_a_value` | 已修复/已验证 |
| DEF-012 | P3 | Dashboard 网格 `minmax(340px,1fr)` 在 320px 横向溢出 | `msi_psu_monitor/dashboard.py` | CSS 静态断言 + Playwright 320/768/1920 | 已修复/已验证 |
| DEF-013 | P2 | Release workflow 把 smoke 生成的 source `.deb`（依赖 python3）上传 | `.github/workflows/release.yml` | TEST-062/资产检查 | 已修复/CI 验证 |
| DEF-014 | P2 | Release `SHA256SUMS` 未覆盖 hardware kit | `.github/workflows/release.yml` | release_security 测试 + 资产 digest 对比 | 已修复/CI 验证 |
| DEF-015 | P2 | `--export -O` 直接写目标，失败会破坏旧导出 | `msi_psu_monitor/monitor.py` | `test_export_preserves_an_existing_file_when_the_write_fails` | 已修复/已验证 |
| DEF-016 | P2 | `-f/--serial` 在 export/控制写等固定输出模式中被静默忽略 | `msi_psu_monitor/monitor.py` | `test_flags_that_would_be_silently_ignored_are_rejected`、配置 format 警告 | 已修复/已验证 |

## 已审查排除

- DEF-001：`MONITOR="$PY -m msi_psu_monitor"` 是命令字符串；给变量加引号才会变成单个可执行文件名（exit 127）。SC2086 为 info，`shellcheck -S warning` 通过。
- DEF-002：Beta 分类/占位邮箱属于发布元数据策略，不是运行缺陷；发布前需产品确认。

## 修复规则

1. 先复现并记录旧行为；2. 修改源码而非测试断言；3. 加回归测试；4. 跑单模块 + 全量；5. 更新本台账和 test-report。

## 第二轮追加（2026-10-19）

| ID | 修改文件 | 回归测试 |
|---|---|---|
| DEF-017 | `msi_psu_monitor/daemon.py` | daemon unexpected parser/enrichment/open/history/prom tests |
| DEF-018 | `msi_psu_monitor/monitor.py` | `test_a_zero_watt_sample_still_counts_in_the_average` |
| DEF-019 | `msi_psu_monitor/state.py` | `test_state_dir_falls_back_when_the_default_path_is_a_regular_file` |
| DEF-020 | `msi_psu_monitor/monitor.py` | `--serial ''` parser test |

| DEF-021 | `msi_psu_monitor/monitor.py` | `test_serial_discovery_skips_an_unexpected_parser_error` |
## 第五轮追加（2026-10-19，全项目深度审计）

| ID | 修改文件 | 回归测试 |
|---|---|---|
| DEF-022 | `msi_psu_monitor/monitor.py` | `test_output_through_a_symlink_keeps_the_symlink`、`test_export_through_a_symlink_keeps_the_symlink`、`test_output_to_dev_stdout_follows_the_symlink` |
| DEF-023 | `msi_psu_monitor/dashboard.py` | `test_the_live_snapshot_can_feed_every_charted_series`、`test_the_live_overlay_actually_moves_every_chart_series` |
| DEF-024 | `msi_psu_monitor/daemon.py` | `test_a_failing_prune_does_not_kill_the_daemon` |
| DEF-025 | `msi_psu_monitor/monitor.py` | `test_a_failed_payload_read_does_not_clear_a_mirror_alert` |
| DEF-026 | `scripts/smoke.sh`、`tests/test_e2e_cli.py`、`tests/test_docs_consistency.py` | `test_shell_scripts_do_not_hardcode_the_release_artifact_version`、e2e 版本测试 |
| DEF-027 | `scripts/build_hardware_kit.sh` | `test_the_kit_start_page_reports_the_real_build_glibc` |
| DEF-028 | `msi_psu_monitor/daemon.py` | `test_empty_path_arguments_are_usage_errors` |
| DEF-029 | `msi_psu_monitor/state.py` | `test_iter_alert_log_limit_keeps_the_newest_lines_in_order` |
| DEF-030 | `msi_psu_monitor/daemon.py` | `--help` 实测文本（文档型修复） |
| DEF-031 | `msi_psu_monitor/dashboard.py` | `test_an_unknown_api_route_is_404_even_without_a_state_dir` |

全部 659 tests / ruff / format / mypy / smoke 58 / coverage 92% / shellcheck / systemd-analyze /
udevadm verify 均通过；详细命令与未执行项见 [bug-audit/TEST_REPORT.md](../../bug-audit/TEST_REPORT.md)。

## 第六轮追加（2026-10-19，psu-file 对比）

| ID | 修改文件 | 回归测试 |
|---|---|---|
| DEF-032 | `msi_psu_monitor/monitor.py`、`protocol.py`、README/docs/AGENTS、`scripts/smoke.sh` | `test_buzzer_off_writes_and_reports_the_switch`、审计行断言、smoke |
| DEF-033 | `msi_psu_monitor/monitor.py` | `test_set_rail_is_a_noop_when_already_in_the_requested_mode` |
| DEF-034 | `msi_psu_monitor/dashboard.py` | `test_the_seven_charts_match_the_msi_dashboard`、Node live harness |
| DEF-035 | `msi_psu_monitor/protocol.py`、`docs/protocol.md` | `test_a_meg_serial_is_cut_to_the_msi_fixed_length` |

对照矩阵与未完成项分类：[psu-file-gap-analysis.md](psu-file-gap-analysis.md)。

## 第七轮追加（2026-10-19，本地阈值/告警 FEAT-01）

| ID | 修改文件 | 回归测试 |
|---|---|---|
| FEAT-01 | `msi_psu_monitor/alerts.py`（阈值评估/名字/描述）、`config.py`（8 个键 + `threshold_limits`）、`monitor.py`（`attach_alerts`、文本/JSON/Prometheus、exit 2）、`daemon.py`、example/README/verify | `test_alerts.py`、`test_config.py`、`test_cli_features.py`、`test_daemon.py` 新增用例 |

说明：桌面通知按用户确认不做；OCP 8 字节阈值写/ dump-load 仍按冻结批次保留。

## 第八轮追加（2026-10-19，运维/CLI 打磨 FEAT-02）

| ID | 修改文件 | 回归测试 |
|---|---|---|
| FEAT-02 | `msi_psu_monitor/monitor.py`（规范 exposition、电量双名、`--dump-config`、`--help` 注释、阈值告警带 measured/limit）、`docs/prometheus-rules.yml`、`scripts/build_{deb,binary,hardware_kit}*`、README/verify | `test_cli_features.py`（dump-config/别名/描述）、`test_packaging.py`（规则随包）、`test_monitor_format.py` |

## 第九轮追加（2026-10-19，硬件 OCP 阈值写 + 握手退避 + promtool 替代）

| ID | 修改文件 | 回归测试 |
|---|---|---|
| FEAT-03 | `msi_psu_monitor/protocol.py`（`set_ocp_thresholds()`、`_handshake()` 3 次退避）、`monitor.py`（`--dump-thresholds`/`--ocp-set`/`--load-thresholds`、范围校验、读回 3 次、同值不写）、`demo.py`（阈值状态）、README/AGENTS/protocol/verify | `test_ocp.py`（写字节/拒绝/保存失败/demo）、`test_cli_features.py`（14 例 dump/set/load/幂等/读回失败/机型门/冲突/越界）、`test_psu_sensors.py`（握手重试/退避）、`test_prometheus_exposition.py`（严格 exposition 解析） |

## 第十轮追加（2026-10-19，可靠性/发布收口）

| ID | 修改文件 | 回归测试 |
|---|---|---|
| QUAL-01 | `scripts/soak.sh` + CI 步骤（5k 采样）、`tests/test_soak.py`；`.github/workflows/ci.yml` | soak 坏参数/短线长跑/CI 接线；50k 本地 soak（RSS 16.4 MB、fd=3） |
| QUAL-02 | `tests/test_robustness.py`（随机 0xE0/配置/--ocp-set fuzz）、`tests/test_monitor_format.py`（多轨 formatter） | 随机 400 payload ×5 机型、120 配置、120 set spec；多轨 12V1-5/CPU/GPU |
| QUAL-03 | OCP 写诊断：不支援机型的 dump、读失败、未知 JSON 键、可选 on/off；`protocol/demo` | `test_ocp.py`/`test_cli_features.py` 新增边界 |
| DOC-01 | `CHANGELOG.md`（随源码/二进制 deb、tar、kit 发布）、RELEASE_READINESS/support/incident/SECURITY/protocol/README/verify 同步 | `test_packaging.py` 锁定 CHANGELOG/soak/CI 接线 |

## 全项目审计第二轮（2026-10-22）

基线 736 → 803 passed，分支覆盖率 94%，smoke 58/58，soak 5000 PASS；详细缺陷表与回归测试名见
[`bug-audit/FIX_LOG.md§全项目审计第二轮`](../../bug-audit/FIX_LOG.md)。本轮覆盖 live JSON 非有限值、
深层 JSON RecursionError、FIFO 阻塞、原子写权限、告警 NaN、HID fd/帧边界、daemon 非 dict 返回、
dashboard Host/503、`--dump-config` fan 段与输出错误、demo 非 TS Zero Fan、release sidecar/SBOM
顺序、soak 零轮询假通过、`--quiet` 配置 warning 泄漏等。真机写 ACK 语义与全部硬件验收仍为 BLOCKED。

### 契约收口（2026-10-22 追加）

- `--once` 与 `--export/--show-log/--show-alert-log/--ocp/--dump-thresholds` 组合改为 usage error，
  不再静默忽略。
- 配置文件来源的 `output`/`serial` 在 dashboard/export/show-alert-log 等不使用它的模式下打印
  warning；显式 CLI 组合仍按原规则拒绝。
- 0xC0 `enabled` 仅接受 0/1；未定义字节视为读取失败，避免把未知保护状态报成 disabled。
