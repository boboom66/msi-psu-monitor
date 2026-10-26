# 需求溯源矩阵（`psu-file/01_需求文档/需求分析.md` → 代码 → 测试）

本文把需求文档的每一条落点写成「需求 → 实现位置 → 覆盖测试 → 无硬件验证命令 → 状态」，
供验收时逐条勾对。状态含义：

| 状态 | 含义 |
|------|------|
| ✅ 已实现 | 代码 + 测试 + 无硬件可验证 |
| 🧪 待真机 | 代码完成、单测覆盖，但结论必须样机复核（见 [`verify.md`](verify.md) §8） |
| 🟡 部分/待放行 | 软件链路已实现并测试，但关键动作仍需真机 bench 或产品决策后才能放行 |
| ⏸ 冻结 | 明确留待后续批准批次，本轮不做 |

> 回归命令：`uv run --group dev pytest -q` → **870 passed**（29 个测试模块）。
> 无硬件全链路自检见 [`verify.md`](verify.md)。

---

## 1. 与 MSI Center 一致的基础能力

| 需求 | 实现位置 | 测试 | 状态 |
|------|----------|------|------|
| PSU 自動發現（hidraw 掃描） | `protocol.detect_devices()`（sysfs `uevent` → `/dev/hidrawN`）、`monitor.resolve_device()` | `test_protocol_discovery.py`（真解析器 + 假 sysfs 樹）、`test_demo.py` | ✅ 已实现 |
| 多機型相容解析（不同資料長度） | `protocol.MSIPSU.VARIANTS[*]["payload_size"]` + `get_sensors()` | `test_psu_sensors.py`（62/40/20B + 拒解） | 🧪 待真机 |
| 廠商 / 型號 / 韌體 / 序號 | `protocol.MSIPSU.init()`（0x10/0x11/0x12/0x13，FW 為 2 位 ASCII 數字 + 讀取方補小數點、序號 TS 按首字節切片 / MEG 固定 24 字節，對齊 `CPSU.cs:515-528`） | `test_psu_sensors.py` | ✅ 已实现 |
| 雙 12V-2x6 每針電流（TS 專屬） | `get_sensors()` TS 分支（44 B 内联切片）→ `iout_pins` | `test_psu_sensors.py`、`test_monitor_format.py` | 🧪 待真机 |
| 直流三組電壓 / 電流 | `get_sensors()` → `vout_12v`/`vout_5v`/`vout_3v3`、`iout_*` | `test_psu_sensors.py` | 🧪 待真机 |
| 輸出功率 / 轉換效率 / 溫度 / 風扇轉速 | `get_sensors()`（0xE0 尾部 + 41h/42h） | `test_psu_sensors.py`、`test_monitor_format.py` | ✅ 已实现 |
| 本次 / 累計運行時間 | `get_sensors()` 读 `0xD0`/`0xD1`（= MSI Center 的 `Time_Daily`/`Time_Total`） | `test_psu_sensors.py` | ✅ 已实现 |
| AC 輸入電壓（MEG 機型，0x20，MSI `GET_VIN` 兼容） | `MSIPSU.read_vin()`、`format_text()` 的 `AC Input`、`format_prometheus()` 的 `msi_psu_input_voltage` | `test_psu_sensors.py`、`test_monitor_format.py` | 🧪 待真机（量程/有效值以實測為準） |
| 單次讀取（`--once`，預設） | `monitor.main()` → `run_once()` | `test_cli_features.py` | ✅ 已实现 |
| 持續重新整理（`--watch [秒]`，REQ-6 秒數合一） | `run_watch()`（无值默认 2 s，每帧 flush） | `test_cli_features.py` | ✅ 已实现 |

## 2. 本套件獨有能力

| 需求 | 实现位置 | 测试 | 状态 |
|------|----------|------|------|
| 純 CLI、標準庫-only 零第三方依賴 | 全包仅用 stdlib；`pyproject.toml` 无 `dependencies` | `test_stdlib_only.py`（`python -I` 子进程导入全部模块） | ✅ 已实现 |
| 人讀文字輸出 | `format_text()` | `test_monitor_format.py` | ✅ 已实现 |
| JSON 輸出 | `format_json()` | `test_monitor_format.py`、`test_schema.py` | ✅ 已实现 |
| Prometheus textfile（`msi_psu_` 前綴，per-pin 帶 connector/pin 標籤） | `format_prometheus()`（`msi_psu_pin_current{connector=,pin=}`、`msi_psu_rail_*{rail=}`；`msi_psu_up` 0/1 + `msi_psu_error_info{reason=}` 讓「沒讀到」不會看起來像健康）；daemon 每個 prom 週期附上 OCP 塊（`format_ocp_prometheus()`；不支援的機型出 `msi_psu_ocp_available 0`） | `test_monitor_format.py`、`test_schema.py`、`test_cli_features.py`、`test_daemon.py` | ✅ 已实现 |
| 輸出重導向到檔案（三格式皆可） | `-O/--output` + `emit()` | `test_cli_features.py` | ✅ 已实现 |
| 單常駐 daemon（替代 timer） | `daemon.MonitorDaemon`（flock 獨占、1 s 判警、30 s 原子寫 prom、60 s 追加 history、1 h 輪轉） | `test_daemon.py` | ✅ 已实现 |
| Linux 維運鏈路（node_exporter → Prometheus → Grafana；告警走 stderr + exit 2） | `write_prometheus()`、`alerts.format_alert_line()` | `test_daemon.py`、`test_alerts.py`、`test_cli_alerts.py` | ✅ 已实现 |
| 告警審計檔案（MSI AlertLog 等價：`alerts-YYYYMMDD.log`，5 MiB 輪轉、30 天清理、`--show-alert-log`） | `state.append_alert_log()` / `iter_alert_log()` / `prune_alert_logs()`、`daemon._record_alerts()`、`monitor.run_show_alert_log()` | `test_state.py`、`test_daemon.py`、`test_cli_features.py` | ✅ 已实现 |
| 官方分发：自包含 tar.gz + 零 Python 依赖 `.deb`（x86_64/arm64） | `scripts/build_binary.sh` / `scripts/build_deb_binary.sh`（PyInstaller onefile，构建基线 Ubuntu 22.04 / glibc 2.35） | CI `freeze` job + `tests/test_packaging.py` | ✅ 已实现（待真机安装验证） |
| 变更控制：01 文档曾冻结「源码 `.deb` 依赖 python3、不内嵌 Python」；用户 2026-10-19 明确要求官网下载**目标机不装 Python**，故官方产物改为自包含二进制 + 零 Python `.deb`，源码 `.deb` 仅保留为开发/CI 用途 | `scripts/build_binary.sh`、`scripts/build_deb_binary.sh`、`docs/release.md` | `tests/test_packaging.py` 断言 `Depends` 无 python | ✅ 已按新需求覆盖旧冻结 |
| 供应链与安全：SBOM、SECURITY/CVD、支持周期、应急 runbook | `scripts/build_sbom.py`、`SECURITY.md`、`docs/support.md`、`docs/incident-response.md`；release workflow 生成并上传 `SBOM-<arch>.json` | `tests/test_release_security.py` | ✅ 已实现（GPG 签名待定） |
| 开发/CI 源码 `.deb`（`Depends: python3 >= 3.10`，非官网下载） | `scripts/build_deb.sh`（含 postinst/prerm、systemd unit、udev rule、doc） | CI 步骤 `Build the .deb` | ✅ 仅开发 |
| 桌面彈窗 / 顯卡功耗連動下調 | — | — | ⏸ 明确不做 |

## 3. 一期功能（已凍結，全做）

### 3.1 狀態與告警顯示

| 需求 | 实现位置 | 测试 | 状态 |
|------|----------|------|------|
| 12V-2x6 狀態列（Normal / 告警名；閾值單針 12 A、針差 5 A） | `alerts.evaluate_pin_alerts()`、`monitor.status_from()` | `test_alerts.py` | ✅ 已实现 |
| E1h 告警位图按机型解名（MPG TS / MEG P / MEG Ai1600T 三套字节序） | `protocol.ALERT_INDEXES`、`MSIPSU.alert_names` | `test_psu_sensors.py`（对照 `CPSU.cs` 三张索引数组） | ✅ 已实现 |
| 告警結束碼與連續判定（0/2/1，連續 2 次才算） | `alerts.AlertEngine(consecutive_required=2)`、`EXIT_ALERT=2` | `test_alerts.py`、`test_cli_alerts.py` | ✅ 已实现 |
| 黑盒最近 10 條（`--show-log`，新到舊，空提示；与 `-f/--watch/--export` 互斥） | `monitor.format_blackbox()` + `protocol.read_blackbox()`（0xC1 InfoID 1..10） | `test_cli_features.py` | 🧪 待真机（黑盒内容；MSI Center 从不读这个日志，格式为本项目定义，**不宣称 MSI 兼容**） |
| 按序號選多電源（`--serial`，默认第一颗，对不上报错并列列表） | `resolve_device()` | `test_demo.py`、`test_psu_sensors.py` | ✅ 已实现 |

### 3.2 能耗統計

| 需求 | 实现位置 | 测试 | 状态 |
|------|----------|------|------|
| 功率平均值（AVG，累計不清零） | `state.MonitorState.update()` / `monitor.apply_stats()` → `power_avg` | `test_state.py` | ✅ 已实现 |
| 效率平均值（AVG，累計不清零） | 同上 → `efficiency_avg`（算术平均，等价 MSI Center PCIE5 分支 `Efficiency_Total/Count`；MEG 分支的 `Wattage_Total/Wattage_in_Total` 是另一种定义，本实现不混用） | `test_state.py` | 🧪 待真机（AVG 数值） |
| 累計用電量（kWh，`wh += watts*dt/3600` 落盤） | `state.MonitorState.update()` → `total_energy_kwh` | `test_state.py` | 🧪 待真机（72 h 对照） |
| 當日運行時間（讀 `0xD0`/`0xD1`） | `get_sensors()` → `uptime`/`uptime_total` | `test_psu_sensors.py` | ✅ 已实现 |

### 3.3 查詢與匯出

| 需求 | 实现位置 | 测试 | 状态 |
|------|----------|------|------|
| Zero Fan 開關與風扇模式顯示（41h/42h） | `monitor.read_fan_fields()`、`format_text()` | `test_monitor_format.py`、`test_cli_features.py` | ✅ 已实现 |
| 按時間區間 + 按欄勾選的歷史匯出（`--export --from --columns`） | `monitor.run_export()`、`state.build_export()` | `test_cli_features.py`、`test_state.py` | ✅ 已实现 |

### 3.4 本地阈值早警（软件阈值，REQ-13/14）

| 需求 | 实现位置 | 测试 | 状态 |
|------|----------|------|------|
| 可配置本地阈值：总功率、温度、单针电流、针差、单 12V-2x6 连接器总电流、12V/5V/3.3V 轨电流（`[alerts]`，0=关闭） | `config.threshold_limits()`、`alerts.evaluate_threshold_alerts()`、`alerts.configured_threshold_names()` | `test_config.py`、`test_alerts.py` | ✅ 已实现（默认值为 REQ-14 初值，真机后调参） |
| 阈值告警进入统一告警链路：边沿去抖、stderr ALERT、exit 2、`alerts-*.log` | `monitor.attach_alerts()`、`AlertEngine`、`daemon._record_alerts()` | `test_cli_features.py`、`test_daemon.py` | ✅ 已实现 |
| 阈值告警与 12V-2x6 状态行分离，JSON/Prometheus 单独暴露 | `monitor.format_text()`（Thresholds 行）、JSON `threshold_alerts/threshold_limits`、Prometheus `msi_psu_threshold_alert/limit` | `test_cli_features.py`、`test_daemon.py` | ✅ 已实现 |
| 0xE0 读失败不清除已 latched 的阈值告警 | `evaluate_threshold_alerts()` 缺读数时省略名字 + `retain()` 的 `configured_threshold_names()` | `test_a_failed_payload_read_does_not_clear_a_threshold_alert` | ✅ 已实现 |
| 运维交付：生效配置查询、Prometheus 告警规则、电量 counter 双名、规范 exposition、严格 exposition 校验 | `monitor._dump_effective_config()`（`--dump-config`）、`docs/prometheus-rules.yml`、`format_prometheus()` 的 `msi_psu_energy_kwh_total` 别名、`tests/test_prometheus_exposition.py`（严格解析；官方 promtool 2.45.3 语法通过） | `test_cli_features.py`（dump-config/alias）、`test_packaging.py`（规则随包）、`test_prometheus_exposition.py` | ✅ 已实现 |
| 可靠性/发布收口：5k soak 门禁、确定性 fuzz、多轨 formatter、CHANGELOG/发布文档、Python 3.13 裸跑 | `scripts/soak.sh`（CI 接线）、`tests/test_soak.py`、`tests/test_robustness.py`、`CHANGELOG.md` | `test_soak.py`、`test_robustness.py`、`test_packaging.py`；裸 3.13.15 870 passed | ✅ 已实现 |
| 恢复/重连：初始化握手 3 次指数退避（0.5/1.0 s）+ daemon 连续 5 次失败后重扫 | `protocol._handshake()`、`daemon._ensure_psu()` | `test_psu_sensors.py`（握手重试/退避）、`test_daemon.py`（rescan） | ✅ 已实现 |

## 4. P0 數據正確性（已凍結）

| 需求 | 实现位置 | 测试 | 状态 |
|------|----------|------|------|
| FW 為 2 位 ASCII 數字，小數點由讀取方補（非「兩位數字」才透傳） | `protocol.MSIPSU.init()` | `test_psu_sensors.py` | ✅ 已实现 |
| 序列號按首字節長度切片 | 同上 | `test_psu_sensors.py` | ✅ 已实现 |
| PID 表補 `AA6F`（protocol + install.sh + udev） | `PSU_PRODUCT_IDS`、`VARIANTS[*]["pid"]`、udev、installer | `test_pid_consistency.py`（五处交叉校验） | ✅ 已实现 |
| 未知機型拒解（只出 ident + stderr + exit 1，不按 40 B 誤解析） | `get_sensors()` 的 `payload_size` 门 + `monitor.main()` 错误路径 | `test_psu_sensors.py`、`test_cli_features.py` | ✅ 已实现 |
| （附帶）P 系五條離散 12V 軌 + CPU/GPU 瓦特 | `get_sensors()` P 分支、`state.rail_watts()` | `test_psu_sensors.py`、`test_state.py`、`test_demo.py` | 🧪 待真机 |
| （附帶）Ai1600T 20 B 載荷不再被 44 B 硬門檻整段拒收 | `VARIANTS["meg_ai1600"]["payload_size"]=20` | `test_psu_sensors.py` | 🧪 待真机 |

## 5. 寫控制

| 需求 | 实现位置 | 测试 | 状态 |
|------|----------|------|------|
| 風扇自動/自訂切換與轉速寫入（`--fan-mode` + `--fan-duty 0-100`，超限電源自行鉗制，寫完讀回驗證） | `monitor.apply_fan_setting()`、`protocol.set_fan_mode()` | `test_cli_features.py` | 🧪 待真机 |
| 風扇設定儲存（`[0x50 0xF1]`，REV6 0 數據字節） | `set_fan_mode()` 内联发 `REG_SAVE_SETTING` | `test_cli_features.py` | 🧪 待真机 |
| 風扇配置按 Profile 恢復 | `daemon.restore_fan_profile()`（每次打開/重連重發 41h + F1h，並按 `[fan] zero_fan` 重發 43h + F1h）；`[fan] mode/duty/zero_fan` opt-in | `test_daemon.py`、`test_config.py` | 🧪 待真机 |
| Zero Fan 開關（43h + F1h，讀回 42h byte 4） | `MSIPSU.set_zero_fan()`、`monitor.apply_zero_fan_setting()`、`--zero-fan`；daemon 依 `[fan] zero_fan` 恢復 | `test_set_zero_fan_*`、`test_zero_fan_*`、`test_zero_fan_only_profile_is_restored` | 🧪 待真机 |
| 蜂鳴器開關切換（C2h，只寫無回讀；MSI 名為 BUZZER_SWITCH，會 toggle，CLI 不宣稱已靜音） | `MSIPSU.silence_buzzer()`、`monitor.run_write_controls()`、`--buzzer-toggle`（`--buzzer-off` 為兼容別名） | `test_silence_buzzer_*`、`test_buzzer_toggle_*`、`test_buzzer_off_remains_*` | 🧪 待真机 |
| OCP 閾值檢視（單針 12 A、針差 5 A、觸發 20 s、警告 180 s）+ 導出（`--dump-thresholds`/JSON） | `protocol.read_ocp_thresholds()`（0xC0 8 B）、`read_ocp_state()`（0xC1 42 B）、`monitor.run_ocp()`、`monitor.run_ocp_thresholds()`；daemon 每個 prom 週期一併導出（C1 是 5 s 滾動平均，不快取） | `test_ocp.py`、`test_cli_features.py`、`test_daemon.py` | ✅ 实现；数值/状态需真机核对 |
| 單多軌模式檢視（`==2` 為多軌） | `protocol.read_multirail_ocp()`（0xC0 1 B）、`monitor.format_multirail_*()` | `test_ocp.py`、`test_demo.py` | 🧪 待真机（**提前落地**） |
| 單多軌模式切換（MEG Ai1000P/Ai1300P；`--set-rail`，C0h 2/1 + F1h，寫前先讀回、同值不寫，寫後讀回） | `protocol.set_multirail_ocp()`、`monitor.apply_rail_mode()`（同值返回 `(mode, False)`，見 REQ-11） | `test_psu_sensors.py`、`test_cli_features.py`、`test_demo.py` | 🧪 待真机（用户要求补齐 MSI 的 DC Output 开关；不属于 12V-2x6 阈值写） |
| OCP 閾值設定（8 B + `0xF1`，範圍 10-14 A / 4-8 A / 5-30 s / 5-30 s / 30-240 s） | `protocol.set_ocp_thresholds()`、`monitor.apply_ocp_thresholds()`（寫 + F1h + 讀回，3 次；同值不寫）、`--ocp-set`/`--load-thresholds`；越界拒絕不 clamp、不支援機型 exit 1 | `test_ocp.py`、`test_cli_features.py`、`test_demo.py` | 🟡 已实现（demo/mock）；**保护写，需真机 bench 验收后放行** |

## 6. GUI（CLI 內不做）

| 需求 | 实现位置 | 测试 | 状态 |
|------|----------|------|------|
| 平時 CLI，看圖時 `--dashboard`（stdlib-only，預設 `127.0.0.1:8899`，`--port` 可改，關閉即停） | `dashboard.make_server()`、`monitor.run_dashboard()` | `test_dashboard.py` | ✅ 已实现 |
| 7 張即時曲線（歷史走 `daily-*.log`，累計/型號走 `state.json`，實時走 daemon 每秒寫的 `latest.json`；構成與 MSI Center 一致：12V/5V/3.3V/效率/溫度/風扇/功率 CPU+GPU+Total） | `dashboard.PAGE` + `/api/history`、`/api/state`、`/api/live`（1 s 輪詢，daemon 停止 10 s 後 503/stale） | `test_dashboard.py`、`test_daemon.py`、`test_state.py` | ✅ 已实现 |
| Weekly 七天用電圖（`state.json` 的 `daily` kWh 桶，不是 `daily-*.log`） | `dashboard.PAGE: drawWeekly()` + `/api/state` | `test_dashboard.py` | ✅ 已实现 |
| 讀不到 state 目錄/檔案時不假裝「沒資料」 | `dashboard._state_dir_problem()`（目錄 → `/api/*` 503）、`MonitorState.load(strict=True)`（損壞的 `state.json` → 僅 `/api/state` 503），頁面本身仍 200；`/api/history` 照常服務 | `test_dashboard.py`、`test_state.py` | ✅ 已实现 |
| 截圖存圖片 → 看圖頁提供匯出 PNG/CSV | `/api/export`（前端导出按钮，HEAD 与 GET 同状态同长度） | `test_dashboard.py` | ✅ 已实现 |
| 桌面彈窗 | — | — | ⏸ 明确不做 |

## 7. 无硬件可覆盖的验证方式

所有 🧪 项在无样机时的最大覆盖：`bash scripts/smoke.sh` 一条命令跑完全链路（CI 也跑），`MSI_PSU_DEMO=1` 合成电源（`MSI_PSU_DEMO_MODEL` 可切
全部 5 机型、`MSI_PSU_DEMO_ALERT` 可卡任意告警位），配合 870 个单测覆盖解析、告警、
落盘、导出的全部分支。**每一条待真机项的判定标准与命令见 [`verify.md`](verify.md) §8（共 19 项）。**

## 非需求交付物（如实标注）

| 交付物 | 状态 | 说明 |
| --- | --- | --- |
| `kernel/msi-psu-ai1600ts.patch` | ⏸ 草稿，不可构建 | 未编译过、不对应任何已复核的上游版本；文件头已列出致命 hunk（文件作用域的枚举常量、无 `t` 的函数里用 `t`、switch 外的 `case`、第二个 `default:`、未定义的 `iout_pins_fops`、无代码填充 62B 结构体）。README/`install.sh` 不再声称可用；用户态工具才是受支持路径 |

