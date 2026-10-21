# 测试覆盖与限制（Test Coverage）

> 本文件只写**本轮实际跑过**的结论；没有真机/浏览器环境的项目明确标 NOT RUN / BLOCKED。

- 自动化测试：**736 passed**。实际执行环境：venv Python 3.12.3；另在裸 Python
  3.13.15（uv 缓存解释器，只装 pytest、不装本包）复跑 **736 passed**。本机没有
  python3.10，3.10 兼容性由 ruff `target-version = "py310"`、mypy
  `python_version = "3.10"`、smoke 的 `ast.parse(feature_version=(3, 10))`
  静态兜底；CI 矩阵仍配置 3.10 / 3.12 / 3.13。
- 覆盖率：**93%**（branch；2957 stmts / 195 missed / 1084 branches，floor 90%）。
- smoke：**58 passed / 0 failed**（demo，无硬件）。
- 加速 soak：`scripts/soak.sh 5000` → SOAK PASS（峰值 RSS 16.4 MB，fd=3）；
  本地 50k 采样长跑 exit 0。
- 硬件 kit demo acceptance：**30 PASS / 0 FAIL / 3 MANUAL / 2 SKIP**；MANUAL 项不算 PASS。
- 浏览器：真实桌面浏览器/Playwright **NOT RUN**（headless Chromium 缺系统库，本机无法启动）；
  dashboard 的 JS 用 Node DOM-stub 验证页面/图表叠加，不能替代真实浏览器验收。

## 源码模块覆盖（`coverage report` 本轮数字）

| 模块 | 语句/分支覆盖 | 主要已验证行为 | 未验证/限制 |
|---|---|---|---|
| `protocol.py` | 92% | HID 帧、NAK、LINEAR11、机型分发、传感器、风扇/黑盒/OCP/告警解析、0xC0 阈值写编码（mock 帧） | 真实 PSU/固件差异 BLOCKED |
| `monitor.py` | 93% | 全部 CLI 模式、输出格式、告警退出码、OCP 阈值写/导出/导入、写入 read-back（stub） | 真实写入/真机语义 BLOCKED |
| `daemon.py` | 90% | 采样、prom/history/latest、失败重扫、fan restore、阈值告警（stub） | 真实硬件 systemd 长跑 BLOCKED |
| `state.py` | 93% | 历史/告警日志、导出、原子写、能量、live、清理 | 24h/72h 长稳 NOT RUN |
| `dashboard.py` | 91% | HTTP 端点、Host/CSP、CSV/PNG、HEAD、错误码、Node 下图表交互 | 真实桌面浏览器矩阵 NOT RUN |
| `config.py` | 93% | INI、优先级、边界/非法值（含 nan/inf）、未知项、阈值 | 无 |
| `alerts.py` | 96% | 去抖、边沿、retain、pin 镜像、本地阈值 | 真实 E1h 故障注入 BLOCKED |
| `demo.py` | 96% | 5 机型合成数据、OCP 阈值读写 | 仅合成数据 |

## 功能状态

| 类别 | 状态 |
|---|---|
| CLI/配置/状态/daemon/dashboard 软件行为 | PASS（736 tests） |
| 打包/安装（用户命名空间）/CI release 脚本 | PASS（本地 + CI workflow 静态检查） |
| 真实 PSU 读取/告警/写入 | BLOCKED（无样机） |
| OCP 阈值真实写入与断电保持 | BLOCKED（仅 demo/mock；不得标 PASS） |
| root/systemd/udev 实际启停 | PARTIAL/BLOCKED |
| arm64 运行 | BLOCKED（CI build 配置存在，未在 arm64 执行） |
| 24h/72h 长稳 | NOT RUN（5k CI soak + 50k 本地加速长跑 PASS） |
| 真实桌面浏览器 | NOT RUN（Node DOM-stub 替代） |
| 官方 promtool 校验 | NOT RUN（无工具/网络；严格 exposition 解析作为本机替代） |

## 已知限制

- 覆盖率百分比不等于无 Bug；未覆盖行主要是防御性/错误分支和硬件异常路径。
- 所有 mock/stub 测试不能证明真实 HID 设备行为。
- 真实 OCP/OTP/OVP 故障注入、OCP 保护点写入需要安全条件和样机，未执行。
- CI 已发布 v1.0.0，但该版本来自更早的提交；本轮改动未提交/未发布，arm64 产物也未在
  arm64 上运行。
