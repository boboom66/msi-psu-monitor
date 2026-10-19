# msi-psu-monitor 全项目测试计划（第一阶段）

> 状态：Phase 1 完成（项目结构调查、功能盘点、测试矩阵、基线执行）
> 基线提交：`650076a`（2026-10-19）
> 本文档不构成“生产合格”结论；真机与发布环境仍有明确阻塞项。

## 1. 范围与依据

测试对象为 `/home/timzhang/projects/project/msi-psu-monitor` 当前工作树。

- 原项目基线：`807b681`（`origin/master`，上游 HesiPullupTimbo 的 Initial release）。
- 本地改造：`807b681..650076a` 共 58 个提交。
- 依据：实际源码、`git log/diff`、已有测试、CI、打包脚本、协议文档；不以 README 单独作为功能事实。
- 不能确认的部分：上游发布历史只有初始提交，无版本 tag；官方 arm64/Ubuntu 22.04 构建尚未在本机复现。

## 2. 测试环境（实测）

| 项目 | 值 |
|---|---|
| OS | Ubuntu 24.04 LTS（WSL2） |
| 内核 | 6.18.33.2-microsoft-standard-WSL2 x86_64 |
| glibc | 2.39 |
| Python | 3.12.3；CI 矩阵 3.10/3.12/3.13 |
| systemd | 255（运行中） |
| 权限 | 普通用户 `timzhang`，sudo 需要密码 |
| 硬件 | 无 `/dev/hidraw*`、无 `/sys/class/hidraw` |
| 架构 | x86_64（无 arm64 运行环境） |

结论：**所有真实 PSU 通信测试 BLOCKED**；可用 demo/fake 验证软件路径。

## 3. 项目结构与调用链

```text
CLI 入口
  msi-psu-monitor = msi_psu_monitor.monitor:main
  msi-psu-monitor-daemon = msi_psu_monitor.daemon:main
  python -m msi_psu_monitor -> monitor.main

CLI 主链:
  main -> _main -> load_config -> resolve_device / detect_devices
       -> open_psu (MSIPSU + HIDDevice, 或 DemoPSU)
       -> run_once / run_watch / run_export / run_dashboard / run_ocp
       -> format_text/json/prometheus -> emit -> exit 0/1/2

常驻链:
  daemon.main -> MonitorDaemon.run -> tick -> sample
       -> get_sensors -> collect_alerts -> state.update
       -> write_prometheus / record_history / write_live_snapshot / alert log
       -> 失败 5 次 -> _rediscover

Dashboard 链:
  make_server/ThreadingHTTPServer -> _route
       -> /api/history /api/state /api/export /api/live
       -> PAGE (内嵌 JS, canvas 绘图)

发布链:
  build_binary.sh (PyInstaller onefile) -> tar.gz
  build_deb_binary.sh -> zero-Python .deb
  build_sbom.py -> CycloneDX；release.yml -> GitHub Release
```

模块职责：

| 模块 | 职责 |
|---|---|
| `protocol.py` | hidraw 发现、HID 帧、机型分派、寄存器读、写入、告警/黑盒/OCP/VIN |
| `monitor.py` | CLI 参数、设备选择、格式化、告警采集、统计应用、导出、dashboard/ocp 入口 |
| `alerts.py` | E1h/软件镜像告警、去抖、严重度、恢复事件 |
| `state.py` | 平均值、能量积分、state.json、历史、告警日志、实时快照、导出 |
| `daemon.py` | 常驻采样、prometheus、历史、换机重扫、Profile 恢复、信号 |
| `dashboard.py` | loopback HTTP、历史/状态/实时 API、内嵌图表页 |
| `config.py` | INI 解析、默认值、优先级、容错 |
| `demo.py` | 无硬件合成 PSU（仅 opt-in） |
| `scripts/*` | 构建、安装、卸载、smoke、SBOM |
| `systemd/*` | unit、udev、沙箱 |
| `tests/*` | 636 个自动化测试（Phase 3 当前） |

## 4. 功能清单（FUNC）

状态图例：`C` 自动化覆盖（软件层）；`P` 部分覆盖；`B` 需真机/真实环境；`N` 尚未覆盖；`D` 有意不做。

### 4.1 入口与 CLI

| ID | 功能 | 源码 | 现有测试 | 状态 |
|---|---|---|---|---|
| FUNC-001 | `msi-psu-monitor` 控制台入口 | `pyproject.toml` / `monitor.py:main` | `test_monitor.py`、smoke | C |
| FUNC-002 | `python -m msi_psu_monitor` | `__main__.py` | `test_monitor.py` | C |
| FUNC-003 | daemon 控制台入口 | `daemon.py:main` | `test_daemon.py` | C |
| FUNC-004 | `--help` 帮助与退出 0 | `monitor.py:build_parser` | `test_cli_features.py`、smoke | C |
| FUNC-005 | `--version` 与 pyproject 一致 | `monitor.py`、`__init__.py` | `test_docs_consistency.py` | C |
| FUNC-006 | 无参数默认 one-shot | `_main` | `test_cli_features.py` | C |
| FUNC-007 | `--once` | `_main` | `test_cli_features.py`、smoke | C |
| FUNC-008 | `--watch` 无值默认间隔 | `run_watch`、`_watch_interval` | `test_cli_features.py` | C |
| FUNC-009 | `--watch N` 指定间隔 | 同上 | `test_cli_features.py`、smoke | C |
| FUNC-010 | `--interval` 仅与 watch 搭配 | `_validate_args` | `test_cli_features.py` | C |
| FUNC-011 | `-O/--output` 单次输出 | `emit` | `test_cli_features.py`、smoke | C |
| FUNC-012 | `-O/--output` watch 追加与 flush | `emit`、`run_watch` | `test_cli_features.py`、smoke | C |
| FUNC-013 | text 格式 | `format_text` | `test_monitor_format.py` | C |
| FUNC-014 | JSON 格式与 schema | `format_json` | `test_schema.py`、smoke | C |
| FUNC-015 | Prometheus 格式与 `msi_psu_up` | `format_prometheus` | `test_monitor_format.py`、smoke | C |
| FUNC-016 | `--serial` 选择多 PSU | `resolve_device` | `test_cli_features.py`、`test_demo.py` | C（真机 B） |
| FUNC-017 | `--config` 显式配置 | `load_config` | `test_config.py` | C |
| FUNC-018 | 默认配置搜索与 CLI 优先级 | `config.py` | `test_config.py` | C |
| FUNC-019 | `--verbose` / `--quiet` | `setup_logging` | `test_cli_features.py` | C |
| FUNC-020 | `--no-alerts` | `_main` | `test_cli_alerts.py`、smoke | C |
| FUNC-021 | `--show-log` 黑盒 | `run_once`/`format_blackbox` | `test_cli_features.py` | C（真机 B） |
| FUNC-022 | `--show-alert-log` 本地告警日志 | `run_show_alert_log` | `test_cli_features.py` | C |
| FUNC-023 | `--ocp` 只读 OCP 视图 | `run_ocp` | `test_ocp.py`、smoke | C（真机 B） |
| FUNC-024 | `--export` | `run_export` | `test_cli_features.py`、smoke | C |
| FUNC-025 | `--from` 时间窗 | `parse_from` | `test_state.py`、`test_cli_features.py` | C |
| FUNC-026 | `--columns` 选择列 | `parse_columns` | `test_state.py`、`test_cli_features.py` | C |
| FUNC-027 | `--dashboard` | `run_dashboard` | `test_dashboard.py`、smoke | C |
| FUNC-028 | `--port` | `run_dashboard` | `test_dashboard.py` | C |
| FUNC-029 | `--fan-mode` / `--fan-duty` | `apply_fan_setting` | `test_cli_features.py` | C（真机 B） |
| FUNC-030 | `--zero-fan` | `apply_zero_fan_setting` | `test_cli_features.py` | C（真机 B） |
| FUNC-031 | `--buzzer-off` | `silence_buzzer` | `test_cli_features.py` | C（真机 B） |
| FUNC-032 | `--set-rail` | `apply_rail_mode` | `test_cli_features.py`、`test_psu_sensors.py` | C（真机 B） |
| FUNC-033 | 退出码 0/1/2 | `_main`、`run_*` | `test_cli_alerts.py`、`test_cli_features.py` | C |
| FUNC-034 | 参数冲突/未知参数/缺失值 | `_validate_args`、argparse | `test_cli_features.py` | C |
| FUNC-035 | 管道/BrokenPipe/重定向 | `main` | `test_cli_features.py`、`test_monitor.py` | C |

### 4.2 设备发现、权限与初始化

| ID | 功能 | 源码 | 现有测试 | 状态 |
|---|---|---|---|---|
| FUNC-040 | sysfs/hidraw 自动发现 | `detect_devices` | `test_protocol_discovery.py` | C |
| FUNC-041 | 单设备发现与默认选择 | `detect_device` | 同上 | C |
| FUNC-042 | 5 个 USB PID 覆盖 | `PSU_PRODUCT_IDS`、VARIANTS、udev、installer | `test_pid_consistency.py` | C |
| FUNC-043 | 按序列号选择/错误提示 | `resolve_device` | `test_cli_features.py`、`test_psu_sensors.py` | C |
| FUNC-044 | 无设备错误 | `_main` | `test_cli_features.py`、E2E | C |
| FUNC-045 | 权限不足错误 | `HIDDevice.open` | 单测假设备；真实 EACCES B | P/B |
| FUNC-046 | 设备忙/flock 独占 | `HIDDevice` | `test_psu_sensors.py`、`test_daemon.py` | C |
| FUNC-047 | open/close/重连 | `HIDDevice`、`MonitorDaemon` | `test_daemon.py` | C |
| FUNC-048 | handshake 与 init | `MSIPSU.init` | `test_psu_sensors.py` | C |
| FUNC-049 | 未知/截断机型拒绝解析 | `init`、`get_sensors` | `test_psu_sensors.py` | C |
| FUNC-050 | demo 绕过真实设备 | `demo.enabled`、`open_psu` | `test_demo.py` | C |

### 4.3 协议读取与数据解析

| ID | 功能 | 源码 | 现有测试 | 状态 |
|---|---|---|---|---|
| FUNC-060 | 64B 帧、250ms、echo、NAK | `HIDDevice.send_command` | `test_psu_sensors.py`、`test_protocol.py` | C |
| FUNC-061 | 厂商 0x10 / 型号 0x11 | `MSIPSU.init` | `test_psu_sensors.py` | C |
| FUNC-062 | 固件 0x12（2 位 ASCII） | `init` | `test_psu_sensors.py` | C |
| FUNC-063 | 序列号 0x13（两种长度前缀） | `init` | `test_psu_sensors.py` | C |
| FUNC-064 | VIN 0x20（非 TS） | `read_vin` | `test_psu_sensors.py` | C（真机 B） |
| FUNC-065 | E0 TS 44B/62B | `get_sensors` TS 分支 | `test_psu_sensors.py` | C |
| FUNC-066 | E0 P 40B 五轨 | `get_sensors` P 分支 | `test_psu_sensors.py` | C |
| FUNC-067 | E0 Ai1600T 20B | `get_sensors` T 分支 | `test_psu_sensors.py` | C |
| FUNC-068 | LINEAR11 标度/符号/边界 | `lin11_to_int` | `test_protocol_lin11.py`、`test_protocol.py` | C |
| FUNC-069 | 12 针电流 | `get_sensors`、`_parse_pin_currents` | `test_psu_sensors.py` | C |
| FUNC-070 | 12V1-5 电压/电流 | `get_sensors` P 分支 | `test_psu_sensors.py` | C |
| FUNC-071 | 功率/效率/温度/风扇 | `get_sensors` | `test_psu_sensors.py` | C |
| FUNC-072 | 运行时间 D0/D1 | `get_sensors` | `test_psu_sensors.py` | C |
| FUNC-073 | E1h 三套机型字节序 | `ALERT_INDEXES`、`read_alert_status` | `test_psu_sensors.py`、`test_alerts.py` | C（真机 B） |
| FUNC-074 | C0 TS 8B OCP 阈值 | `read_ocp_thresholds` | `test_ocp.py` | C（真机 B） |
| FUNC-075 | C1 42B OCP 状态 | `read_ocp_state` | `test_ocp.py` | C（真机 B） |
| FUNC-076 | C1 InfoID 1..10 黑盒 | `read_blackbox` | `test_psu_sensors.py`、`test_cli_features.py` | C（真机 B） |
| FUNC-077 | 风扇 41h/42h 读取 | `read_fan_setting/duty` | `test_psu_sensors.py` | C |
| FUNC-078 | Zero Fan 42h byte4 读取 | `read_zero_fan` | `test_psu_sensors.py` | C |
| FUNC-079 | 多轨 0xC0 1B 读取 | `read_multirail_ocp` | `test_psu_sensors.py`、`test_ocp.py` | C |
| FUNC-080 | 短帧/垃圾帧/NAK/无响应 | 各读取函数 | 单测假 HID；HID 负向/模糊测试 N | P |
| FUNC-081 | 设备字符串清洗/限长 | `_clean_identity` | `test_psu_sensors.py` | C |
| FUNC-082 | ident-only 不算成功样本 | `get_sensors`、`has_readings` | `test_daemon.py`、`test_cli_features.py` | C |

### 4.4 写控制

| ID | 功能 | 源码 | 现有测试 | 状态 |
|---|---|---|---|---|
| FUNC-090 | 风扇写 41h + F1h + 读回 | `set_fan_mode`、`apply_fan_setting` | `test_psu_sensors.py`、`test_cli_features.py` | C（真机 B） |
| FUNC-091 | Zero Fan 写 43h + F1h + 读回 | `set_zero_fan`、`apply_zero_fan_setting` | 同上 | C（真机 B） |
| FUNC-092 | 蜂鸣器 C2h | `silence_buzzer` | `test_psu_sensors.py`、`test_cli_features.py` | C（真机语义 B） |
| FUNC-093 | 多轨 C0h 1B + F1h + 读回 | `set_multirail_ocp`、`apply_rail_mode` | 同上 | C（真机 B） |
| FUNC-094 | 写失败/NAK/读回不一致处理 | `apply_*` | `test_cli_features.py` | C |
| FUNC-095 | daemon `[fan]` Profile 恢复 | `restore_fan_profile` | `test_daemon.py` | C（真机 B） |
| FUNC-096 | 写操作审计行 | `run_write_controls` | `test_cli_features.py` | C |
| FUNC-097 | 写参数与查询互斥 | `_validate_args` | `test_cli_features.py` | C |

### 4.5 告警

| ID | 功能 | 源码 | 现有测试 | 状态 |
|---|---|---|---|---|
| FUNC-100 | 12V-2x6 单针 >12A | `evaluate_pin_alerts` | `test_alerts.py` | C |
| FUNC-101 | 针差 >5A | 同上 | `test_alerts.py` | C |
| FUNC-102 | E1h 告警名/严重度 | `ALERT_DESCRIPTIONS`、`severity_of` | `test_alerts.py`、`test_psu_sensors.py` | C |
| FUNC-103 | 连续去抖 | `AlertEngine.update` | `test_alerts.py` | C |
| FUNC-104 | 恢复事件 | `take_cleared` | `test_alerts.py` | C |
| FUNC-105 | 换机型 retain | `AlertEngine.retain` | `test_alerts.py`、`test_daemon.py` | C |
| FUNC-106 | 状态行 Normal/Unknown/告警 | `status_from` | `test_cli_alerts.py`、`test_daemon.py` | C |
| FUNC-107 | 告警日志写入/轮转/清理/查看 | `append_alert_log`、`run_show_alert_log` | `test_state.py`、`test_daemon.py`、`test_cli_features.py` | C（真机 B） |

### 4.6 统计、历史与导出

| ID | 功能 | 源码 | 现有测试 | 状态 |
|---|---|---|---|---|
| FUNC-110 | 功率平均 | `MonitorState.power_avg` | `test_state.py` | C |
| FUNC-111 | 效率平均 | `efficiency_avg` | `test_state.py` | C |
| FUNC-112 | 能量积分/300s 空档 | `update` | `test_state.py` | C |
| FUNC-113 | state.json 原子写/损坏恢复 | `load/save/atomic_write_text` | `test_state.py` | C |
| FUNC-114 | 日 CSV 追加/表头修复/BOM | `append_history` | `test_state.py` | C |
| FUNC-115 | CPU/GPU 瓦特 | `rail_watts` | `test_state.py` | C |
| FUNC-116 | 每日 kWh 桶/Weekly | `_daily_buckets` | `test_state.py`、`test_dashboard.py` | C |
| FUNC-117 | 历史读取/时间窗 | `iter_history`、`parse_from` | `test_state.py` | C |
| FUNC-118 | CSV 导出列/格式 | `build_export` | `test_state.py`、`test_cli_features.py` | C |
| FUNC-119 | 30 天清理 | `prune`、`prune_history` | `test_state.py` | C |
| FUNC-120 | latest.json 实时快照 | `write/read_live_snapshot` | `test_state.py`、`test_daemon.py` | C |

### 4.7 常驻 daemon

| ID | 功能 | 源码 | 现有测试 | 状态 |
|---|---|---|---|---|
| FUNC-130 | 常驻循环/iterations | `run/tick` | `test_daemon.py` | C |
| FUNC-131 | 1s 告警采样 | `sample` | `test_daemon.py`、smoke | C |
| FUNC-132 | 30s Prometheus 原子写 | `write_prometheus` | `test_daemon.py`、smoke | C |
| FUNC-133 | 失败时 `msi_psu_up 0` | `write_prometheus_failure` | `test_daemon.py` | C |
| FUNC-134 | OCP 指标块 | `refresh_ocp` | `test_daemon.py` | C |
| FUNC-135 | 60s 历史 | `record_history` | `test_daemon.py` | C |
| FUNC-136 | 失败 5 次重扫 | `_rediscover` | `test_daemon.py` | C |
| FUNC-137 | 信号退出/资源关闭 | `_install_signal_handlers` | `test_daemon.py` | P |
| FUNC-138 | state dir/配置/错误退出 | `main` | `test_daemon.py` | C |
| FUNC-139 | 长期运行/泄漏/稳定性 | 全模块 | 无长时间测试 | N |

### 4.8 Dashboard

| ID | 功能 | 源码 | 现有测试 | 状态 |
|---|---|---|---|---|
| FUNC-150 | 仅 loopback 绑定 | `make_server` | `test_dashboard.py`、smoke | C |
| FUNC-151 | 页面渲染/占位符替换 | `PAGE`、`render_page` | `test_dashboard.py` | C |
| FUNC-152 | `/api/history` | `_history_payload` | `test_dashboard.py` | C |
| FUNC-153 | `/api/state` | `_state_payload` | `test_dashboard.py` | C |
| FUNC-154 | `/api/export` | `_route` | `test_dashboard.py`、smoke | C |
| FUNC-155 | `/api/live` 与 stale/503 | `read_live_snapshot` | `test_dashboard.py`、smoke | C |
| FUNC-156 | from/columns 查询 | `_from_spec`/`_columns` | `test_dashboard.py` | C |
| FUNC-157 | HEAD/404/400/503 语义 | `_route` | `test_dashboard.py` | C |
| FUNC-158 | 图表/PNG/CSV/Weekly | 内嵌 JS | 只能静态/HTTP 测；浏览器 N | P |
| FUNC-159 | 真实浏览器 1s 刷新 | 内嵌 JS | 无浏览器自动化 | N |
| FUNC-160 | Host 头/DNS rebinding/CSP | `_route` | 未实现 Host 校验 | N |

### 4.9 配置、demo、打包、安全、文档

| ID | 功能 | 源码 | 现有测试 | 状态 |
|---|---|---|---|---|
| FUNC-170 | INI 段/未知项/默认值 | `config.py` | `test_config.py` | C |
| FUNC-171 | 非法值回落 | 同上 | `test_config.py` | C |
| FUNC-172 | `[fan]` opt-in | 同上 | `test_config.py`、`test_daemon.py` | C |
| FUNC-173 | `[daemon] alert_log/live_snapshot` | 同上 | `test_config.py` | C |
| FUNC-174 | UTF-8/BOM/显式缺失文件 | 同上 | `test_config.py` | C |
| FUNC-180 | demo opt-in | `demo.enabled` | `test_demo.py` | C |
| FUNC-181 | 5 机型 demo | `MODEL_WATTS` | `test_demo.py` | C |
| FUNC-182 | 告警注入 | `_stuck_alert` | `test_demo.py` | C |
| FUNC-183 | demo 不碰真实设备 | `open_psu` | `test_demo.py` | C |
| FUNC-190 | 源码 .deb | `build_deb.sh` | smoke、`test_packaging.py` | C |
| FUNC-191 | 自包含 tar.gz | `build_binary.sh` | 本地 x86 构建通过；22.04/arm B | P/B |
| FUNC-192 | 零 Python .deb | `build_deb_binary.sh` | 本地构建、Depends 检查 | C（22.04 B） |
| FUNC-193 | install/uninstall | `install_binary.sh`、`uninstall_binary.sh` | 仅静态检查 | N（root） |
| FUNC-194 | udev rule | `99-msi-psu.rules` | 静态/一致性 | N（真实设备） |
| FUNC-195 | systemd unit/沙箱 | `msi-psu-monitor.service` | `systemd-analyze verify`、静态 | P（未实际启动） |
| FUNC-196 | checksums/SBOM | 脚本/release | `test_release_security.py` | C |
| FUNC-197 | release workflow | `.github/workflows/release.yml` | 静态测试；未实际发版 | N |
| FUNC-198 | CI 矩阵/门禁 | `.github/workflows/ci.yml` | 本地复跑；CI 未观察 | P |
| FUNC-199 | 内核模块补丁 | `kernel/` | 草稿不可构建 | D/B |
| FUNC-200 | 标签/身份清洗 | `_label`、`_clean_identity` | `test_monitor_format.py`、`test_psu_sensors.py` | C |
| FUNC-201 | stdlib-only | `pyproject`、`test_stdlib_only` | C | C |
| FUNC-202 | 数据权限/序列号暴露 | state/unit | 未做真实权限测试 | N |
| FUNC-203 | 安全/支持/应急文档 | `SECURITY.md` 等 | `test_release_security.py` | C |
| FUNC-210 | README/CLI 一致性 | `test_docs_consistency.py` | C | C |
| FUNC-211 | 协议文档/验收文档 | docs | 一致性测试部分覆盖 | P |

## 5. 测试矩阵

表格中的 `Y` 已有自动化/可重复测试，`P` 部分覆盖，`N` 未覆盖，`B` 需真实硬件/root/发布环境。

| 功能组 | 静态 | 单元 | 集成 | E2E | 异常 | 边界 | 稳定 | 安全 | 兼容 | 真机 |
|---|---|---|---|---|---|---|---|---|---|---|
| CLI/参数/退出码 | Y | Y | Y | Y | Y | Y | N | P | P | P |
| 设备发现/权限/flock | Y | Y | Y | P | P | P | N | P | N | B |
| 协议读取/机型/解析 | Y | Y | Y | P | P | Y | N | P | N | B |
| 写控制 | Y | Y | Y | P | Y | P | N | P | N | B |
| 告警/恢复/日志 | Y | Y | Y | Y | Y | Y | N | P | N | B |
| 统计/历史/导出 | Y | Y | Y | Y | Y | Y | N | P | P | P |
| daemon | Y | Y | Y | Y | Y | P | N | P | P | B |
| Dashboard API | Y | Y | Y | Y | Y | Y | N | P | P | N |
| Dashboard 浏览器 | P | N | N | N | N | N | N | N | N | N |
| 配置 | Y | Y | Y | Y | Y | Y | N | P | P | P |
| demo | Y | Y | Y | Y | Y | Y | N | P | P | P |
| 打包/安装/发布 | Y | P | P | P | P | P | N | P | B | B |
| 文档/质量护栏 | Y | Y | N | N | N | N | N | P | P | N |

## 6. 基线结果（详见 `test-report.md`）

- `pytest -q`：**569 passed**（3.10.21 / 3.12.3 裸环境与 3.12.3 venv 各一次）。
- 源码覆盖率（临时 `uv run --with coverage`，未改项目依赖）：语句 **93.02%**、分支 **89.20%**。
- `ruff check` / `ruff format --check`：通过。
- `mypy`：10 files，无问题。
- `compileall`、`shellcheck -S warning`、`systemd-analyze verify`：通过。
- `scripts/smoke.sh`：**58 passed，0 failed**。
- 本地 x86_64 二进制/`.deb`/SBOM 构建通过；二进制 clean-env demo 通过。
- **真实硬件**：无 hidraw，BLOCKED。
- **root/systemd 实际启动、安装/卸载、udev、Ubuntu 22.04/arm64**：BLOCKED/NOT RUN。

## 7. 主要风险与不确定项

1. 无 `hidraw` 设备：所有真实 PSU 通信、权限、root 行为、型号差异无法验证。
2. 本机 glibc 2.39；Phase 3 已用 22.04 rootfs/chroot 构建并在 22.04 内运行通过（见 test-report §10.8），但 CI 仍须复跑。
3. 无 arm64 环境；release workflow 的 arm runner 未验证。
4. Dashboard JS 没有真实浏览器测试；只验证 HTTP 与页面源码。
5. 安装/卸载、systemd 启停、udev uaccess 没有实际执行（无 sudo）。
6. 缺少长稳/泄漏测试、HID 负向模糊测试、属性测试。
7. 覆盖率工具未纳入 dev 依赖/CI；当前数字是一次性测量。
8. release workflow 未执行；arm64 与 22.04 产物未生成。
9. Dashboard 未校验 Host 头（DNS rebinding 加固缺口），需安全评审。
10. state/告警文件权限与序列号暴露没有实测/评审。
11. 多轨写、VIN 量程、蜂鸣器 toggle、黑盒 pin/set 语义仍需真机确认。

## 8. 下一阶段计划

1. 为 FUNC 清单建立 `TEST-xxx` 用例，先覆盖 P0/P1 风险：协议/告警/stat/daemon/CLI。
2. 新增测试：HID 负向帧、dashboard Host/CSP、安装脚本静态+容器、systemd 单元、长稳循环。
3. 修复确认的缺陷；每项附回归测试。
4. 在 22.04/arm64 环境复核构建与二进制；真实 PSU 环境执行 verify §8。
5. 最终重跑全量、覆盖率、smoke、构建和发布验收。
