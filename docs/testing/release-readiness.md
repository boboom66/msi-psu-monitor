# Release readiness（Phase 3，历史快照）

> **历史记录，不是当前结论。** 当前发布判断见
> [bug-audit/RELEASE_READINESS.md](../../bug-audit/RELEASE_READINESS.md)。本文件中的
> 测试数、覆盖率和浏览器结论均是 Phase 3 历史记录，不代表当前状态。

- 日期：2026-10-19
- 基线：`e3ab7ae`（CI release v1.0.0）+ Phase 3 修复
- 结论：**不满足无条件发布条件（NOT READY）**。

## 判定依据

| 条件 | 状态 | 证据/原因 |
|---|---|---|
| 代码构建 | PASS（CI 22.04 + 本机） | CI x86_64/arm64 tar.gz/.deb/SBOM/kit 构建成功 |
| 自动化测试 | PASS | 645 passed；ruff/mypy/compileall 通过 |
| smoke | PASS | 58 passed，0 failed |
| 覆盖率门禁 | PASS | 源语句 92%，CI fail-under=90 |
| 真实 PSU 通信 | **BLOCKED（P1）** | 无 `/dev/hidraw*`、无样机 |
| 真实写入（风扇/Zero Fan/蜂鸣器/多轨） | **BLOCKED（P1）** | 需样机确认安全与持久性 |
| root/udev/systemd 安装启停 | **PARTIAL（P2）** | 用户命名空间内 install/uninstall/`--purge` 通过；真实 systemd/udev 未跑 |
| Ubuntu 22.04 / glibc 2.35 产物 | **PASS（CI）** | GitHub Actions `ubuntu-22.04` build/publish success；[release](https://github.com/boboom66/msi-psu-monitor/releases/tag/v1.0.0) |
| arm64 产物/运行 | **PARTIAL（P1）** | CI `ubuntu-22.04-arm` build success；运行/真机仍未验证（无 arm64 环境） |
| 真实浏览器 Dashboard | **PASS（本机 headless）** | Playwright 1.64.1：range 切换、7 CSV/7 PNG、8 canvas、无 console/page error、无外部请求；320/768/1920 无横向溢出；尚未进 CI，见 [test-report](test-report.md) §10.5/§10.6 |
| 长稳/内存/fd | PARTIAL | 20,000 样本加速长稳 PASS（RSS/fd 稳定）；24h/72h 未跑 |
| 安装/卸载/升级/回滚 | **PARTIAL（P2）** | 用户命名空间 install/uninstall/`--purge` 通过；真实 root 未跑 |
| 硬件验收 kit | **PASS（软件层）** | kit 构建、setup（二进制/源码）、acceptance demo、证据打包通过 |
| 正式 tag 发布/下载 | **PASS** | CI release v1.0.0 发布、资产/SHA256SUMS 下载并核对；见 evidence-ci-release.txt |

## 阻塞项

1. 无真实 PSU：所有硬件读取、告警、写入、VIN/多轨/蜂鸣器语义均不能判定 PASS。
2. arm64 只有 CI build，尚无 arm64 运行/真机证据。
3. root 安装/udev/systemd 未执行：安装脚本只能算静态审查。
4. 24h/72h 长稳、真实桌面浏览器仍未跑。

Phase 3 已修复 15 类软件缺陷（输出错误/配置边界/CSV/资源泄漏/响应式等，见
[bug-report.md](bug-report.md) DEF-005..021），并已拿到 CI 22.04 与 arm64 构建产物；软件层通过不等于真机验收。

## 解除条件

- 真机按 `docs/verify.md` §8 的清单完成，尤其 VIN、多轨、buzzer、黑盒 pin/set。
- arm64 环境执行 clean-env `--once` + smoke（x86_64/22.04 CI 已完成）。
- root 容器/机器执行 install/uninstall/重装/`--purge`。
- 真实桌面浏览器完成最终页面/下载验收（headless 已通过）。
- 24h/72h 长稳。

## 剩余风险

见 [bug-report.md](bug-report.md) RISK-001..012；未解决前不得把项目标为生产合格。
