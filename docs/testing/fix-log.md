# 修复台账（Fix Log）

- 项目：msi-psu-monitor
- 更新时间：2026-10-19
- 当前测试：636 passed；源语句覆盖率 92%；smoke 58
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
