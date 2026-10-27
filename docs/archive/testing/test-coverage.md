# 测试覆盖与限制（历史快照：2026-10-22）

> 本文件只写**本轮实际跑过**的结论；没有真机/浏览器环境的项目明确标 NOT RUN / BLOCKED。
> 本轮统计已冻结；当前 CI 测试和发布状态见 [`bug-audit/RELEASE_READINESS.md`](../../../bug-audit/RELEASE_READINESS.md)。

- 自动化测试：**803 passed**（2026-10-22 全项目审计后）。实际执行环境：当前 venv
  Python 3.10.21、Python 3.12.3、裸 Python 3.13.15 各 **803 passed**；CI 矩阵仍配置
  3.10 / 3.12 / 3.13。
- 覆盖率：**94%**（branch；3166 stmts / 183 missed / 1174 branches，floor 90%）。
- smoke：**58 passed / 0 failed**（demo，无硬件）。
- 加速 soak：`scripts/soak.sh 5000` → SOAK PASS（峰值 RSS 18 436 KB，fd=3）；
  本地 50k 采样长跑 exit 0。
- 真实节奏 demo：180 samples at 1 s → exit 0，峰值 RSS 18 000 KB，fd=3，state 16 KiB。
- 硬件 kit demo acceptance：**30 PASS / 0 FAIL / 3 MANUAL / 2 SKIP**；MANUAL 项不算 PASS。
- 官方 promtool 2.45.3（当前 1.0.1 daemon textfile）：metrics **exit 3**，8 条命名规范
  告警、**无语法错误**；`check rules docs/prometheus-rules.yml` → SUCCESS（5 rules）。
- 浏览器：真实桌面浏览器/Playwright **NOT RUN**（headless Chromium 缺系统库，本机无法启动）；
  dashboard 的 JS 用 Node DOM-stub 验证页面/图表叠加，不能替代真实浏览器验收。

## 源码模块覆盖（`coverage report` 本轮数字）

| 模块 | 语句/分支覆盖 | 主要已验证行为 | 未验证/限制 |
|---|---|---|---|
| `protocol.py` | 96% | HID 帧、NAK、LINEAR11、机型分发、传感器、风扇/黑盒/OCP/告警解析、0xC0 阈值写编码（mock 帧） | 真实 PSU/固件差异 BLOCKED |
| `monitor.py` | 94% | 全部 CLI 模式、输出格式、告警退出码、OCP 阈值写/导出/导入、写入 read-back（stub） | 真实写入/真机语义 BLOCKED |
| `daemon.py` | 90% | 采样、prom/history/latest、失败重扫、fan restore、阈值告警（stub） | 真实硬件 systemd 长跑 BLOCKED |
| `state.py` | 92% | 历史/告警日志、导出、原子写、能量、live、清理 | 24h/72h 长稳 NOT RUN |
| `dashboard.py` | 95% | HTTP 端点、Host/CSP、CSV/PNG、HEAD、错误码、Node 下图表交互 | 真实桌面浏览器矩阵 NOT RUN |
| `config.py` | 94% | INI、优先级、边界/非法值（含 nan/inf）、未知项、阈值 | 无 |
| `alerts.py` | 97% | 去抖、边沿、retain、pin 镜像、本地阈值 | 真实 E1h 故障注入 BLOCKED |
| `demo.py` | 96% | 5 机型合成数据、OCP 阈值读写 | 仅合成数据 |

## 功能状态

| 类别 | 状态 |
|---|---|
| CLI/配置/状态/daemon/dashboard 软件行为 | PASS（803 tests） |
| 打包/安装（用户命名空间）/CI release 脚本 | PASS（本地 + CI workflow 静态检查） |
| 真实 PSU 读取/告警/写入 | BLOCKED（无样机） |
| OCP 阈值真实写入与断电保持 | BLOCKED（仅 demo/mock；不得标 PASS） |
| root/systemd/udev 实际启停 | PARTIAL/BLOCKED |
| arm64 运行 | BLOCKED（CI build 配置存在，未在 arm64 执行） |
| 24h/72h 长稳 | NOT RUN（5k CI soak + 50k 加速长跑 + 180 s 真实节奏 PASS） |
| 真实桌面浏览器 | NOT RUN（Node DOM-stub 替代） |
| 官方 promtool 校验 | RUN（metrics 语法通过、8 条命名告警；rules 5 条成功） |

## 已知限制

- 覆盖率百分比不等于无 Bug；未覆盖行主要是防御性/错误分支和硬件异常路径。
- 所有 mock/stub 测试不能证明真实 HID 设备行为。
- 真实 OCP/OTP/OVP 故障注入、OCP 保护点写入需要安全条件和样机，未执行。
- CI 已发布 v1.0.0；当前修复已提交，并已生成 x86_64/glibc 2.39 的本地 1.0.1
  tar/deb/kit（仅 smoke），但尚未打 v1.0.1 tag/发布；arm64 产物也未在 arm64 上运行。
