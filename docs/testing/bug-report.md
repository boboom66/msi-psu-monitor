# msi-psu-monitor 缺陷与风险登记（第一阶段）

- 基线：`650076a`；执行时间：2026-10-19。
- 本文件区分“确认缺陷”和“测试缺口/发布风险”；未执行的测试不写成通过。

## 1. 确认缺陷

| ID | 严重度 | 状态 | 描述 | 证据 | 影响 | 处理 |
|---|---|---|---|---|---|---|
| DEF-002 | P3 | 待评审 | `pyproject.toml` 仍标 `Development Status :: 4 - Beta`，作者邮箱为 `contributors@example.com`，Homepage 指向上游而非 fork | `pyproject.toml` | 官网/包元数据与“生产级”定位不一致 | 发布前确认版本/元数据策略 |
| DEF-003 | P2 | 已修复 | Dashboard 未校验 Host，DNS rebinding 可读取本地数据 | 原始 socket `Host: evil.example` 曾返回 200；`test_a_non_loopback_host_header_is_rejected` 现断言 421 | 本地遥测/序列号可能被恶意网页读取 | 已加 loopback Host 校验 + CSP/Permissions-Policy，回归通过 |
| DEF-004 | P3 | 已修复 | `--iterations 0/-1` 会静默跑 1 个样本，与“Stop after N samples”不符 | `test_daemon_rejects_zero_or_negative_iterations` | 边界行为误导 | `_positive_iterations` 拒绝非正数，argparse exit 2 |

**DEF-001 已审查排除**：`MONITOR="$PY -m msi_psu_monitor"` 是命令字符串，给 `$MONITOR` 加引号会变成单个可执行文件名并 exit 127；SC2086 是 info，CI 的 `-S warning` 门禁通过。保留这种写法，smoke 58 项已验证。

基线未发现可复现的 P0/P1 软件功能缺陷；Phase 3 又确认并修复了 7 类 P2/P3 软件缺陷（见 §5）。这不等于不存在缺陷，硬件与浏览器/安装路径仍未测。

## 2. 发布/测试风险

| ID | 级别 | 类型 | 风险 | 现状 | 建议 |
|---|---|---|---|---|---|
| RISK-001 | P1（阻塞发布） | 硬件 | 真实 PSU 通信、5 机型差异、告警/写控制/黑盒未验证 | 无 `/dev/hidraw*`，全部 BLOCKED | 真机按 verify §8 的 18 项执行 |
| RISK-002 | P1（阻塞发布） | 构建环境 | 本机 glibc 2.39 构建的二进制不能代表 22.04/2.35 官方产物 | 本地需 `ALLOW_NEWER_GLIBC=1` | 在 CI `ubuntu-22.04` 构建并执行 clean-env 测试 |
| RISK-003 | P2 | 发布门禁 | release workflow 已补 ruff/format/mypy/smoke，但仍未跑 shellcheck；arm64 仍仅 release 时构建，且可绕过 CI 状态发布 | `.github/workflows/release.yml` | 继续把 CI 作为 release 的 needs 或加同样门禁 |
| RISK-004 | P2 | 安装 | 用户命名空间内 install/uninstall/`--purge` 已实际通过（fake systemctl/udevadm）；真实 systemd/udev 启停未跑 | `tests/test_install_namespace.py` | 在真实 root 容器/机器复验 |
| RISK-005 | P2 | 前端 | Dashboard JS 只用 HTTP/源码断言，无真实浏览器测试 | 无浏览器自动化 | 用 Playwright/Chromium 跑页面加载、图表、PNG/CSV、1s live |
| RISK-006 | P2 | 安全 | Dashboard Host/CSP 已修复；仍建议真实浏览器验证 CSP 不影响 PNG/CSV 下载 | 421 + CSP 测试已加 | 浏览器端复测 |
| RISK-007 | P2 | 数据 | `state.json`/日志/串口标签可能被本机其他用户读取，序列号属于可识别信息 | unit 无 UMask，文件默认 0644 | 做权限/数据分类评审，决定 0640+组或脱敏 |
| RISK-008 | P2 | 兼容 | arm64、Ubuntu 22.04、真实 systemd 沙箱未验证 | 仅 x86_64/24.04 | 增加构建/运行矩阵或明确发布限制 |
| RISK-009 | P2 | 质量 | 覆盖率已进 dev 依赖与 CI（语句 92%，fail-under 90）；HID 负向帧/FD 泄漏已补；24h/72h 长稳仍未跑 | `coverage` + CI Coverage step；`test_psu_sensors` 负向参数化 | 补长稳与内存测试 |
| RISK-010 | P2 | 文档 | 安装/发布/支持文档复制粘贴风险；已有文档一致性测试，但未覆盖 docs/testing 与安装命令 | 文档测试有限 | 发布前人工审查 + 链接检查 |
| RISK-011 | P3 | 测试脚本 | `shellcheck` 默认级别仍有 SC2015 info；SC2086 是命令字符串的预期写法（DEF-001 排除） | `smoke.sh` | 保留 `-S warning` CI 门禁，必要时改 reporter 写法 |
| RISK-012 | P3 | 硬件语义 | VIN 量程、多轨切换持久性、buzzer 是否 toggle、黑盒 pin/set byte 语义未确认 | 仅按 MSI 源码/REV6 推断 | 真机专项验证，不通过就保留限制说明 |

## 3. 未执行项（不得算 PASS）

- 真实 hidraw 打开、权限、EACCES、flock 多进程、拔插重连。
- root 下 systemd 启动、`systemd-analyze security`、udev uaccess。
- 22.04/arm64 二进制构建与运行。
- 真实浏览器 Dashboard。
- 24h/72h 长稳、fd/内存泄漏、反复启停。
- 真实 release tag 发布、下载/校验/升级/回滚。
- 真实硬件写入（fan/Zero Fan/buzzer/multirail）。

## 4. 复现与回归要求

每个确认缺陷修复时必须补充回归测试；每个风险转为结论时必须附命令与输出。
Phase 2 会把上表映射为 TEST-xxx，并在 `test-cases.md` 中记录前置条件、输入、预期和实际结果。

## 5. Phase 3 新增确认缺陷（2026-10-19）

| ID | 严重度 | 状态 | 描述 | 证据 | 影响 | 处理 |
|---|---|---|---|---|---|---|
| DEF-005 | P2 | 已修复 | 输出路径错误被误报为“Run as root”；`--show-alert-log -O` traceback；stdout 写满（ENOSPC）exit 120 且有异常输出 | 复现：`--show-alert-log -O /no/such/x`、`--once -O /no/such/x`、`--once >/dev/full`；修复后 exit 1 + “cannot write” / 无 traceback | 误导 root 诊断、脚本收到错误退出码、日志被污染 | `emit()` 增加 `OutputError`；main 捕获 OutputError/OSError 并清理 stdout；3 个回归测试通过 |
| DEF-006 | P2 | 已修复 | `[monitor] interval = 0/-1` 未校验；裸 `--watch` 会忙循环或 `time.sleep(-1)` 抛异常 | `test_a_non_positive_monitor_interval_falls_back` | 无提示的忙循环/崩溃 | `load_config` 回落默认 2.0 |
| DEF-007 | P3 | 已修复 | `[fan] mode=performance` 仍保留 duty，与 performance=PSU 曲线语义不符 | `test_performance_mode_drops_a_configured_duty` | 配置语义混乱，日志显示无意义 duty | performance 与 auto 一样清空 duty |
| DEF-008 | P3 | 已修复 | `--columns all,wattage` 先遇到 all 就返回全部，拼写错误被静默吞掉 | `test_parse_columns_order_dedup_and_all` 新增 `all,wattage` ValueError 断言 | 用户以为选了指定列，实际导出全部 | 先校验全部 token，再决定 all |
| DEF-009 | P3 | 已修复 | `iter_alert_log(limit=0)` 因 Python `[-0:]` 返回全部而不是空 | `test_iter_alert_log_zero_limit_returns_nothing` | 边界 API 语义错误 | limit<=0 返回 [] |
| DEF-010 | P2 | 已修复 | daemon `open()` 成功、`init()` 失败时未关闭已打开的 hidraw fd | `test_a_failed_init_closes_the_already_open_device` | 持续发现失败时每轮泄漏一个 fd | `_ensure_psu` 失败路径关闭 psu |
| DEF-011 | P3 | 已修复 | Dashboard `/api/export` 用 `",".join` 拼 CSV，值含逗号/引号时错列 | `test_export_endpoint_quotes_a_comma_in_a_value` | 手工编辑的历史文件可让导出列错位 | 改用 `csv.writer`（与 CLI 一致） |

回归命令：`uv run --group dev pytest -q` → 629 passed；覆盖率 92%；`ruff check`/`mypy`/`smoke` 见 test-report。
