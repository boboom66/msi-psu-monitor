# Release readiness（Phase 2 interim）

- 日期：2026-10-19
- 基线：`650076a` + Phase 2 修复
- 结论：**不满足无条件发布条件（NOT READY）**。

## 判定依据

| 条件 | 状态 | 证据/原因 |
|---|---|---|
| 代码构建 | PASS（本机 x86_64/24.04） | 源码 `.deb`、tar.gz、二进制 `.deb`、SBOM 均构建成功 |
| 自动化测试 | PASS | 630 passed；ruff/mypy/compileall 通过 |
| smoke | PASS | 58 passed，0 failed |
| 覆盖率门禁 | PASS | 源语句 92%，CI fail-under=90 |
| 真实 PSU 通信 | **BLOCKED（P1）** | 无 `/dev/hidraw*`、无样机 |
| 真实写入（风扇/Zero Fan/蜂鸣器/多轨） | **BLOCKED（P1）** | 需样机确认安全与持久性 |
| root/udev/systemd 安装启停 | **PARTIAL（P2）** | 用户命名空间内 install/uninstall/`--purge` 通过；真实 systemd/udev 未跑 |
| Ubuntu 22.04 / glibc 2.35 产物 | **BLOCKED（P1）** | 本机 24.04/2.39；CI 未实际运行 |
| arm64 产物/运行 | **BLOCKED（P1）** | 无 arm64 环境；arm runner 未验证 |
| 真实浏览器 Dashboard | **PASS（本机 headless）** | Playwright 1.64.1：range 切换、7 CSV/7 PNG、8 canvas、无 console/page error、无外部请求；320/768/1920 无横向溢出；尚未进 CI，见 [test-report](test-report.md) §10.5/§10.6 |
| 长稳/内存/fd | PARTIAL | 20,000 样本加速长稳 PASS（RSS/fd 稳定）；24h/72h 未跑 |
| 安装/卸载/升级/回滚 | **PARTIAL（P2）** | 用户命名空间 install/uninstall/`--purge` 通过；真实 root 未跑 |
| 硬件验收 kit | **PASS（软件层）** | kit 构建、setup（二进制/源码）、acceptance demo、证据打包通过 |
| 正式 tag 发布/下载 | **NOT RUN（P2）** | 未 push tag |

## 阻塞项

1. 无真实 PSU：所有硬件读取、告警、写入、VIN/多轨/蜂鸣器语义均不能判定 PASS。
2. 本机不是发布基线：必须用 CI `ubuntu-22.04` / `ubuntu-22.04-arm` 的产物复验。
3. root 安装/udev/systemd 未执行：安装脚本只能算静态审查。

Phase 3 已修复 7 类软件缺陷（输出错误/配置边界/CSV/资源泄漏等，见
[bug-report.md](bug-report.md) DEF-005..011），但**没有改变**上述 P1 阻塞结论；软件层通过不等于真机/发布环境通过。

## 解除条件

- 真机按 `docs/verify.md` §8 的 18 项完成，尤其 VIN、多轨、buzzer、黑盒 pin/set。
- 在 22.04 与 arm64 构建并执行 clean-env `--once` + smoke。
- root 容器/机器执行 install/uninstall/重装/`--purge`。
- 真实浏览器完成图表、PNG/CSV、1s live、CSP 验证。
- 24h 以上长稳与真实 release 下载校验。

## 剩余风险

见 [bug-report.md](bug-report.md) RISK-001..012；未解决前不得把项目标为生产合格。
