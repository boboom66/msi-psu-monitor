# Ai1300TS 严格测试报告（历史快照）

> **历史快照（2026-10-19/21）**。本文结果只代表当时的 demo 测试；当前发布状态见 [`bug-audit/RELEASE_READINESS.md`](../../bug-audit/RELEASE_READINESS.md)。

- 日期：2026-10-21
- 对象：MSI MPG Ai1300TS，USB PID 0xAA6F，内部 variant mpg_ai1300ts
- 环境：Ubuntu 24.04 WSL2，Python 3.12.3，demo 模式（无真实 PSU）
- 结论：软件层功能覆盖通过；真实硬件行为仍 BLOCKED（无样机）

## 测试范围

覆盖 Ai1300TS 适用的全部功能：

- 机型识别、PID、身份信息、固件、序列号
- 12V/5V/3.3V、12V 总电流、每针 12 路电流、功率、效率、温度、风扇
- E1h 硬件告警、本地阈值告警、黑盒、告警日志
- OCP 阈值读取、文本/JSON/Prometheus 导出、8 字节写入、读回、从 JSON 恢复
- 风扇、Zero Fan、蜂鸣器
- daemon、state.json、latest.json、psu.prom、历史、CSV 导出、dashboard API
- PCIe 机型的固有限制：无 VIN、无五轨 CPU/GPU、无 MEG P 单多轨开关
- PID 在代码、udev、安装脚本、README 五处的一致性

## 执行结果

| 测试 | 结果 |
|---|---|
| 全量 pytest | **803 passed** |
| Ai1300TS 专项测试 | **5 passed** |
| Ai1300TS 相关模块（sensors/ocp/demo/PID/专项） | **216 passed** |
| 全量分支覆盖率 | **94%**（3166 stmts / 183 missed / 1174 branches） |
| 端到端检查矩阵 | **58 项通过，0 失败** |
| Ai1300TS 5k 采样 soak | **SOAK PASS**，峰值 RSS 16384 KB，fd=3，state dir 32K |
| dashboard API（Ai1300TS 数据） | /api/state 与 /api/live 返回正常 |
| 真实 Ai1300TS | **BLOCKED**（无样机） |

## 专项覆盖明细

- 机型识别：产品字符串精确匹配 MPG Ai1300TS，不会被通用 Ai1300 分支误判为 Ai1300P；截断成 MPG Ai1300T 时拒解。
- 读数：62 字节帧、44 字节数据区、12 针电流、合并 12V 轨、无 VIN/五轨字段。
- 告警：E1h 按 TS 位表解析；本地阈值独立命名；两者都走连续去抖、stderr、exit 2 和告警日志。
- OCP：C0h 8 字节配置支持读、JSON/Prometheus 导出、写入、读回、从 JSON 恢复、关闭 OCP；越界值在参数解析阶段 exit 2；不支持的 --set-rail 返回 1。
- 写入：风扇模式/占空比、Zero Fan、蜂鸣器均返回成功；蜂鸣器按无回读的 switch 语义输出。
- 系统链路：daemon 写出 state/latest/psu.prom/daily；Prometheus 文件含每针电流、OCP available、msi_psu_up；--export 输出 9 列 CSV；dashboard 能读到 Ai1300TS 的 state/live。
- 打包：PID 0xAA6F 同时出现在 PSU_PRODUCT_IDS、VARIANTS、udev 规则、install.sh、README；test_pid_consistency.py 全部通过。

## 复现命令

~~~bash
cd /home/timzhang/projects/project/msi-psu-monitor

# 全量
.venv/bin/python -m pytest -q

# Ai1300TS 专项
.venv/bin/python -m pytest -q tests/test_ai1300ts.py

# 相关模块
.venv/bin/python -m pytest -q \
  tests/test_ai1300ts.py tests/test_psu_sensors.py tests/test_ocp.py \
  tests/test_demo.py tests/test_pid_consistency.py

# demo 读数
MSI_PSU_DEMO=1 MSI_PSU_DEMO_MODEL=mpg_ai1300ts \
  .venv/bin/msi-psu-monitor --once

# OCP 读取/写入
MSI_PSU_DEMO=1 MSI_PSU_DEMO_MODEL=mpg_ai1300ts \
  .venv/bin/msi-psu-monitor --ocp
MSI_PSU_DEMO=1 MSI_PSU_DEMO_MODEL=mpg_ai1300ts \
  .venv/bin/msi-psu-monitor --ocp-set 13,6,10,12,60

# 5k 采样长跑
MSI_PSU_DEMO_MODEL=mpg_ai1300ts bash scripts/soak.sh 5000
~~~

## 未验证项

- 真实 Ai1300TS 的读数精度、每针电流、E1h 故障注入
- 真实 OCP 阈值写入、读回和断电保持
- 风扇/Zero Fan/蜂鸣器的实际动作
- 24h/72h 长稳、arm64、真实 root/systemd/udev、桌面浏览器

这些项目在 demo 中通过不等于真机 PASS；样机到位后按 [hardware-acceptance.md](../hardware-acceptance.md) 和 [verify.md](../verify.md) §8 执行。
