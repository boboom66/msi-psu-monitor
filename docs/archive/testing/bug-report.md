# msi-psu-monitor 缺陷与风险登记（第一阶段）

> **历史缺陷台账（2026-10-19）**。其中 NR-002/NR-003 已在 2026-10-22 修复；当前门禁为 **803 tests / 94% 分支覆盖率 / smoke 58 / soak 5000**，当前状态见 `bug-audit/FIX_LOG.md` 与 `bug-audit/BUG_TRACKER.md`。

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
| RISK-002 | P1（CI 阻塞） | 构建环境 | 已用 Ubuntu 22.04 chroot 本地构建并在 22.04 内运行通过；CI `ubuntu-22.04` 仍未实际执行 | `docs/testing/evidence-2204-build.txt` | 在 CI 复跑并保留 provenance |
| RISK-003 | P2 | 发布门禁 | release workflow 已补 ruff/format/mypy/smoke，但仍未跑 shellcheck；arm64 仍仅 release 时构建，且可绕过 CI 状态发布 | `.github/workflows/release.yml` | 继续把 CI 作为 release 的 needs 或加同样门禁 |
| RISK-004 | P2 | 安装 | 用户命名空间内 install/uninstall/`--purge` 已实际通过（fake systemctl/udevadm）；真实 systemd/udev 启停未跑 | `tests/test_install_namespace.py` | 在真实 root 容器/机器复验 |
| RISK-005 | P2 | 前端 | Dashboard 已用本机 headless Chromium 跑页面/图表/CSV/PNG；该验证依赖本地 Playwright，未进 CI，也未覆盖真实桌面浏览器 | `docs/testing/evidence-dashboard-headless.png`、test-report §10.5 | 把 Playwright 浏览器 smoke 纳入可选 CI 或发布前手工执行 |
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

回归命令：`uv run --group dev pytest -q` → 645 passed；覆盖率 92%；`ruff check`/`mypy`/`smoke` 见 test-report。

## 6. Phase 3 补充：响应式与长稳验证

| ID | 严重度 | 状态 | 描述 | 证据 | 影响 | 处理 |
|---|---|---|---|---|---|---|
| DEF-012 | P3 | 已修复 | Dashboard 图表网格 `minmax(340px,1fr)` 在 320px 视口下产生 360px 横向溢出 | Playwright 320px 实测 `scrollWidth=360 > clientWidth=320`；修复后均为 320 | 手机/窄窗口横向滚动，卡片被截 | 改为 `minmax(min(340px,100%),1fr)`；浏览器 320/768/1920 复测无溢出；新增静态 CSS 断言 |

- 长稳：demo daemon 20,000 样本（约 200s，`sample_interval=0.01`），RSS 稳定在 16.6MB、fd=3、prom 约 4.4KB、history 1,164 行；无 traceback，正常 `Stopped after 20000 samples`。
  证据：[evidence-soak-20k.tsv](evidence-soak-20k.tsv)。24h/72h 仍未跑。

## 7. CI release 阶段发现并修复

| ID | 严重度 | 状态 | 描述 | 证据 | 影响 | 处理 |
|---|---|---|---|---|---|---|
| DEF-013 | P2 | 已修复 | 首次 v1.0.0 release 把 smoke test 生成的 source `.deb`（Architecture: all, Depends: python3）一起发布 | 首次 release 资产含 `msi-psu-monitor_1.0.0_all.deb`；`dpkg-deb -f` 显示 `Depends: python3`；修复后资产无该文件 | 违背“官方下载不需要 Python”，且与自包含 deb 混淆 | release workflow 在 smoke 后删除 `_all.deb`，upload/publish 只匹配自包含 arch deb，并加回归断言 |
| DEF-014 | P2 | 已修复 | 首次修复后 `SHA256SUMS` 只覆盖 release tar/deb/SBOM，未覆盖 hardware kit | 修复前 `SHA256SUMS` 无 hardware-kit 行；修复后含两架构 kit | kit 资产无校验和 | checksum 命令加入 `msi-psu-monitor-*hardware-kit*.tar.gz`，并由 release_security 测试锁定 |

首个失败 run 还暴露了两个 CI-only 断言（`dist/*.tar.gz`、旧 `sha256sum` 行）；已在 tests 中更新并在后续 tag 重跑。

## 8. 2026-10-19 第二轮缺陷修复

| ID | 严重度 | 状态 | 描述 | 证据 | 影响 | 处理 |
|---|---|---|---|---|---|---|
| DEF-015 | P2 | 已修复 | `--export -O` 直接写目标文件；中途 OSError 会留下被截断的旧导出 | `test_export_preserves_an_existing_file_when_the_write_fails`（旧实现会把 `old export` 覆盖成 partial） | 数据导出损坏/不可恢复 | 普通文件改为 scratch + fsync + `os.replace`；FIFO/字符设备保留直接写 |
| DEF-016 | P2 | 已修复 | `-f/--format` 在 export/控制写中被接受但静默忽略；`--serial` 在 export 中被忽略；配置文件 format 在固定输出模式中也被静默忽略 | 新增参数化 `test_flags_that_would_be_silently_ignored_are_rejected`、`test_a_config_format_is_ignored_with_a_warning_in_fixed_format_modes` | 调用方以为得到 JSON/选了设备，实际不是 | 不兼容组合 argparse exit 2；配置 format 在固定格式模式给出 warning 并回落 text |

## 9. 2026-10-19 第三轮缺陷修复

| ID | 严重度 | 状态 | 描述 | 证据 | 影响 | 处理 |
|---|---|---|---|---|---|---|
| DEF-017 | P2 | 已修复 | daemon 的设备 read/open/enrichment/history/prometheus 出现非 OSError 异常时直接向上抛，systemd 会重启循环；异常解析数据可能杀死常驻进程 | 新增 `test_an_unexpected_parser_exception_is_a_counted_read_failure`、`test_an_unexpected_enrichment_error_is_a_counted_failure`、`test_an_unexpected_history_error_does_not_stop_the_daemon`、`test_an_unexpected_prometheus_error_does_not_stop_the_daemon`、`test_an_unexpected_open_error_is_retried_not_fatal` | 监控中断/反复重启 | 失败计为 read failure/记录日志；设备打开失败按 discovery throttle 重试 |
| DEF-018 | P3 | 已修复 | `_valid_sample` 用 `if not power or not efficiency`，0 W/0% 的合法样本被跳过，样本数和均值被偏置 | `test_a_zero_watt_sample_still_counts_in_the_average` | 空闲功率/计数不准确 | 只把 `None`/不可转换视为无效，零值正常统计 |
| DEF-019 | P3 | 已修复 | `default_state_dir` 在默认路径是普通文件但可写时仍返回该文件，后续 state/history 写失败 | `test_state_dir_falls_back_when_the_default_path_is_a_regular_file` | 异常部署下监控不可用 | 默认路径必须是目录才采用，否则回退 XDG |
| DEF-020 | P3 | 已修复 | `--serial ""`（未设置变量）被接受，变成搜索空 serial，而不是参数错误 | 新增 `['--serial', '']` 到 CLI 参数校验用例 | 脚本报错难诊断 | argparse exit 2，`--serial requires a value` |

| DEF-021 | P3 | 已修复 | `--serial` 发现过程中设备 `open/init` 抛非 OSError 时 traceback；CLI 崩溃 | `test_serial_discovery_skips_an_unexpected_parser_error` | 一个坏设备阻断整次按序列号发现 | `resolve_device` 将意外异常记为 blocked 并继续扫描 |


## 10. 2026-10-19 第五轮：全项目深度审计（DEF-022..031）

完整台账（含根因/复现/证据）：[bug-audit/BUG_TRACKER.md](../../../bug-audit/BUG_TRACKER.md)。

| ID | 严重度 | 状态 | 描述 | 证据（回归测试） | 影响 | 处理 |
|---|---|---|---|---|---|---|
| DEF-022 | P1 | 已修复/已验证 | `-O`/`--export -O` 目标是符号链接时，`os.replace` 替换链接本身；`-O /dev/stdout` + stdout 重定向到普通文件时，root 下可替换系统 `/dev/stdout`，非 root 直接失败 | `test_output_through_a_symlink_keeps_the_symlink`、`test_export_through_a_symlink_keeps_the_symlink`、`test_output_to_dev_stdout_follows_the_symlink` | 用户链接/系统设备名被破坏，输出路径错误 | 新增 `_must_write_through()`：symlink/FIFO/设备改为直接写入，仅普通文件走原子替换 |
| DEF-023 | P2 | 已修复/已验证 | Dashboard 1 s `/api/live` 覆盖层键名不匹配（latest.json 用 `vout_12v` 等，图表用 `12v` 等），10 个序列只有 `temp` 会动 | HTTP 键名测试 + Node 执行页面 JS 的集成测试；修复前 3 行数据但 12V 序列仅 1 点 | 实时曲线大部分冻结，页面宣称的 1 s 刷新名不副实 | `/api/live` 增加 `_live_view()` 历史列别名，原键保留 |
| DEF-024 | P1 | 已修复/已验证 | 每小时 prune 的 OSError 未捕获，从 `tick()` 抛出杀死常驻 daemon；systemd 会每小时重启循环 | `test_a_failing_prune_does_not_kill_the_daemon` | 长期运行稳定性 | prune 包 try/except，告警后继续采样 |
| DEF-025 | P2 | 已修复/已验证 | 0xE0 读失败但 E1h 应答时，E1h 的 False 被当成镜像告警的"恢复"：记 RECOVERED、`pin_imbalance` 被 retain 静默丢弃 | `test_a_failed_payload_read_does_not_clear_a_mirror_alert` | 告警消失且没有真实测量依据 | payload 缺失时镜像专属名字不进入 update；retain 保留 `pin_imbalance` |
| DEF-026 | P2 | 已修复/已验证 | `smoke.sh` 硬编码 `1.0.0_all.deb`、真实入口测试硬编码版本；版本升级后检查旧产物/误报失败 | `test_shell_scripts_do_not_hardcode_the_release_artifact_version` + e2e 版本测试 | 发布流程在下次 bump 时静默检查错产物 | 版本唯一来源 pyproject；e2e 用 `__version__` |
| DEF-027 | P3 | 已修复/已验证 | hardware kit `START-HERE.md` 写死 glibc 2.39（CI 实际 2.35） | `test_the_kit_start_page_reports_the_real_build_glibc` | 真机验收读错兼容下限 | `__GLIBC__` 从 `ldd` 注入，BUILD-INFO 同源 |
| DEF-028 | P3 | 已修复/已验证 | daemon `--state-dir ""`/`--prom-path ""` 被静默忽略，回落打包默认路径 | `test_empty_path_arguments_are_usage_errors`（3 参数） | 脚本变量未设置时写错目录 | 空路径按 argparse 用法错误 exit 2 |
| DEF-029 | P3 | 已修复/已验证 | `iter_alert_log(limit)` 先加载全部日志行再取尾部；30 天 5 MiB 日志可达数百 MB | `test_iter_alert_log_limit_keeps_the_newest_lines_in_order` | 小内存主机 OOM | 有 limit 时用 `deque(maxlen)` 流式保留最新 N 行 |
| DEF-030 | P4 | 已修复/已验证 | `--iterations` 帮助说 "positive samples"，实际按循环次数计（失败读也算） | `--help` 实测文本 | 文档/行为不一致 | 帮助与 docstring 改为 sample-loop passes |
| DEF-031 | P3 | 已修复/已验证 | 无 state 目录时未知 `/api/typo` 返回 503 而不是 404 | `test_an_unknown_api_route_is_404_even_without_a_state_dir` | 客户端拼写错误被误诊为服务端故障 | 目录检查只作用于 4 个真实 API 路由 |

回归：659 passed；ruff/format/mypy、smoke 58、coverage 92% 全绿（命令与输出见
[bug-audit/TEST_REPORT.md](../audit/TEST_REPORT.md)）。`DEF-002` 与 NR-001..006
仍未关闭，硬件/arm64/真实 systemd/桌面浏览器/24h 仍 BLOCKED。

## 11. 2026-10-19 第六轮：psu-file 需求资料对比（DEF-032..035）

对比对象：`psu-file/01_需求文档`（定稿需求、CLI 手册、技术评估 F-01..F-22、
PSU-7ZPU 草案 REQ-1..19）、`04_MSI-Center源码`、`03_参考实现`、`05_截图`。
完整矩阵：[psu-file-gap-analysis.md](psu-file-gap-analysis.md)。

| ID | 严重度 | 状态 | 描述 | 证据（参考实现 / 测试） | 处理 |
|---|---|---|---|---|---|
| DEF-032 | P2 | 已修复/已验证 | `--buzzer-off` 宣称 "Buzzer: silenced"，但 C2h 是 MSI 的无参数、无回读 `BUZZER_SWITCH`（toggle）：第二次执行会重新打开蜂鸣 | `CPSU.cs:1148-1159`；`verify.md` §8.11 早已写"switch 还是静音待确认" | 输出/帮助/审计/README/协议统一为 "switch toggled (no read-back)"；行为不变（仍只发一次 C2h） |
| DEF-033 | P2 | 已修复/已验证 | `--set-rail` 即使已是目标模式也会写 0xC0 + F1h；草案 REQ-11 要求先读回、同值直接返回（硬件同值会报错），且幂等调用会多消耗 flash 保存 | `PSU-7ZPU...md` REQ-11 | `apply_rail_mode()` 先读后写，同值返回 `(mode, False)`，输出 "already set" |
| DEF-034 | P3 | 已修复/已验证 | Dashboard 的 7 张曲线里缺独立效率图、多了 MSI 没有的 12V 总电流图，效率混在功率图（W/% 同轴） | 技术评估 §2（温度/12V/5V/3.3V/风扇/效率/瓦数 CPU-GPU-Total）；实屏 02 | CHARTS 改为 12V/5V/3.3V/效率/温度/风扇/功率(CPU/GPU/Total)；总电流仍进历史/导出/Prometheus |
| DEF-035 | P3 | 已修复/已验证 | MEG 序列号取 0x13 整包，依赖 24 字节后的报告为零；非零尾部会进入日志/Prometheus 标签 | `CPSU.cs:515-528`（MEG 固定 24 字节；TS 长度前缀） | 按机型分支读取：TS 长度前缀 / MEG 固定 24 字节 / 未知机型旧启发式 |

回归：661 passed，coverage 92%，smoke 58/58；完整命令见
[bug-audit/TEST_REPORT.md](../audit/TEST_REPORT.md)。

## 12. 2026-10-19 功能补齐：本地阈值与告警（FEAT-01，非缺陷）

按用户 2026-10-19 决定：**桌面通知不需要；阈值和告警必须有**。原草案
`thresholds.yaml` 改为 stdlib-only 的 INI `[alerts]` 段（项目不引入 YAML 依赖）：

| 配置键 | 默认 | 含义 |
|---|---:|---|
| `power_w` | 1200 | 总输出功率上限（W） |
| `temp_c` | 70 | PSU 内部温度上限（℃） |
| `pin_max_a` | 12 | 单针电流上限（A；C0h 出厂点） |
| `pin_imbalance_a` | 5 | 同一 12V-2x6 连接器 6 针的针差上限（A） |
| `connector_a` | 50 | 单个 12V-2x6 连接器 6 针电流和上限（A，600W/12V） |
| `rail_12v_a` / `rail_5v_a` / `rail_3v3_a` | 108.33 / 22 / 22 | 合并轨电流上限（A，产品规格） |

- 0 = 关闭该项。
- 阈值告警与硬件告警共用 AlertEngine（连续去抖）、stderr `ALERT`、exit 2、
  `alerts-*.log` 边沿/恢复日志；名字独立（`power_high`/`temp_high`/
  `rail_*_high`/`connector*_high`），不混入 12V-2x6 Status。
- 输出：text 增加 `Thresholds    : ...`；JSON 增加 `threshold_alerts`/
  `threshold_limits`；Prometheus 增加 `msi_psu_threshold_alert`/
  `msi_psu_threshold_limit`。
- 0xE0 读失败不清除已 latched 的阈值告警（缺读数 != 恢复）；`--no-alerts` 连阈值一起关闭。
- 回归：`test_alerts.py`、`test_config.py`、`test_cli_features.py`、
  `test_daemon.py`；全套 **680 passed**，coverage 92%，smoke 58/58。

## 13. 2026-10-19 运维/CLI 打磨（FEAT-02，非缺陷）

- Prometheus 空 label 指标改为规范写法 `metric{} value`（去掉 name 与 braces 间空格），
  消除 NR-001 的解析不确定性；
- 电量 counter 同时导出 `msi_psu_total_energy_kwh` 与 REQ-8 名 `msi_psu_energy_kwh_total`；
- 新增 `docs/prometheus-rules.yml`（Down/Stale/ScrapeError/HardwareAlert/ThresholdAlert），
  源码 .deb / 二进制 tar / hardware kit 均随包发布，并有 packaging 测试；
- 新增 `--dump-config`（text/json，无 PSU 访问，打印含 `[alerts]` 的生效配置）；
- `--help` 注明 per-pin/12V total 为 5 s 平均、EFF 来自 0xE0 offset 32、Conn1/Conn2 针序；
- 阈值告警 stderr 行带 measured/limit，便于真机调参。
- 回归：**689 passed**，coverage 92%，smoke 58/58。

## 14. 2026-10-19 硬件 OCP 阈值写（FEAT-03，非缺陷，保护写）

- 新增 `--dump-thresholds`（text/JSON）与 `--ocp-set`/`--load-thresholds`：
  `0xC0` 8 字节（amp LINEAR11 exp -4，`value<<4 + 0xE0`）+ `0xF1`；范围
  10-14 A / 4-8 A / 5-30 s / 5-30 s / 30-240 s，越界拒绝不 clamp；写后读回最多 3 次；
  同值不写；不支援机型（MEG/Ai1600T）exit 1。
- 安全边界：CI 只覆盖 demo/mock；真机需先导出原值、bench 验证、断电保持、再恢复。
  不是自动路径，daemon 不会调用。
- 初始化握手补 3 次 + 0.5/1.0 s 退避（REQ-18 的可安全实现部分；采样失败仍走 5 次重扫）。
- 新增严格 exposition 解析测试替代 promtool（无工具/无网络）。
- 全量回归：**735 passed**。
