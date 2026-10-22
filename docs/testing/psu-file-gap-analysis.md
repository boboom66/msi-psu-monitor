# psu-file 需求资料 vs 当前实现：差距与缺陷对比（2026-10-19，2026-10-22 更新）

## 0. 方法与范围

对比基准（只读，不修改）：

| 来源 | 路径 | 用途 |
|---|---|---|
| 文件索引 / 冻结缺口清单 | `psu-file/README_文件索引.md`、`psu-file/msi-psu-monitor-missing-features.md` | 冻结范围口径 |
| 定稿需求（DocMost m00066） | `psu-file/01_需求文档/需求分析.md` | 一期/二期/不做的最终口径 |
| CLI 手册 | `psu-file/01_需求文档/CLI-输入参数与输出格式.md` | 参数、退出码、三种输出样例 |
| 技术评估（差距矩阵） | `psu-file/01_需求文档/技术评估-msi-psu-monitor对比Msi-Center.md`（F-01..F-22） | 逐项差距与处置 T-01..T-22 |
| 需求改动清单（草案） | `psu-file/01_需求文档/PSU-7ZPU-需求分析与技术评估.md`（REQ-1..REQ-19） | 草案条目，区分"冻结/未冻结" |
| 官方规格 | `02_官方规格/CWT_MSI_..._REV6.pdf`、`MPG-Ai1300TS-PCIE5.pdf` | 寄存器与产品能力 |
| 参考实现 | `03_参考实现/msi-psu-monitor`（上游 v1.0.0）、`msi-psu-jackdoan/msi-psu.c` | 行为/NAK/边界对照 |
| MSI Center 源码 | `04_MSI-Center源码/Msi-Center/Power Supply Unit/.../CPSU.cs`、`C_PSU.cs` | 真实行为基准（E2） |
| 实屏 | `05_截图/images/01..10` | 总览/曲线/导出/风扇：UI 语义 |

当前实现：本仓库 HEAD `124de81`（工作树 clean；803 tests，覆盖率 94%，smoke 58/58），详见
[bug-audit/TEST_REPORT.md](../../bug-audit/TEST_REPORT.md)。

## 1. 结论摘要

1. **冻结范围内没有发现"整块功能缺失"**。定稿需求
   （`需求分析.md`）与技术评估矩阵里的一期功能全部有实现和测试；
   新增的 `--ocp`/`--set-rail`/`--zero-fan`/`--buzzer-off`/`--show-alert-log`
   等也都在 CLI 手册的扩展范围内。
2. **草案条目分两种情况**：
   - 本地阈值/告警（power/temp/pin/imbalance/connector/rails）已在本轮补齐（FEAT-01），
     不再是缺口；
   - 桌面通知（用户 2026-10-19 明确不做）、`promtool` 自检（无工具）、udev 固定
     软链与完整命令级重试仍未做（见 §5）；OCP 阈值写/dump/load 与初始化握手退避已按
     用户要求补齐（FEAT-03），但保护写仍需真机 bench 验收后才能放行。
3. **本轮对比发现 4 个真实缺陷并已修复**（DEF-032..035）：蜂鸣器把"开关 toggle"
   误报成"已静音"、`--set-rail` 同值仍写、Dashboard 7 张曲线构成与 MSI 不一致、
   MEG 序列号按整包读取而非 MSI 的固定 24 字节。
4. **发布阻塞项没变**：真实 PSU 验收、arm64 运行、真实 root/systemd/udev、
   桌面浏览器、24h/72h 仍未验证（硬件到货后按
   [hardware-acceptance.md](../hardware-acceptance.md) 执行）。

## 2. 技术评估矩阵 F-01..F-22 复核

状态：✅ 已实现且有自动化验证；🧪 已实现待真机；🟡 部分；⏸ 明确冻结/不做；
❌ 未实现（草案，未冻结）。

| ID | 条目 | 当前状态 | 证据 / 说明 |
|---|---|---|---|
| F-01 | FW 2 字节 ASCII + 补小数点 | ✅ | `protocol.MSIPSU.init()`；`test_fw_revision_*` |
| F-02 | 序列号按长度/固定长度解析 | ✅（本轮补 MEG 24B） | TS 长度前缀、MEG 固定 24B（`CPSU.cs:515-528`）；DEF-035 |
| F-03 | 补 AA6F 等 5 个 PID | ✅ | `PSU_PRODUCT_IDS`/`VARIANTS`/udev/install/README 五处交叉测试 |
| F-04 | 未知机型拒解（ident + exit 1） | ✅ | `get_sensors()` 的 variant 门 + payload 门 |
| F-05 | E1h 状态行 + exit 2 + 连续判定 | ✅ | E1h 按机型索引 + 软件镜像 + debounce；daemon 默认 2 次 |
| F-06 | AVG 功率/效率 | ✅ | `MonitorState` 累计平均，落盘 |
| F-07 | kWh 积分 + uptime | ✅ | `wh += watts*dt/3600`，30 天日桶 |
| F-08 | `--export --from --columns` 9 列 | ✅ | cpu/gpu/12v/5v/3v3/temp/fan/eff；TS 上 CPU/GPU=N/A |
| F-09 | `--show-log` 黑盒 10 条新→旧 | ✅（格式待真机） | C1h InfoID 1..10；MSI Center 本身不读该日志，格式是本项目定义 |
| F-10 | 桌面通知 / `--notify desktop` | ⏸ 不做 | 定稿与冻结清单均写"告警只走 stderr + exit 2" |
| F-11 | .deb + udev + arm64 | ✅（arm64 仅构建） | 源 .deb + 自包含 tar/deb；arm64 产物 CI 构建，未执行 |
| F-12 | 单 daemon + 原子写 | ✅ | 旧 timer 已删除；`.tmp+fsync+os.replace` |
| F-13 | 风扇/Zero Fan 只读 | ✅ | 41h/42h 四元组 |
| F-14 | 风扇写 + F1h + 读回 | ✅（待真机） | 用户 2026-10-16 把风扇写提前到一期 |
| F-15 | 单多轨只读/切换 | ✅（只读+写都做了） | `--ocp` 读 `==2`；`--set-rail` 写 2/1 + F1h + 读回 |
| F-16 | OCP 阈值写 | ✅（待真机 bench） | `--ocp-set`/`--load-thresholds` 写 8B + F1h 并读回（3 次），`--dump-thresholds` 只读导出；范围硬校验、不 clamp、不支援机型 exit 1；demo/mock 全链路测试，真机保护写仍未验 |
| F-17 | flock + 5 次失败重扫 | ✅ | `flock`、daemon 5 次失败重扫已做；初始化握手按草案补了 3 次 + 0.5/1.0s 指数退避（`HANDSHAKE_RETRY_DELAYS`），采样失败仍走 5 次重扫（不对每个读做 3 次重试，避免阻塞 1s 采样） |
| F-18 | `--watch` 秒数合一/去清屏 | ✅ | `--watch 1`、`-i` 兼容；仅 TTY 清屏，管道不被破坏 |
| F-19 | 针序/5s 平均/效率源标注 | ✅ | CLI `--help` 已注明 5s 平均、EFF 来自 0xE0 offset 32、Conn1/Conn2 针 1-6；TS 针到 12V3/12V5 的具体映射仍缺权威证据（U-07 剩余） |
| F-20 | 多电源 `--serial` | ✅ | 扫全部 hidraw、列序列号、找不到打印可用列表 |
| F-21 | protocol 文档补 E1/C1/C0 | ✅ | `docs/protocol.md` 已含 NAK/0xE0/0xE1/0xC0/0xC1/F1 章节 |
| F-22 | HID mock 单测 + 72h 烤机 | 🟡 | mock/负向/短帧单测充分；72h 需真机（BLOCKED） |

## 3. 草案 REQ-1..REQ-19 复核

| REQ | 主题 | 状态 | 说明 |
|---|---|---|---|
| REQ-1 | 底座四款全保、字段冻结 | ✅ | 5 机型（含 AA6F/7ZPU）均解析；字段与三格式冻结 |
| REQ-2 | 一期 .deb，不内嵌 Python | ✅（口径已升级） | 当前同时提供开发源 .deb 与官方自包含 tar/deb；官网零 Python 依赖 |
| REQ-3 | PVE7 / Python 3.9 去留 | ⏸ 放弃 | `requires-python >=3.10`，最终冻结明确放弃 PVE7 |
| REQ-4 | 多发行版 binary 验证 | 🟡 | 22.04 本地 chroot + CI runner 实测；24.04/26.04/Fedora/PVE8 未跑 |
| REQ-5 | CLI 清单冻结 | ✅ | 清单全部有；另有 `--ocp/--zero-fan/--buzzer-off/--show-alert-log/--no-alerts/--config` 扩展 |
| REQ-6 | `--watch [秒]` 合一 | ✅ | 无值用 `[monitor] interval`（默认 2s）；`-i` 兼容 |
| REQ-7 | AVG + Status 行 | ✅ | json 字段名为 `power_avg/efficiency_avg`（CLI 手册口径），另有 `status` |
| REQ-8 | kWh 落盘 + Weekly | ✅ | 积分落 `state.json`/日桶；Weekly 由 dashboard 画（未用 recording rule，效果等价） |
| REQ-9 | `--export` 9 列 | ✅ | 见 F-08；CPU/GPU 语义按 MSI P 系（12V2 / 12V3+4+5），TS=N/A |
| REQ-10 | 风扇显示 + 写控制 | ✅ | 41h/42h/43h/F1h；钳制由电源执行；读回验证 |
| REQ-11 | 单多轨切换（二期） | ✅（提前） | `--set-rail` 已实现；本轮补"先读回、同值不写"（DEF-033） |
| REQ-12 | OCP 阈值只读展示；写/备份恢复 | 🟡 | `--ocp` 只读完整；8B 写与 `--dump/--load-thresholds` 未做（写已冻结，dump/load 未冻结待定） |
| REQ-13 | 单 daemon 快路（1s 判定、syslog、exit 2 语义） | ✅ | 单 daemon、1s 判警、journald(stderr)、Prometheus；本地阈值已实现（`[alerts]`，见 FEAT-01），告警边沿/恢复写 `alerts-*.log`；桌面通知按用户确认不做 |
| REQ-14 | 阈值初值（12V 总量/单口/温度/单针/风扇） | ✅ | 12V/5V/3.3V 轨电流、单针 12A、针差 5A、连接器 50A、功率 1200W、温度 70℃ 全部可配（默认即初值）；风扇/OPP/OTP 由 E1h 硬件位覆盖，不再做软件 fan 阈值（Zero Fan 下 0 RPM 为正常态） |
| REQ-15 | EPS 数量外部确认 | N/A | 代码不建模 EPS 数量，回函前无写死值 |
| REQ-16 | textfile 运维 + 告警规则 + promtool 自检 | 🟡 | 原子写/644/3 条交付已做；`docs/prometheus-rules.yml` 已随包；以 `tests/test_prometheus_exposition.py` 严格解析替代 promtool（本机无 promtool/网络）；`--exporter` 二期未做 |
| REQ-17 | 多电源 `--serial` | ✅ | 见 F-20 |
| REQ-18 | 睡眠/断线重握手与抢占 | 🟡 | `flock LOCK_NB`、失败重扫+重 INIT 已做；250ms×3 重试+指数退避、udev 按序列号固定软链未做（现有 sysfs 扫描不受 hidraw 号漂移影响） |
| REQ-19 | 真机 72h 验收 | ⏸ BLOCKED | 无样机；kit 已就绪 |

## 4. 明确冻结 / 不做（不是缺陷）

| 项 | 出处 | 说明 |
|---|---|---|
| OCP 阈值写（0xC0 8B + F1h） | 需求分析/技术评估 F-16 | ✅ 已实现 `--ocp-set`/`--load-thresholds`（读回 + 范围校验 + 同值不写）；保护写仅 demo/mock 验证，待真机 bench |
| 桌面弹窗/通知 | 需求分析、群聊记录 | 只保留 stderr + exit 2；批量走 Prometheus |
| 显卡功耗联动下调 | 需求分析 | 调不到显卡，只对齐触发条件 |
| timer 方案 | 冻结 D-02 | 改为单 daemon |
| kernel 模块路径 | 需求分析、REQ-1 | `kernel/msi-psu-ai1600ts.patch` 是草稿且不可构建，用户态为唯一支持路径 |
| PVE7 / Python 3.9 | REQ-3 | 放弃 |

## 5. 需求决策/外部验证项（原“未冻结但未实现”）

| ID | 项 | 来源 | 现状 / 建议 |
|---|---|---|---|
| U-02 | `--dump-thresholds` / `--load-thresholds` | 草案 REQ-12 | ✅ 已实现：`--dump-thresholds`（text/JSON）、`--ocp-set`、`--load-thresholds`（接受 dump JSON 的 `ocp_config` 或扁平对象）；读回验证与范围硬校验 |
| U-03 | `--notify desktop`（notify-send opt-in） | 技术评估 F-10 | **用户确认不需要（2026-10-19）**：告警只保留 stderr + exit 2 / Prometheus，不做桌面通知 |
| U-04 | `promtool check metrics` 自检 + Prometheus 告警规则文件 | 草案 REQ-16 | ✅ 规则文件已交付并随包；✅ `tests/test_prometheus_exposition.py` 严格解析我们的 exposition（HELP/TYPE、label 转义、数值、重复序列、规范 `metric{} value`）。promtool 2.45.3 的结果记录在 `psu-file/msi-psu-monitor-项目信息汇总.md`（2026-10-21，外部证据，本轮未重跑）：语法通过，9 条命名规范告警待决策 |
| U-05 | 命令级 3 次重试 + 0.5/1/2s 退避；udev 按序列号固定软链 | 草案 REQ-18 | 🟡 初始化握手已补 3 次 + 0.5/1.0s 退避；采样读不做逐命令 3 次重试（会拖慢 1s 循环，daemon 已有 5 次失败重扫）；按序列号的 udev 软链仍不做——多电源会冲突，且 sysfs 发现不依赖 hidraw 号 |
| U-06 | 电量 counter 名 | 草案 REQ-8 用 `msi_psu_energy_kwh_total`；实现用 `msi_psu_total_energy_kwh`（TYPE counter） | ✅ 已同时导出两个名字（同一 counter 值），按草案或按描述名写的 recording rule 都能用 |
| U-07 | F-19：CLI `--help` 注明针序与 12V3/12V5 对应关系 | 技术评估 T-19 | ✅ 5s 平均、EFF 源（0xE0 offset 32）、Conn1/Conn2 针 1-6 已写进 `--help` epilog；针到 12V3/12V5 的具体映射仍缺权威证据，需真机/原厂确认后补 |
| U-08 | REQ-4 多发行版矩阵（24.04/26.04/Fedora/PVE8） | 草案 REQ-4 | 未跑；当前只保证 22.04 构建 + CI x86_64，其它系统标 NOT RUN |

### 5.1 本轮已补齐：U-01 本地阈值/告警

原 `thresholds.yaml` 草案已改为 INI `[alerts]`（stdlib-only 无 YAML 依赖）：
`power_w / temp_c / pin_max_a / pin_imbalance_a / connector_a / rail_12v_a / rail_5v_a /
rail_3v3_a`，0 关闭；默认值即 REQ-14 初值。阈值告警与 E1h 告警共用引擎/去抖/
stderr+exit 2/`alerts-*.log`，但名字独立（`power_high`/`temp_high`/`rail_*_high`/
`connector*_high`），不污染 12V-2x6 Status；JSON 暴露 `threshold_alerts`/
`threshold_limits`，Prometheus 暴露 `msi_psu_threshold_alert`/
`msi_psu_threshold_limit`。0xE0 读失败不清除已 latched 阈值告警。
验证：`test_alerts.py`（阈值/禁用/缺读数/连接器/可配置 pin）、`test_config.py`
（默认/覆盖/负值/坏值）、`test_cli_features.py`（exit 2、text/json/prom、--no-alerts）、
`test_daemon.py`（日志/prom/恢复/payload 失败）。

## 6. 本轮新发现并修复的缺陷（对比 psu-file 参考资料）

| ID | 严重度 | 问题 | 参考资料 | 修复 | 回归 |
|---|---|---|---|---|---|
| DEF-032 | P2 | `--buzzer-off` 输出/文档宣称 "Buzzer: silenced"，但 C2h 是无参数、无回读的 **toggle**；第二次执行会重新打开蜂鸣，用户却以为已静音 | `CPSU.cs:1148-1159`（`BUZZER_SWITCH`，无 payload、无读回）；`verify.md` §8.11 早已标注"switch 还是静音待确认" | 输出改为 `Buzzer: switch toggled (no read-back)`，帮助/审计行/README/协议文档统一为"开关切换、不宣称静音"；行为仍只发一次 C2h | `test_buzzer_off_writes_and_reports_the_switch`、audit 断言、smoke 期望同步 |
| DEF-033 | P2 | `--set-rail` 即使当前已是目标模式也会写 + F1h 保存；草案 REQ-11 明确"发前先读回，值一致直接返回（硬件同值会报错）"，且每次幂等调用都消耗一次 flash 保存 | `PSU-7ZPU-需求分析与技术评估.md` REQ-11 | `apply_rail_mode()` 先读 `read_multirail_ocp()`，一致则直接返回 `(mode, changed=False)`；输出 `Rail mode: multi (already set)`，审计行带 `changed=` | `test_set_rail_is_a_noop_when_already_in_the_requested_mode`；原写入/读回失败用例保持 |
| DEF-034 | P3 | Dashboard 的"7 张实时曲线"实际是 12V/5V/3.3V/12V 总电流/温度/风扇/功率(含效率)，缺独立效率曲线，且 12V 总电流不在 MSI 的 7 张里 | `技术评估-msi-psu-monitor对比Msi-Center.md` §2（温度/12V/5V/3.3V/风扇/效率/瓦数 CPU/GPU/Total）；实屏 02 | CHARTS 改为 12V/5V/3.3V/efficiency/temperature/fan/power(CPU/GPU/Total)；12V 总电流仍进历史/导出/Prometheus | `test_the_seven_charts_match_the_msi_dashboard`（含 id 顺序与功率卡不含 eff 断言）；Node live harness |
| DEF-035 | P3 | MEG 机型序列号取 0x13 整包，依赖 24 字节后的报告全为 0；参考实现固定读 24 字节 | `CPSU.cs:515-523`（MEG 固定 24）；`CPSU.cs:525-528`（TS 长度前缀） | `init()` 按机型分支：MPG TS 长度前缀、MEG 固定 24 字节、未知机型保留旧启发式 | `test_a_meg_serial_is_cut_to_the_msi_fixed_length`；TS 长度前缀/legacy/64 字节上限用例保持 |
| FEAT-01 | — | 本地阈值/告警补齐（原 U-01、REQ-13/14 草案） | REQ-13/14、J-01..J-03 | `[alerts]` 8 个可配极限；统一 AlertEngine（去抖/exit 2/审计日志）；文本 Thresholds 行、JSON `threshold_alerts/limits`、Prometheus `msi_psu_threshold_*`；payload 失败不清 latched | `test_alerts.py` 6 例、`test_config.py` 4 例、`test_cli_features.py` 5 例、`test_daemon.py` 3 例 |
| FEAT-04 | — | 可靠性/发布收口：soak 门禁、fuzz、多轨 formatter、CHANGELOG、裸 3.13 复核 | QUAL-01..03 | `scripts/soak.sh` 进 CI（5k）、确定性 fuzz、多轨 formatter 测试、CHANGELOG 随所有包、Python 3.13.15/3.10.21 裸跑 803 passed | `test_soak.py` 3 例、`test_robustness.py` 3 例、`test_monitor_format.py` 3 例、`test_packaging.py` |
| FEAT-03 | — | 硬件 OCP 阈值写/导出/导入 + 握手退避 + promtool 替代 | REQ-12/16/18、F-16/F-17 | `--dump-thresholds`/JSON、`--ocp-set`、`--load-thresholds`（8B + F1h + 读回 3 次；范围硬校验；同值不写；机型门）；初始化握手 3 次退避；严格 exposition 测试替代 promtool | `test_ocp.py` 5 例、`test_cli_features.py` 14 例、`test_psu_sensors.py` 2 例、`test_prometheus_exposition.py` 4 例；保护写仍待真机 bench |
| FEAT-02 | — | 运维/CLI 打磨（U-04、U-06、U-07、F-19） | REQ-8/16、F-19 | Prometheus 规范 exposition（`metric{} value`，无空格）、电量 counter 双名、`docs/prometheus-rules.yml` 随包、`--dump-config`（text/json，无 PSU 也可打印生效阈值）、`--help` 注明 5s 平均/EFF 源/针序、阈值告警带 measured/limit 明细 | `test_cli_features.py`（dump-config/alias/描述）、`test_packaging.py`（规则随包）、`test_monitor_format.py` |

修复后：**803 passed**、ruff/format/mypy clean、coverage **94%**、smoke **58/58**。

## 7. 与上游参考实现的差异

- 上游 v1.0.0（`03_参考实现/msi-psu-monitor`）只有 `--once/-w/-i/-f/-O` 和 timer 方案；
  当前分支是其**严格超集**：daemon、告警/黑盒/OCP/风扇/ZeroFan/buzzer/rail、
  历史导出、dashboard、demo、自包含发布、CJK 文档均新增；没有发现上游有而当前丢失的 CLI 功能。
- 上游的 `systemd timer` 被冻结为单 daemon；上游 `kernel` 补丁仍保留为草稿且明确不可构建。
- 参考工具 `msi-psu-jackdoan` 只覆盖 Ai1300P/Ai1000P，且 NAK 语义（`[cmd,NAK]` /
  `[cmd,reg,NAK]`）与当前 `protocol.send_command` 一致，是本次复核 NAK 实现的依据。

## 8. 建议的下一步

1. 样机到位：按 [hardware-acceptance.md](../hardware-acceptance.md) 跑 kit，重点验证
   §2 状态行 / §5 OCP / §10-11 风扇/ZeroFan/buzzer（含"第二次 toggle"行为）/
   §12-13 set-rail 幂等与 OCP 行为。
2. 真机 bench：OCP 阈值写必须先在样机上导出原值、写入、断电保持验证，再恢复；
   默认值/阈值/保护点都按真实负载校准。U-07 只剩 TS 针到 12V3/12V5 的映射。
   U-04 的 promtool 自检需有工具的环境补跑；U-05 的 udev 序列号软链经评估不做。
3. 发布：本轮修复已提交（`cf57e8d`/`e57bd44`/`2076d3f`/`124de81`）但未打 tag/发布；确认后 bump 版本、走新 CI release，并补 arm64 运行、
   真实 systemd/udev、桌面浏览器、24h/72h。
