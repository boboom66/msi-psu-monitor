# 测试覆盖与限制（Test Coverage）

- 测试：645 passed；Python 3.10/3.12/3.13；源语句覆盖率 92%（branch 统计见 CI）。
- smoke：58 passed；硬件 kit demo acceptance：26 PASS / 0 FAIL / 3 MANUAL。
- 浏览器：Playwright headless Chromium 页面/CSV/PNG 已实际通过。

## 源码模块覆盖

| 模块 | 语句覆盖 | 主要已验证行为 | 未验证/限制 |
|---|---|---|---|
| `protocol.py` | 92% | HID 帧、NAK、LINEAR11、机型分发、传感器、风扇/黑盒/OCP/告警解析（mock 帧） | 真实 PSU/固件差异 BLOCKED |
| `monitor.py` | 92% | 全部 CLI 模式、输出格式、告警退出码、写入 read-back（stub） | 真实写入/真机语义 BLOCKED |
| `daemon.py` | 89% | 采样、prom/history/latest、失败重扫、fd、fan restore（stub） | 真实硬件 systemd 长跑 BLOCKED |
| `state.py` | 93% | 历史/告警日志、导出、原子写、能量、live、清理 | 24h/72h 长稳 NOT RUN |
| `dashboard.py` | 91% | HTTP 端点、Host/CSP、CSV/PNG、HEAD、错误码、浏览器交互 | 真实桌面浏览器矩阵 NOT RUN |
| `config.py` | 92% | INI、优先级、边界/非法值、未知项 | 无 |
| `alerts.py` | 97% | 去抖、边沿、retain、pin 镜像 | 真实 E1h 故障注入 BLOCKED |
| `demo.py` | 98% | 5 机型合成数据 | 仅合成数据 |

## 功能状态

| 类别 | 状态 |
|---|---|
| CLI/配置/状态/daemon/dashboard 软件行为 | PASS（645 tests） |
| 打包/安装（用户命名空间）/CI release | PASS（本地 + GitHub Actions） |
| 真实 PSU 读取/告警/写入 | BLOCKED（无样机） |
| root/systemd/udev 实际启停 | PARTIAL/BLOCKED |
| arm64 运行 | BLOCKED（CI build PASS） |
| 24h/72h 长稳 | NOT RUN（20k 加速长稳 PASS） |
| 真实桌面浏览器 | NOT RUN（headless PASS） |

## 已知限制

- 覆盖率百分比不等于无 Bug；未覆盖行主要是防御性/错误分支和硬件异常路径。
- 所有 mock/stub 测试不能证明真实 HID 设备行为。
- 真实 OCP/OTP/OVP 等故障注入需要安全条件和样机，未执行。
- CI release 已发布 v1.0.0，但 arm64 产物未在 arm64 上运行。
