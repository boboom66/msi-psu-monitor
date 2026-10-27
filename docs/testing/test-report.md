# msi-psu-monitor 基线测试报告（第一阶段，历史归档）

> **历史快照（2026-10-19/21）**。本文结果只代表当时的测试轮次；当前发布状态见 [`bug-audit/RELEASE_READINESS.md`](../../bug-audit/RELEASE_READINESS.md)。

- 执行时间：2026-10-19 10:01–10:05（Asia/Shanghai）
- 提交：`650076a263d9f6126c58508c60963102116ec4f2`
- 工作树：干净（`git status --porcelain` 空）
- 环境：Ubuntu 24.04 LTS / WSL2 6.18 / glibc 2.39 / Python 3.12.3 / systemd 255 / x86_64
- 硬件：无 `/dev/hidraw*`、无 `/sys/class/hidraw`；普通用户，无免密 sudo

## 1. 自动化测试

```bash
$ uv run --group dev pytest -q
569 passed in 15.87s
```

- 测试收集：`569 tests collected`。
- 本阶段实测 Python：3.10.21（裸环境）→ 569 passed；3.12.3（裸环境）→ 569 passed；
  3.12.3（项目 venv）→ 569 passed。3.13 由 CI/历史记录覆盖，本阶段未重跑。
- 测试模块 21 个；各模块用例数：

| 模块 | 用例 |
|---|---:|
| test_cli_features.py | 94 |
| test_state.py | 65 |
| test_psu_sensors.py | 63 |
| test_ocp.py | 56 |
| test_demo.py | 49 |
| test_daemon.py | 46 |
| test_dashboard.py | 36 |
| test_config.py | 32 |
| test_protocol_lin11.py | 18 |
| test_packaging.py | 17 |
| test_protocol_discovery.py | 16 |
| test_cli_alerts.py / test_alerts.py | 13 / 13 |
| test_monitor_format.py / test_docs_consistency.py | 11 / 11 |
| test_protocol.py | 8 |
| test_pid_consistency.py | 6 |
| test_release_security.py | 5 |
| test_monitor.py | 4 |
| test_stdlib_only.py / test_schema.py | 3 / 3 |

## 2. 静态检查

```bash
$ uv run --group dev ruff check .
All checks passed!
$ uv run --group dev ruff format --check .
40 files already formatted
$ uv run --group dev mypy msi_psu_monitor/
Success: no issues found in 10 source files
$ python3 -m compileall -q msi_psu_monitor scripts/build_sbom.py
compileall-ok
$ shellcheck -S warning scripts/*.sh
exit 0（warning 级别无输出）
$ systemd-analyze verify systemd/msi-psu-monitor.service
exit 0
```

补充：默认级别 `shellcheck scripts/*.sh` 退出 1，内容全是 info/style，包括
`scripts/smoke.sh` 的 SC2015（A && B || C）和 SC2086（`$MONITOR` 未加引号）。
该轮 CI 使用 `-S warning`，因此当时门禁通过；这些是 P3 测试脚本质量问题，不是产品故障。

## 3. 覆盖率（一次性测量，不写回项目）

```bash
$ uv run --with coverage coverage run --branch -m pytest -q
569 passed
$ uv run --with coverage coverage report -m
```

| 源模块 | 语句覆盖率 |
|---|---:|
| `msi_psu_monitor/alerts.py` | 96.81% |
| `config.py` | 92.48% |
| `daemon.py` | 89.50% |
| `dashboard.py` | 93.83% |
| `demo.py` | 98.31% |
| `monitor.py` | 91.42% |
| `protocol.py` | 91.06% |
| `state.py` | 92.65% |
| `__init__.py` | 100% |
| **源合计** | **语句 93.02% / 分支 89.20%** |

说明：`coverage` 是用 `uv run --with` 临时提供的，不写入 `pyproject.toml`；
`__main__.py`、安装/构建 shell 脚本、内嵌浏览器 JS 不在这份覆盖率里。

## 4. 无硬件冒烟

```bash
$ bash scripts/smoke.sh
结果: 58 passed, 0 failed
```

覆盖：三种格式、告警 exit 2 与按机型告警名、黑盒、OCP、风扇/Zero Fan/蜂鸣器写、
daemon→Prometheus+历史、dashboard HTTP、`.deb` 内容/权限、3.10 语法。

## 5. 构建产物（本地 x86_64）

```bash
$ ALLOW_NEWER_GLIBC=1 bash scripts/build_binary.sh
[INFO] Release: dist/msi-psu-monitor_1.0.0_linux_x86_64.tar.gz
$ bash scripts/build_deb_binary.sh
$ dpkg-deb -f dist/msi-psu-monitor_1.0.0_amd64.deb Depends
libc6 (>= 2.35), zlib1g
$ python3 scripts/build_sbom.py --dist dist --output dist/SBOM-x86_64.json --arch x86_64
wrote dist/SBOM-x86_64.json (10 components; hardware-kit artifact included)
```

- tar.gz 包含 `install.sh`/`uninstall.sh`/unit/udev/config/README/LICENSE/SECURITY/docs/SHA256SUMS。
- 二进制 clean-env：`env -i PATH=/usr/bin:/bin HOME=/tmp MSI_PSU_DEMO=1 ... --version`
  → `msi-psu-monitor 1.0.0`；`--once` 输出 demo 读数。
- `ldd`（clean env）只显示 libdl/libz/libpthread/libc，无 libpython。
- **限制**：本机 glibc 2.39，构建脚本必须 `ALLOW_NEWER_GLIBC=1`；这不是 22.04 官方产物。
  Phase 3 已用 Ubuntu 22.04 rootfs/chroot 构建并在 22.04 内运行通过（见 §10.8）；CI provenance 仍未生成。

## 6. 端到端行为抽样

```text
MSI_PSU_DEMO=1 --once                         exit 0，文本读数
MSI_PSU_DEMO=1 -f json                        exit 0，json.tool 可解析
MSI_PSU_DEMO=1 -f prometheus                  31 条 msi_psu_* 指标
--fan-mode performance                        Fan mode: performance，exit 0
--zero-fan off                                Zero Fan: off，exit 0
--buzzer-off                                  Buzzer: silenced，exit 0
--set-rail multi (ai1300p)                    Rail mode: multi，exit 0
--set-rail multi (TS)                         exit 1，read-back/机型拒绝
--ocp (TS)                                    exit 0，8B 阈值视图
--ocp (ai1300p)                               exit 0，multirail 视图
--show-log                                    exit 0，黑盒头
--show-alert-log（空）                        exit 0，No alert log records stored.
--no-alerts + 注入告警                        exit 0，无 ALERT 行
注入 ocp_pin1                                 exit 2，stderr ALERT 行
daemon --iterations 2                          state.json/daily/latest.json/psu.prom 落盘
--export --from 2h --columns temp,fan          9 列表头 + 1 行数据
Dashboard / /api/history /api/state /api/live /api/export → 200；/nope → 404
daemon + alert 注入                              alerts-YYYYMMDD.log 写入，--show-alert-log 可读
```

## 7. 失败、阻塞、未执行

| 项目 | 状态 | 原因 |
|---|---|---|
| 569 自动化测试 | PASS | 全部实际执行 |
| smoke 58 | PASS | 实际执行 |
| 静态检查/覆盖率/构建 | PASS（有环境限制） | 见上 |
| 真实 hidraw/PSU 通信 | BLOCKED | 无 `/dev/hidraw*` |
| root/udev/systemd 实际启停 | BLOCKED | 普通用户，sudo 需密码 |
| 安装/卸载脚本实际执行 | NOT RUN | 需要 root 与 systemd |
| Ubuntu 22.04/glibc 2.35 构建 | PASS（本地 chroot）/CI NOT RUN | Phase 3 §10.8；本机 24.04/2.39 仅用于开发烟测 |
| arm64 构建/运行 | BLOCKED | 无 arm64 环境 |
| Dashboard 真实浏览器 | NOT RUN | 无浏览器自动化 |
| 长稳/内存/fd 泄漏 | NOT RUN | 未设计长时间测试 |
| HID 负向/模糊测试 | NOT RUN | 现有假帧单测不足以称 fuzz |
| release workflow 实际发版 | NOT RUN | 未 push tag |

## 8. 结论

软件层自动化基线健康：569/569、静态门禁通过、冒烟 58/58、源码语句覆盖 93%。
但本报告不能证明真实 PSU、真实 systemd/udev、22.04/arm64 发布产物或浏览器端行为；
这些必须在后续阶段明确保留为 BLOCKED/NOT RUN，不能写成 PASS。

## 9. Phase 2 增量（2026-10-19）

- 当时提交：Phase 3 修复（见 git log），测试 **645 passed**（3.10.21 / 3.12.3 裸环境与 3.12.3 venv）。
- 覆盖率：源语句 **92%**（`coverage report` 8 个模块；`__main__.py` 未覆盖）；CI 的门限为 90%。
- 新增测试：真实 console 子进程 E2E、Host/CSP、JS 语法、HID 短/垃圾帧、daemon fd 泄漏、
  `--iterations` 边界、AlertLog `-O`、release/CI 门禁静态检查；
  以及用户命名空间内真实安装/卸载（配置保留、systemctl/udevadm 调用、`--purge`）。
- 修复：Dashboard Host 仅 loopback（否则 421）+ CSP/Permissions-Policy；`--iterations 0/-1` 拒绝；
  覆盖率纳入 dev 依赖与 CI；release workflow 增加 ruff/format/mypy/smoke 门禁；
  冻结二进制 smoke 增加 performance/多轨/AlertLog/VIN 检查。
- smoke：**58 passed, 0 failed**；本地二进制重新构建通过。
- 硬件验收 kit：`build_hardware_kit.sh` 构建通过；kit 内 `setup.sh`（二进制/源码回退）在用户命名空间中安装/卸载通过；`acceptance.sh --demo` 30 项 PASS、3 项 MANUAL、2 SKIP；证据 tar 生成。
- 仍 BLOCKED/NOT RUN：真实 hidraw/PSU、root/systemd/udev、安装卸载、22.04/arm64、真实浏览器、
  24h/72h 长稳、真实 tag 发布。

> Phase 1 段落中的 569 是当时基线，保留作历史记录；当时以本节 645 为准。

## 10. Phase 3 全量审计增量（2026-10-19）

### 10.1 实际执行证据

```text
pytest -q                              645 passed in 17.9s
ruff check .                           All checks passed!
ruff format --check .                  50 files already formatted
mypy msi_psu_monitor/                  Success: no issues found in 10 source files
coverage run --branch -m pytest -q     645 passed
coverage report                        TOTAL 92% (statement)
bash scripts/smoke.sh                  58 passed, 0 failed
shellcheck -S warning scripts/*.sh scripts/hardware/*.sh   exit 0
systemd-analyze verify                 exit 0
```

### 10.2 Phase 3 确认并修复的缺陷

- **DEF-005（P2）输出错误处理**：`--show-alert-log -O` 曾 traceback；`--once -O`/`--ocp -O` 误报 “Run as root”；stdout 写满时 exit 120。
  修复：`OutputError` + main 的 OSError 处理 + stdout 清理；回归覆盖 4 类入口。
- **DEF-006（P2）配置 interval**：`[monitor] interval` 非正未校验；裸 `--watch` 忙循环/异常。修复为回落 2.0。
- **DEF-007（P3）performance duty**：performance 模式仍保留 duty，改为与 auto 一样清理。
- **DEF-008（P3）`--columns all,typo`**：先遇到 all 就静默全选；改为先校验所有 token。
- **DEF-009（P3）`iter_alert_log(limit=0)`**：Python `[-0:]` 返回全部；改为返回空。
- **DEF-010（P2）daemon 初始化失败 fd 泄漏**：open 成功、init 失败未 close；修复失败路径关闭。
- **DEF-011（P3）Dashboard CSV 拼列**：`
.join` 改为 `csv.writer`，含逗号/引号的值不再错列。

### 10.3 状态统计

| 状态 | 数量/说明 |
|---|---|
| PASS | 645 个自动化测试 + 静态检查 + smoke 58 |
| FAIL | 0（本轮修复后） |
| BLOCKED | 真实 hidraw/PSU、root/systemd/udev、22.04/arm64、真实浏览器、长稳、正式发版 |
| NOT RUN | 24h/72h、真实 release 下载/升级/回滚、真实浏览器 PNG/CSV |
| MANUAL | 真机 VIN/多轨/buzzer/告警/风扇主观项 |

### 10.4 残余风险

仍以 [bug-report.md](bug-report.md) 的 RISK-001..012 为准；最重要的 P1 仍是**无真实 PSU** 与**未在 22.04/arm64 构建运行**。
本轮修复只覆盖软件层可复现缺陷，不能替代真机验收。

### 10.5 真实 headless Chromium Dashboard 验证（2026-10-19）

- 浏览器：Playwright 1.64.1 + `chromium_headless_shell-1248`（Linux x86_64）。
- 数据：demo daemon 写入 `/tmp/psu-dash-state`，dashboard 用 `MSI_PSU_STATE_DIR` 指向同一目录。
- 结果：`title=MSI PSU Monitor`；正文包含 `MPG Ai1600TS` 与 `12.09 V`；8 个 `<canvas>`；
  `Export CSV` 下载 235B、首行 `time,`；图表 `PNG` 下载 3409B 且 PNG 签名有效；
  `pageerror=[]`、`console error=[]`、外部请求 `[]`。
- 截图证据：[evidence-dashboard-headless.png](evidence-dashboard-headless.png)。
- 限制：这是 headless shell，不是桌面 Firefox/Chrome；Playwright 未进项目依赖/CI，不能当作发布环境全浏览器矩阵。

### 10.6 浏览器交互 / 响应式（2026-10-19）

- Playwright headless Chromium：range 30m/2h/7d 切换后 `#csv` href 同步；
- 7 个卡片 CSV（34–45KB）+ 7 个卡片 PNG（6–20KB）全部触发下载且 PNG 签名有效；
- 8 个 canvas 均有数据；`pageerror=[]`、`console error=[]`、外部请求 `[]`；
- 320px 视口初测发现 `scrollWidth=360 > clientWidth=320`，定位为 `.grid` 的 `minmax(340px,1fr)`；
  改为 `minmax(min(340px,100%),1fr)` 后 320/768/1920 均无横向溢出。对应 DEF-012。
- 证据：[evidence-dashboard-headless.png](evidence-dashboard-headless.png)。

### 10.7 加速长稳 / 资源（2026-10-19）

- demo daemon 20,000 样本，`sample_interval=0.01`，约 200 秒；每 5 秒采 `/proc/<pid>`。
- 结果：RSS 约 16.6MB 稳定、fd=3 恒定、prom 约 4.4KB 稳定、history 1,164 行；
  无 traceback，正常 `Stopped after 20000 samples`。
- 证据：[evidence-soak-20k.tsv](evidence-soak-20k.tsv)。**24h/72h 仍未跑**。

### 10.8 Ubuntu 22.04 / glibc 2.35 本地 chroot 构建（2026-10-19）

- 使用 `ubuntu-base-22.04.5-base-amd64.tar.gz` + userns chroot；系统 Python 3.10.12，PyInstaller 6.16.0。
- 产物在 22.04 chroot 内实际执行：`--version`、`--once`、`--show-alert-log` 均通过。
- 冻结 smoke 8 项：once / zero-fan / buzzer / performance / rail / alertlog / VIN / clean-env 全 PASS。
- 本地 `.deb`：`msi-psu-monitor_1.0.0_amd64.deb`，`Depends: libc6 (>= 2.35), zlib1g`。
- `.deb` 解包后同样在 22.04 内运行 `--version/--once` 通过；硬件 kit 的 `acceptance.sh --demo` 30 PASS/0 FAIL。
- 复现步骤：[build-2204-chroot.md](build-2204-chroot.md)；证据：[evidence-2204-build.txt](evidence-2204-build.txt)。
- **限制**：这是本地 chroot，不是 GitHub Actions 的 `ubuntu-22.04` runner；arm64 仍未构建。

### 10.9 GitHub Actions 22.04/arm64 release（2026-10-19）

- Release: <https://github.com/boboom66/msi-psu-monitor/releases/tag/v1.0.0>
- Run: <https://github.com/boboom66/msi-psu-monitor/actions/runs/39208968894>
- 提交：`e3ab7ae827943c86584880a9f040659e85bab928`（tag `v1.0.0`）。
- Jobs：`build (ubuntu-22.04, x86_64, amd64)` success、`build (ubuntu-22.04-arm, aarch64, arm64)` success、`publish` success。
- 资产：x86_64/aarch64 tar.gz、amd64/arm64 `.deb`、SBOM、两架构 hardware kit、`SHA256SUMS`；
  `SHA256SUMS` 覆盖 kit，**不含** smoke 生成的 `_all.deb`；API digest 与 `SHA256SUMS` 全部一致。
- 两个 tar 的 `BUILD-INFO` 均为 `build_glibc=2.35`；aarch64 二进制经 `file` 确认为 ARM aarch64。
- 证据：[evidence-ci-release.txt](evidence-ci-release.txt)。

### 10.10 第二轮 CLI/导出修复（2026-10-19）

- DEF-015：`--export -O` 改为 scratch + fsync + replace；失败保留旧文件，新增回归。
- DEF-016：`-f/--format` 与 `--serial` 在固定输出/本地历史模式中不再静默忽略；配置文件 format 给出 warning。
- 当时全套 **645 passed**；新增测试已实际执行。

### 10.11 第三轮稳健性修复（2026-10-19）

- DEF-017：daemon 的设备 read/open/enrichment/history/prometheus 非 OSError 异常不再杀进程；记录并重试/计失败。
- DEF-018：0 W 样本不再被 `_valid_sample` 跳过。
- DEF-019：默认 state 路径是普通文件时回退 XDG。
- DEF-020：空 `--serial` 改为 argparse exit 2。
- 当时全套 **645 passed**；新增测试实际执行。

### 10.12 第四轮发现/修复（2026-10-19）

- DEF-021：`resolve_device` 在按 serial 扫描时，单个设备的意外异常会 traceback；现记为 blocked、继续扫描。
- 当时全套 **645 passed**；新增测试实际执行。
## 11. 第五轮全项目深度审计（2026-10-19）

完整命令、复现与未执行清单：[bug-audit/TEST_REPORT.md](../../bug-audit/TEST_REPORT.md)。

### 11.1 基线

- 干净基线 `fdfc97d`：实际执行 **645 passed**（17.98 s），ruff/format/mypy 全绿。
- 本轮先复现再修复：符号链接输出、1 s 实时曲线键名、prune 异常、payload 丢失清告警、
  版本硬编码、kit glibc、空路径参数、AlertLog 内存、未知 API 404。

### 11.2 修复后验证（真实执行）

| 检查 | 结果 |
|---|---|
| `pytest -q` | **659 passed**（18.84 s） |
| `ruff check .` / `ruff format --check .` | clean / 53 formatted |
| `mypy msi_psu_monitor/` | clean（10 files） |
| `coverage run --branch` + `coverage report --fail-under=90` | **92%**（2586 stmts / 188 missed；874 branches / 67 partial） |
| `bash scripts/smoke.sh` | **58 passed, 0 failed** |
| `shellcheck -S warning scripts/*.sh scripts/hardware/*.sh` | clean |
| `systemd-analyze verify` / `udevadm verify` | clean / Success 1, Fail 0 |
| Node 执行页面 JS（live 覆盖层） | 3 行数据 → 每个图表序列 3 点；修复前仅 1 点 |
| 270 组 CLI 参数组合、200 个随机配置、19 个畸形 HTTP 请求、并发 daemon+dashboard+CLI | 无 traceback、无状态损坏 |
| daemon `--iterations` 帮助 | 已改为 sample-loop passes（失败读也计数） |

### 11.3 未执行（不得算 PASS）

- 真实 PSU 全部读写/告警/黑盒/OCP/多轨/拔插：**BLOCKED**（无 hidraw）。
- arm64 运行、真实 root/systemd/udev、桌面浏览器、24h/72h：**BLOCKED / NOT RUN**。
- 浏览器：本地 headless shell 缺 `libnspr4.so` 无法启动；JS 改用 Node DOM stub 执行。
- `promtool check metrics`：未安装、无网络安装渠道（NR-001）。

### 11.4 结论

软件自动化门禁全绿，DEF-022..031 全部有可复现回归；但真机、arm64、真实安装、
浏览器与长稳仍是发布阻塞项，且本轮修复尚未进入任何已发布产物。

## 12. 第六轮：psu-file 需求资料对比（2026-10-19）

- 对照 `psu-file` 的定稿需求、CLI 手册、技术评估 F-01..F-22、草案 REQ-1..19、
  MSI Center 源码与参考实现；完整差距矩阵见
  [psu-file-gap-analysis.md](psu-file-gap-analysis.md)。
- 确认并修复 DEF-032..035：蜂鸣器 toggle 误报为静音、`--set-rail` 同值仍写、
  Dashboard 7 张曲线构成不符、MEG 序列号未按固定 24 字节读取。
- 复核后 **661 passed**；ruff/format/mypy clean；coverage 92%；smoke 58/58。
- 冻结范围（定稿需求 + missing-features 清单）内未发现整块功能缺失；
  草案未冻结项（thresholds.yaml 快路 power/temp、OCP 写/dump/load、桌面通知、
  promtool 自检、命令级重试/退避、udev 固定软链、Prometheus rules）明确列入
  差距文档 §5，不伪装成已实现。
- 硬件/arm64/真实 systemd/桌面浏览器/24h/72h 仍 BLOCKED，结论不变。

## 13. 第七轮：本地阈值/告警补齐（2026-10-19）

- 需求：用户确认桌面通知不做，但阈值与告警必须有；原 `thresholds.yaml` 草案改为
  stdlib-only INI `[alerts]`（8 个键，0=关闭），默认值即 REQ-14 初值。
- 实现：`alerts.evaluate_threshold_alerts/configured_threshold_names`、
  `config.threshold_limits`、`monitor.attach_alerts`（文本/JSON/Prometheus/
  exit 2/告警日志统一链路）、daemon 复用同一入口。
- 设计约束：阈值名与 E1h 名分离，不污染 12V-2x6 Status；缺读数不视为恢复；
  `--no-alerts` 连阈值一起关闭；0 = 关闭单项。
- 结果：**680 passed**；ruff/format/mypy clean；coverage 92%；smoke 58/58。
  详细命令/未执行项见 [bug-audit/TEST_REPORT.md](../../bug-audit/TEST_REPORT.md)。

## 14. 第八轮：运维/CLI 打磨（2026-10-19）

- 依据：U-04/U-06/U-07/F-19 的剩余可做项 + 产品打磨。
- 变更：Prometheus 规范 exposition（空 label 无空格，消除 NR-001 的语法不确定）；
  电量 counter 双名（`msi_psu_total_energy_kwh` + REQ-8 的 `msi_psu_energy_kwh_total`）；
  `docs/prometheus-rules.yml`（Down/Stale/ScrapeError/HardwareAlert/ThresholdAlert）随源码
  .deb/二进制 tar/hardware kit 发布；`--dump-config`（text/json，无 PSU 可打印生效阈值）；
  `--help` 注明 5s 平均/EFF 源/针序；阈值 ALERT 行带 measured vs limit。
- 结果：**689 passed**；ruff/format/mypy clean；coverage 92%；smoke 58/58。
- 仍未执行：`promtool check metrics`（无工具/无网络）；真实 PSU、arm64、桌面浏览器、
  24h/72h 仍 BLOCKED。

## 15. 第九轮：OCP 阈值写 + 握手退避 + promtool 替代（2026-10-19）

- 用户要求"除没有真机无法修补的，其它能补的都补"。本轮补齐：
  - 硬件 OCP 阈值写：`--ocp-set`（5 值 + 可选 on/off）、`--load-thresholds`（接受
    `--ocp/-f json` 的 `ocp_config` 或扁平 JSON）、`--dump-thresholds`（text/JSON）；
    `0xC0` 8 字节（amp LINEAR11 exp -4）+ `F1h`，范围硬校验、读回最多 3 次、同值不写、
    不支援机型 exit 1。**保护写，CI 只覆盖 demo/mock，真机 bench 未做**。
  - 初始化握手 3 次 + 0.5/1.0 s 指数退避（REQ-18）。
  - 新增 `tests/test_prometheus_exposition.py`：严格解析我们自己的 exposition，
    作为 promtool 的本机替代（promtool 仍无工具可跑）。
- 回归：**736 passed**；ruff/format/mypy clean；覆盖率 **93%**（2957 stmts / 195 missed / 1084 branches）；smoke 58/58。
- 仍 NOT RUN：promtool 官方校验、真实 PSU 的 OCP 写/断电保持、arm64、真实
  root/systemd/udev、桌面浏览器、24h/72h。

## 16. 第十轮：可靠性/发布收口（2026-10-19）

- `scripts/soak.sh`：可重复 5k 采样门禁（CI 已接线），50k 本地长跑 exit 0、
  peak RSS 16.4 MB、fd=3、状态目录 28 KB；`tests/test_soak.py` 覆盖坏参数与短线。
- 确定性 fuzz（`tests/test_robustness.py`）：400 随机 0xE0 payload × 5 机型、
  120 随机配置、120 随机 `--ocp-set`，无 traceback / 无 NaN、inf 外泄。
- 多轨 formatter 回归（12V1-5 电压/电流 + CPU/GPU 拆分 + Prometheus rail 标签）。
- OCP 写诊断：不支援机型、配置读取失败、未知 JSON 键、可选 on/off 均有明确退出码。
- 发布文档：新增 `CHANGELOG.md` 并随源码 deb、二进制 deb、tar、kit 发布；
  RELEASE_READINESS/support/incident/SECURITY/protocol 同步 OCP 写边界。
- 环境复核：venv Python 3.12.3 **736 passed**；裸 Python 3.13.15（uv 缓存解释器，
  只装 pytest）**736 passed**；3.10 由 ruff/mypy/ast 静态兜底（本机无 3.10）。
- 冻结二进制本地重建（ALLOW_NEWER_GLIBC=1，仅验证打包链路）：CLI/daemon 7.8 MB，
  binary .deb Depends 仍仅 libc6/zlib1g，hardware-kit demo **30 PASS**。
- 当时门禁（2026-10-19）：736 passed、ruff/format/mypy clean、coverage **93%**、smoke 58/58、
  soak 5k PASS、acceptance demo 30 PASS。
