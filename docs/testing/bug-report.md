# msi-psu-monitor 缺陷与风险登记（第一阶段）

- 基线：`650076a`；执行时间：2026-10-19。
- 本文件区分“确认缺陷”和“测试缺口/发布风险”；未执行的测试不写成通过。

## 1. 确认缺陷

| ID | 严重度 | 状态 | 描述 | 证据 | 影响 | 处理 |
|---|---|---|---|---|---|---|
| DEF-001 | P3 | 待修 | `scripts/smoke.sh` 中 `timeout 3 $MONITOR ...` 未引用变量 | `shellcheck` SC2086 | 冒烟脚本在路径含空格时失败；不影响发布二进制 | Phase 2 修复并跑 smoke |
| DEF-002 | P3 | 待评审 | `pyproject.toml` 仍标 `Development Status :: 4 - Beta`，作者邮箱为 `contributors@example.com`，Homepage 指向上游而非 fork | `pyproject.toml` | 官网/包元数据与“生产级”定位不一致 | 发布前确认版本/元数据策略 |

基线未发现可复现的 P0/P1/P2 软件功能缺陷；这不等于不存在缺陷，硬件与浏览器/安装路径仍未测。

## 2. 发布/测试风险

| ID | 级别 | 类型 | 风险 | 现状 | 建议 |
|---|---|---|---|---|---|
| RISK-001 | P1（阻塞发布） | 硬件 | 真实 PSU 通信、5 机型差异、告警/写控制/黑盒未验证 | 无 `/dev/hidraw*`，全部 BLOCKED | 真机按 verify §8 的 18 项执行 |
| RISK-002 | P1（阻塞发布） | 构建环境 | 本机 glibc 2.39 构建的二进制不能代表 22.04/2.35 官方产物 | 本地需 `ALLOW_NEWER_GLIBC=1` | 在 CI `ubuntu-22.04` 构建并执行 clean-env 测试 |
| RISK-003 | P2 | 发布门禁 | release workflow 只跑 pytest，不跑 ruff/mypy/shellcheck/smoke；tag 推送可直接发布，且 arm64 仅 release 时构建 | `.github/workflows/release.yml` | release 前把 CI 门禁设为 needs/复用，或增加同等步骤 |
| RISK-004 | P2 | 安装 | `install_binary.sh`/`uninstall_binary.sh`、udev、systemd 启停未实际执行 | 普通用户，无免密 sudo | 在一次性容器/root 环境跑安装/卸载/重装 |
| RISK-005 | P2 | 前端 | Dashboard JS 只用 HTTP/源码断言，无真实浏览器测试 | 无浏览器自动化 | 用 Playwright/Chromium 跑页面加载、图表、PNG/CSV、1s live |
| RISK-006 | P2 | 安全 | Dashboard 未校验 Host 头，存在 DNS rebinding 读取本地数据面的风险 | `_route` 无 Host 检查 | 增加 loopback Host/Origin 校验与测试 |
| RISK-007 | P2 | 数据 | `state.json`/日志/串口标签可能被本机其他用户读取，序列号属于可识别信息 | unit 无 UMask，文件默认 0644 | 做权限/数据分类评审，决定 0640+组或脱敏 |
| RISK-008 | P2 | 兼容 | arm64、Ubuntu 22.04、真实 systemd 沙箱未验证 | 仅 x86_64/24.04 | 增加构建/运行矩阵或明确发布限制 |
| RISK-009 | P2 | 质量 | 覆盖率未进 CI，当前 93% 是一次性测量；无长稳/泄漏/HID fuzz | 无 coverage 依赖、无长跑测试 | dev 组加 coverage 门槛（按模块定目标），补负向帧与长跑 |
| RISK-010 | P2 | 文档 | 安装/发布/支持文档复制粘贴风险；已有文档一致性测试，但未覆盖 docs/testing 与安装命令 | 文档测试有限 | 发布前人工审查 + 链接检查 |
| RISK-011 | P3 | 测试脚本 | `shellcheck` 默认级别 info（SC2015/SC2086），CI 用 warning 才过 | `smoke.sh` | 修 DEF-001，必要时调整风格 |
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
