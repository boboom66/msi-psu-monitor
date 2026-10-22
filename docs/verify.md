# 无硬件自检手册

> 没有真机也能验证 CLI、告警、daemon、历史落盘、prometheus 与 dashboard 全链路。
> 下面每条命令都已在 `.venv`（Python 3.12.3）实跑通过；完整测试套件另在裸
> Python 3.13.15 与 Python 3.10.21（uv 下载）各复核 **803 通过**；
> `smoke.sh` → 58 项（Python 3.12 环境跑过）。3.10 已实跑，同时保留静态门禁——ruff `target-version = "py310"`、mypy
> `python_version = "3.10"`（按 3.10 typeshed 分析）、smoke 里对每个 `.py` 的
> `ast.parse(feature_version=(3, 10))`；CI 矩阵另在 3.10 / 3.12 / 3.13 上执行。
> 需要真机的部分集中在最后一节，交付样机后再做。

## 0. 环境

```bash
cd /home/timzhang/projects/project/msi-psu-monitor
uv sync --group dev          # 建 .venv，装 pytest/ruff/mypy，本项目以可编辑方式装入
```

`uv`/`ruff` 若不在 PATH：`~/.local/bin/uv`、`~/.local/bin/ruff`。

## 1. 全部门禁

```bash
uv run --group dev pytest -q
```

```bash
uv run --group dev ruff check .
```

```bash
uv run --group dev mypy msi_psu_monitor/
```

覆盖率门禁（源包语句覆盖不得低于 90%；CI 也跑）：

```bash
uv run --group dev coverage run --branch -m pytest -q
uv run --group dev coverage report --fail-under=90
```

加速长跑门禁（demo，5000 次采样；CI 也跑）：

```bash
bash scripts/soak.sh 5000
```

它检查 daemon 正常退出、state/latest/prom/daily 仍在更新、`msi_psu_up 1`，以及
峰值 RSS ≤256 MiB、fd ≤64；输出 `SOAK PASS` 才算过。默认 5000，最少 100。

无 PSU 也能查看生效配置（含 `[alerts]` 阈值；text/json）：

```bash
msi-psu-monitor --dump-config
msi-psu-monitor --dump-config -f json | python3 -m json.tool | head
```

现在 `ruff format --check .` 也安全了（`[tool.ruff.format] exclude` +
`force-exclude = true` 把 4 个历史文件挡在外面），CI 已把它加进门禁：

```bash
uv run --group dev ruff format --check .
```

### 1.1 测试模块清单

| 模块 | 覆盖（每行点名至少一个真实测试函数，由 `test_docs_consistency.py` 与收集结果核对） |
|------|------|
| `tests/test_protocol.py` | `lin11_to_int` 的 8 条标度/符号向量（`test_unsigned_mode_keeps_high_bit`、`test_exponent_negative_shift`）；帧拼装与 NAK 覆盖在 `test_psu_sensors.py` |
| `tests/test_protocol_discovery.py` | sysfs 发现、5 个 PID 全覆盖、演示模式不碰 sysfs（`test_detect_devices_never_returns_the_device_directory_name`）；解析器用真实实现（`test_resolve_device_uses_the_real_parser`） |
| `tests/test_protocol_lin11.py` | LINEAR11 原始向量与 exp −4 / −7 边界（`test_negative_exponent`、`test_default_mantissa_is_unsigned_not_twos_complement`） |
| `tests/test_psu_sensors.py` | 62 B / 40 B / 20 B 载荷解析、P 系五轨、帧/NAK（`test_a_meg_frame_whose_first_payload_byte_is_0xfe_is_still_decoded`）、告警位顺序、0xC1 状态/黑盒 |
| `tests/test_alerts.py` | 阈值判定、`consecutive_required` 去抖（`test_debounce_needs_two_consecutive_polls`）、严重度、`retain()` 换机清理 |
| `tests/test_state.py` | 能量积分、原子写中断（`test_an_interrupted_save_keeps_the_previous_state_intact`）、strict load、历史追加/裁剪、`--export` 列 |
| `tests/test_config.py` | INI 解析、`[daemon]`、`[fan]` 段与非法值回落；显式 `--config` 缺失/格式错误必须报错（`test_an_explicit_config_file_must_exist`）；越界 port 回落 |
| `tests/test_monitor_format.py` | text / json / prometheus 三种 formatter（`test_prometheus_reports_down_for_a_short_payload`）；多轨 12V1-5 电压/电流与 CPU/GPU 拆分（`test_prometheus_multi_rail_uses_rail_labels_and_cpu_gpu_metrics`）；prometheus 契约在这里，不在 `test_schema.py` |
| `tests/test_cli_alerts.py` | CLI 告警路径与退出码 2（`test_once_alert_exits_two_and_prints_line`）、黑盒空表 |
| `tests/test_cli_features.py` | `--watch`/`-O`/`--serial`/`--show-log`/`--fan-*`/`--export`/互斥校验（`test_an_empty_columns_spec_is_not_silently_every_column`） |
| `tests/test_ocp.py` | 0xC0 阈值 / 0xC1 状态 / 单多轨标志的三格式输出与机型门（`test_run_ocp_on_a_meg_p_model_shows_the_multirail_flag`）；0xC0 阈值写的 MSI 字节编码与 F1h 保存（`test_set_ocp_thresholds_writes_msi_bytes_then_saves`） |
| `tests/test_daemon.py` | 采样节拍、原子写（`test_a_failed_prometheus_replace_keeps_the_previous_textfile`）、重扫、风扇 Profile 恢复、只答 ident 判读失败、OCP 块换机不继承旧阈值 |
| `tests/test_dashboard.py` | HTTP 端点、损坏 state.json 的 503（`test_a_corrupt_state_file_is_a_503_while_history_still_serves`）、HEAD 与错误码一致、真实时间 x 轴 |
| `tests/test_demo.py` | 合成电源、5 机型切换、告警位注入（`test_every_supported_variant_can_be_emulated`） |
| `tests/test_packaging.py` | 安装器/`.deb`/udev/config 不变量（`test_the_deb_does_not_inherit_the_builders_umask`、`test_the_unit_does_not_require_a_config_nothing_installs`） |
| `tests/test_install_namespace.py` | 一次性用户命名空间内实际安装/卸载：配置保留、systemctl/udevadm 调用、`--purge` 删除（`test_root_install_keeps_config_and_uninstall_purges_it`） |
| `tests/test_hardware_kit.py` | 硬件验收 kit 的 shell 语法、二进制/源码/文档打包、装机说明、release 发布接线（`test_the_kit_builder_ships_binary_source_and_docs`、`test_the_release_workflow_publishes_the_hardware_kit`） |
| `tests/test_schema.py` | JSON 输出结构契约（`test_json_schema_keys_frozen`）；prometheus 契约在 `test_monitor_format.py` |
| `tests/test_monitor.py` | 遗留冒烟（兼容旧接口，勿删；`test_format_text_contains_keys`） |
| `tests/test_pid_consistency.py` | 五处 USB PID 列表 + README 载荷双数字（`test_readme_payload_sizes_match_the_parser`） |
| `tests/test_stdlib_only.py` | `python -I` 子进程导入全部模块（零第三方依赖；`test_the_probe_covers_every_shipped_module`） |
| `tests/test_docs_consistency.py` | 文档里的用例数、测试文件名、§1.1 覆盖表函数名、CLI 参数清单、版本号双重来源不得与事实不符（`test_quoted_test_counts_are_accurate`） |
| `tests/test_release_security.py` | SBOM/CycloneDX 与产物哈希、SECURITY/support/incident 文档、release workflow 发布 SBOM（`test_the_sbom_generator_emits_cyclonedx_with_artifact_hashes`、`test_the_release_workflow_generates_and_publishes_an_sbom`） |
| `tests/test_e2e_cli.py` | 真实 console 入口子进程：`--version`/`--help`/demo text+json/告警 exit 2/`-O`/`--show-alert-log`/无设备错误（`test_demo_alert_exit_code_and_stderr_via_subprocess`、`test_no_demo_no_hardware_is_a_clean_error`） |
| `tests/test_ai1300ts.py` | Ai1300TS 全功能回归（`test_ai1300ts_cli_covers_every_feature`）：读数/JSON/Prom、OCP 读写、风扇/Zero Fan/蜂鸣器、告警和本地阈值、`--set-rail` 拒绝 |
| `tests/test_prometheus_exposition.py` | 严格 exposition 语法（`test_format_prometheus_passes_a_strict_exposition_parser`）：HELP/TYPE、label 转义、数值、重复序列，旧式 `metric {} value` 必须被拒；promtool 的本机替代（2026-10-22 官方 promtool 2.45.3 已补跑：语法通过，8 条命名告警待决策） |
| `tests/test_robustness.py` | 确定性 fuzz：随机 0xE0 payload ×5 机型、随机配置文本、随机 `--ocp-set`（`test_random_bulk_payloads_never_crash_a_variant_or_a_formatter`）；不崩、不泄漏 NaN/inf |
| `tests/test_soak.py` | `scripts/soak.sh` 的坏参数拒绝、短线长跑与 CI 门禁（`test_the_soak_script_passes_a_short_run`） |
| `tests/test_audit_regression.py` | 全项目审计回归：非 UTF-8 uevent、HID 帧边界、EBADF/重复 open、daemon 异常、NaN/FIFO/深层 JSON、原子写权限、黑盒兜底、OCP 非有限值/未定义 enable、BOM、坏阈值、`--once` 契约、release/soak（`test_detect_devices_skips_non_utf8_uevent`、`test_state_update_ignores_non_finite`、`test_once_is_rejected_with_a_mode_that_would_ignore_it`、`test_demo_non_ts_models_do_not_report_zero_fan`） |

`tests/test_docs_consistency.py` 是「文档防伪」：文档里写下的数字与文件名，都由测试去核对一遍。

1. 任何文档写了 `N passed` / `N tests` / `N 个单测` / `N 通过` 就必须等于 `pytest --collect-only` 的真实数字
   （`* tests`、`* 个单测`、`* 通过` 这类写法此前逃过了正则，`git log` 里三个老旧数字就是这么烂掉的）；
2. 引用的 `` `tests/xxx.py` `` 必须存在，§1.1 表里每行至少点名一个真实测试函数（与收集结果核对），
   且每个测试文件都要在表里有一行；
3. 每个测试文件都必须在某处文档里被提到；
4. README 的 Usage 参数清单必须与 `build_parser()` 完全一致（少写/多写都失败）；
5. `__version__` 与 `pyproject.toml` 的 `version` 必须一致（`--version`、`.deb` 控制文件各读一份）；
6. `scripts/build_deb.sh` 的版本必须从 `pyproject.toml` 解析，不得硬编码；
7. 文档引用的「`smoke.sh` 共 N 项」必须等于 `scripts/smoke.sh` 里的 `EXPECTED_TOTAL`
   ——该常量同时会被脚本自己核对，检查项被误删时脚本也会失败。

一条命令跑完整条无硬件链路（三种格式 / 告警 exit 2 及按机型鉴名 / 黑盒 / OCP /
风扇/Zero Fan/蜂鸣器写 / daemon→prometheus+历史 / dashboard HTTP / 3.10 语法），共 58 项，失败即非零退出：

```bash
bash scripts/smoke.sh          # 加 --keep 保留临时目录便于排查
```

它与下面第 1 节的门禁互补：门禁查「代码是否合规」，冒烟查「整条链路是否真的跑得通」。
CI 里两者都会跑。

三条全绿即通过。当前基线：**803 passed**、`ruff check` 全过、`mypy` 10 个文件无问题；
分支覆盖率 **94%**（CI 门限 90%）。

> `ruff format --check .` **可以全仓跑**（CI 也跑）：`protocol.py`/`__init__.py`/`__main__.py`/
> `tests/test_monitor.py` 这四个历史文件混用引号风格，已由 `[tool.ruff.format] exclude` +
> `force-exclude = true` 挡在格式化之外，所以不会产生 churn diff。
> `uv run --group dev ruff format .` 是安全的；这里以前写着「不要全仓跑」，那句话已被上面的
> 配置作废，留着只会让人不敢跑门禁。

## 2. 演示模式（合成电源，无需真机）

`MSI_PSU_DEMO=1` 会挂上一个合成 PSU（`msi_psu_monitor/demo.py`）：5 分钟
idle→满载→idle 循环，零风扇随负载开关，per-pin 电流带轻微不平衡，黑盒里预置两条记录。
**只有设置该环境变量时才会生效**，正常路径完全不受影响。

```bash
export MSI_PSU_DEMO=1
.venv/bin/msi-psu-monitor --once
```

`MSI_PSU_DEMO_MODEL` 可切换成任意受支持机型（默认 `mpg_ai1600ts`），
用于在无硬件时覆盖多轨（P 系）与单轨（Ai1600T）代码路径：

```bash
for model in mpg_ai1600ts mpg_ai1300ts meg_ai1600 ai1300p ai1000p bogus; do
  echo "--- $model ---"
  MSI_PSU_DEMO_MODEL=$model .venv/bin/msi-psu-monitor --once | head -1
done
```

期望：前 5 行分别打出对应机型名（`bogus` 回落 `MPG Ai1600TS (demo)`）；
`ai1300p`/`ai1000p` 额外看到 `Per-rail 12V:` 五条轨与 `CPU`/`GPU` 瓦特，
其余机型没有这两段。

```bash
# MEG P 系：--ocp 输出单多轨模式（1 字节 0xC0），exit 0
MSI_PSU_DEMO_MODEL=ai1300p .venv/bin/msi-psu-monitor --ocp
# MEG Ai1600T：两个 0xC0 视图都不支持，打印原因且 exit 0
MSI_PSU_DEMO_MODEL=meg_ai1600 .venv/bin/msi-psu-monitor --ocp; echo "exit=$?"
```

应看到 `MSI PSU: MPG Ai1600TS (demo)`、`12V-2x6 Status: Normal`、`POWER … (AVG …)`、
`Zero Fan: on    Mode: auto`、`Total energy: 0.0 kWh`。

```bash
.venv/bin/msi-psu-monitor -f json | head -20
```

```bash
.venv/bin/msi-psu-monitor -f prometheus | grep -E 'msi_psu_up|power_avg|status_12v_2x6|zero_fan|total_energy|serial='
# daemon 的 textfile 里也要有 OCP 块（TS 机型 1 + 阈值；MEG 机型只有 available 0）
grep -E 'msi_psu_ocp_available|msi_psu_ocp_pin_point_a' /var/lib/node_exporter/textfile/msi-psu.prom
```

```bash
.venv/bin/msi-psu-monitor --show-log
# demo（MSI_PSU_DEMO=1）下应先出 #1 再出 #2：显示顺序按每条记录自己的累计计数器
# 降序排（固件槽序没有任何可核对的依据），打印出来的 total 值就是顺序本身。
```

`[monitor] no_alerts = yes` 在 CLI（`--no-alerts` 等价）与 daemon 两侧都生效：没有 Status
行、没有 `msi_psu_alert`、没有 `ALERT` 行，且完全不轮询 E1h —— daemon 启动日志里会写一行
说明，「什么都没报」不等于「一切正常」。

```bash
.venv/bin/msi-psu-monitor --fan-duty 75 && .venv/bin/msi-psu-monitor --fan-mode auto
```

### 2.0.1 风扇配置按 Profile 恢复（daemon）

`[fan] mode` 或 `zero_fan` 一旦配置，daemon 每次**打开/重连** PSU 都会重发 41h + F1h
（Zero Fan 则 43h + F1h）并读回校验（MSI Center 接管设备时同样会重新下发 Profile；
PSU 的 41h/43h 能熬过休眠但熬不过断电）。两者都不配置则永不写电源。

```bash
cat > /tmp/fan.conf <<'EOF'
[daemon]
state_dir = /tmp/psu-fan

[fan]
mode = customized
duty = 55
zero_fan = on
EOF
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor-daemon --config /tmp/fan.conf --iterations 2 2>&1 | grep -i fan
```

预期：`Restored the configured fan profile: Zero Fan on, customized duty 55%`
（该行只在读回值与写入值一致时才出现；电源拒写则打 warning 而不中断监控）。

> demo 的风扇状态是**进程内**的，所以不要用另起一个 CLI 进程去读回；
> demo 下的读回校验就是上面那行日志。真机上可用
> `msi-psu-monitor --once`（daemon 未占用设备时）看到 `Mode: customized`。

```bash
# 单进程内直接验证写入 + 读回
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --fan-mode customized --fan-duty 55   # expect: Fan mode: customized   Duty: 55%
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --fan-mode auto                       # expect: Fan mode: auto
```

### 2.0.2 控制写入（Zero Fan / 蜂鸣器 / 单多轨）

demo 可验证写路径与输出语义（真实写入需 root + 真机）：

```bash
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --zero-fan off   # Zero Fan: off（43h + F1h + 42h 读回）
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --buzzer-off     # Buzzer: switch toggled (no read-back)
MSI_PSU_DEMO_MODEL=ai1300p MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --set-rail multi
# ↑ 写 C0h 1 字节 + F1h + 读回；与当前值相同时不重复写，输出 (already set)
```

`--buzzer-off` 在 MSI 的命名里是 **switch** 且没有回读，所以只报告 ACK/toggled，
不宣称"已静音"；第二次调用是否会重新响必须真机确认。

### 2.1 OCP 阈值检视（`--ocp`，只读）

一期需求「OCP 閾值檢視」的落地点。读 0xC0 配置 + 0xC1 状态，只读不改电源设置。

```bash
.venv/bin/msi-psu-monitor --ocp
```

应看到出厂值 `12.0 A / 5.0 A / 20 s / 20 s / 180 s`，各带 `(range …)`，
以及 `Conn1/Conn2` 两行状态 + 每连接器 6 针电流（5 秒均值）。

```bash
.venv/bin/msi-psu-monitor --ocp -f json | python3 -m json.tool | head -20
.venv/bin/msi-psu-monitor --ocp -f prometheus | grep ocp_
```

MEG P（Ai1300P/Ai1000P）应打印 `Multirail OCP (0xC0)` 单/多轨标志并 **exit 0**；
MEG Ai1600T 两个 C0h 视图都没有，应打印「not available on this model」并 **exit 0**——
这是机型事实而非错误，脚本可无条件调用；该分支由 `tests/test_ocp.py` 覆盖：

```bash
uv run --group dev pytest -q tests/test_ocp.py
```

`--ocp` 与 `--once`/`--watch`/`--export`/`--show-log`/`--dashboard`/风扇写互斥（argparse 报错 exit 2）。

### 2.2 OCP 阈值导出/写入/导入（MPG TS；真实保护写）

`--dump-thresholds` 只读；`--ocp-set` / `--load-thresholds` 是**会改写电源保护参数**的写路径
（0xC0 8 字节 + F1h），写后必须读回一致，失败重试 3 次后 exit 1。范围
10-14 A / 4-8 A / 5-30 s / 5-30 s / 30-240 s，越界直接拒绝（不静默 clamp）。无硬件时用
demo/mock 验证命令链路（demo 进程内不落 NVRAM，下次进程仍回出厂值）：

```bash
S=$(mktemp -d)
MSI_PSU_STATE_DIR=$S MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --dump-thresholds
MSI_PSU_STATE_DIR=$S MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --dump-thresholds -f json > /tmp/ocp.json
MSI_PSU_STATE_DIR=$S MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --ocp-set 13,6,10,12,60
MSI_PSU_STATE_DIR=$S MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --load-thresholds /tmp/ocp.json
MSI_PSU_DEMO_MODEL=ai1300p MSI_PSU_STATE_DIR=$S MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --ocp-set 12,5,20,20,180; echo "exit=$?"  # 1：无 8 字节视图
uv run --group dev pytest -q tests/test_ocp.py tests/test_cli_features.py -k 'ocp or threshold'
```

越界/错误输入走 argparse exit 2（例如 `--ocp-set 9,6,10,12,60`）；`--load-thresholds` 的
JSON 范围/未知键错误 exit 1。真机验收清单（§8）必须先导出原值再写，写后核对并恢复。

## 3. 告警路径（exit 2 + stderr 单行）

`MSI_PSU_DEMO_ALERT` 可让一条告警位置 1，取值须是该机型**能报**的名字
（TS：`ocp_12v`/`ocp_pin1..12`/`opp`/`otp`/`fan`；MEG P：再加 `ovp_*`/`uvp_*`/`ocp_12v1..5`/`ac`；
MEG Ai1600T：`ovp_*`/`uvp_*`/`ocp_12v`/`ocp_5v`/`ocp_3v3`/`opp`/`otp`/`fan`/`ac`）。

```bash
MSI_PSU_DEMO_ALERT=fan .venv/bin/msi-psu-monitor --once; echo "exit=$?"
```

预期：stderr 打印 `ALERT [critical] fan: fan blocked, shutdown imminent`，`exit=2`。
`fan` 是唯一的 critical 级，其余为 warning。CLI 单次读把去抖设为 1 次（立即触发）；
daemon 按配置默认连续 2 次命中才触发，避免单次采样抖动误报。

### 3.1 本地阈值早警（`[alerts]`，软件阈值）

`[alerts]` 的 8 个阈值不依赖 E1h；`0` 关闭单项。demo 用低阈值触发（真机默认值见
conf example，真机后调参）：

```bash
cat > /tmp/threshold.conf <<'EOF'
[alerts]
power_w = 50
EOF
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --once --config /tmp/threshold.conf; echo "exit=$?"  # 2
# stderr: ALERT [warning] power_high: ...: measured 87.9, limit 50
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --once -f json --config /tmp/threshold.conf | python3 -m json.tool | grep -A2 threshold
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --once -f prometheus --config /tmp/threshold.conf | grep msi_psu_threshold
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --once --no-alerts --config /tmp/threshold.conf; echo "exit=$?"  # 0
uv run --group dev pytest -q tests/test_daemon.py -k threshold
```

默认值（REQ-14 初值）：1200 W / 70 ℃ / 12 A / 5 A / 50 A / 108.33 A / 22 A / 22 A；
`--dump-config` 可查生效值，0xE0 读失败不会清除已 latched 的阈值告警。

## 4. daemon + 历史 + prometheus + dashboard（一条龙）

```bash
cat > /tmp/demo.conf <<'EOF'
[daemon]
state_dir = /tmp/psu-demo
prom_path = /tmp/psu-demo/msi-psu.prom
sample_interval = 0.1
prom_interval = 0.2
history_interval = 0.2
EOF
```

```bash
rm -rf /tmp/psu-demo && MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor-daemon --config /tmp/demo.conf --iterations 25
```

多轨机型另需确认单轨指标与 CPU/GPU 落盘（`MSI_PSU_DEMO_MODEL=ai1300p`）：

```bash
MSI_PSU_STATE_DIR=/tmp/psu-p MSI_PSU_DEMO_MODEL=ai1300p \
  .venv/bin/msi-psu-monitor-daemon --iterations 3 --prom-path /tmp/psu-p/p.prom
grep -E 'rail_current|cpu_watts|gpu_watts' /tmp/psu-p/p.prom
head -1 /tmp/psu-p/daily-*.log       # 末两列应为 cpu_w,gpu_w
MSI_PSU_STATE_DIR=/tmp/psu-p .venv/bin/msi-psu-monitor --export --from 30m --columns cpu,gpu
```

退出码 0，接着应生成三个文件：

```bash
ls /tmp/psu-demo && head -3 /tmp/psu-demo/msi-psu.prom && cat /tmp/psu-demo/state.json
```

`daily-*.log`（每分钟一行 CSV）、`msi-psu.prom`（原子替换，无 `.tmp` 残留）、
`state.json`（累计 count / 平均功率 / kWh / product / serial）。

```bash
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --export --from 30m --columns all | head -3
```

首行表头固定为 `time,cpu,gpu,12v,5v,3v3,temp,fan,eff`；`cpu`/`gpu` 是瓦特
（CPU=12V2 轨、GPU=12V3+4+5，同 MSI Center），单轨机型（TS / Ai1600T）记 `N/A`。

```bash
MSI_PSU_STATE_DIR=/tmp/psu-demo .venv/bin/msi-psu-monitor --dashboard --port 8899 &
sleep 1
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8899/
curl -s 'http://127.0.0.1:8899/api/history?from=2h' | head -c 200
curl -s 'http://127.0.0.1:8899/api/export?from=2h&columns=temp,fan' | head -2
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8899/nope            # 404
curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:8899/api/history?from=fortnight'  # 400
curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:8899/api/history?from=all'          # 200
chmod 000 /tmp/psu-demo && curl -s -w ' [%{http_code}]\n' http://127.0.0.1:8899/api/state     # 503 + 原因，不是 0 数据
chmod 700 /tmp/psu-demo
python3 -c "import socket;s=socket.create_connection(('127.0.0.1',8899));s.sendall(b'GET http://[/x HTTP/1.1\r\nHost: x\r\n\r\n');print(s.recv(80))"  # 400，不是断连
kill %1
```

读不到 state 目錄時 `/api/*` 回 503 並附原因（頁面本身照樣 200，頁內 JS 會把原因
顯示成 `Data may be stale (…)`）：**「daemon 從沒跑過」與「我讀不到 daemon 的檔案」
不能長得一樣**。

浏览器打开 `http://127.0.0.1:8899/` 可看到 7 条曲线 + Weekly 柱状图；每张卡片
自带 PNG / CSV 导出按钮。只读 `daily-*.log` 与 `state.json`，不碰 hidraw。

## 5. 拔出 / 无设备路径

```bash
.venv/bin/msi-psu-monitor --once; echo "exit=$?"
```

无真机且未开 demo 时应打印 `Error: MSI PSU not found…` 并 `exit=1`。

```bash
.venv/bin/msi-psu-monitor-daemon --iterations 2; echo "exit=$?"
```

daemon 在无设备时应正常空转退出 0（这是 systemd 常驻服务等待热插拔的正常状态）。

## 6. 参数冲突与错误码

```bash
.venv/bin/msi-psu-monitor --export;                    echo "exit=$?"   # 1：缺 --from
.venv/bin/msi-psu-monitor --export --from soon;         echo "exit=$?"   # 1：窗口非法
.venv/bin/msi-psu-monitor --watch 1 -f json;            echo "exit=$?"   # 2：watch 只支持 text
.venv/bin/msi-psu-monitor --port 9000;                  echo "exit=$?"   # 2：--port 需配 --dashboard
.venv/bin/msi-psu-monitor --ocp --watch 1;              echo "exit=$?"   # 2：--ocp 与 watch 互斥
.venv/bin/msi-psu-monitor --watch 0;                    echo "exit=$?"   # 2：间隔必须为正
.venv/bin/msi-psu-monitor --watch 1 -i nan;             echo "exit=$?"   # 2：非有限间隔被拒
.venv/bin/msi-psu-monitor --dashboard --port 99999;     echo "exit=$?"   # 2：端口越界
.venv/bin/msi-psu-monitor --dashboard --export --from 2h; echo "exit=$?" # 2：dashboard 不混动作
.venv/bin/msi-psu-monitor --fan-mode auto --fan-duty 50; echo "exit=$?"  # 2：auto 下 duty 无意义
.venv/bin/msi-psu-monitor --export --from 2h --columns ''; echo "exit=$?" # 1：空列清单
MSI_PSU_DEMO=1 timeout 3 .venv/bin/msi-psu-monitor --watch 1 -O /tmp/frames.log
# ↑ 帧写进 /tmp/frames.log 而不是打屏；exit=124 来自 timeout（等价于 Ctrl-C），不是 0/1/2
.venv/bin/msi-psu-monitor --once -O "";                   echo "exit=$?"   # 2：-O 拿到空路径（$OUT 没设）
.venv/bin/msi-psu-monitor -i 5;                          echo "exit=$?"   # 2：-i 只能配 --watch
.venv/bin/msi-psu-monitor --dashboard -O /tmp/page.html; echo "exit=$?"   # 2：dashboard 没有输出文件
.venv/bin/msi-psu-monitor --dashboard --serial ABC; echo "exit=$?"        # 2：dashboard 读历史不认设备
.venv/bin/msi-psu-monitor --ocp --show-log;             echo "exit=$?"   # 2：两个查询互斥
.venv/bin/msi-psu-monitor --dump-config --once;        echo "exit=$?"   # 2：dump-config 不碰设备
.venv/bin/msi-psu-monitor --ocp-set 9,6,10,12,60;      echo "exit=$?"   # 2：OCP 范围越界
.venv/bin/msi-psu-monitor --dump-thresholds --ocp;     echo "exit=$?"   # 2：两个查询互斥
```

约定：`0` 正常 / `1` 程序或参数错误 / `2` 告警或参数冲突（argparse 用法错误）。

## 7. 打包与发布

源码 .deb、二进制 tar 和 hardware kit 都随附 `CHANGELOG.md`、
`docs/prometheus-rules.yml`、`docs/verify.md` 与配置样例；发布前用
`bash scripts/soak.sh 5000` + `bash scripts/smoke.sh` 复核。

下面两个是**开发/CI 用**的源码包（`Depends: python3`）；官网下载用 §7.1 的自包含产物。

```bash
bash scripts/build_deb.sh
dpkg-deb -c dist/msi-psu-monitor_*_all.deb | awk '{print $6}'
```

应包含 `usr/bin/msi-psu-monitor`、`usr/bin/msi-psu-monitor-daemon`、
`usr/lib/python3/dist-packages/msi_psu_monitor/*.py`、`lib/systemd/system/msi-psu-monitor.service`、
`lib/udev/rules.d/99-msi-psu.rules`、`usr/share/doc/msi-psu-monitor/*`（README / LICENSE /
`protocol.md` / `verify.md` / `requirements-traceability.md` / `msi-psu-monitor.conf.example` / `copyright`）。

同时确认包根目录不是 0700（`mktemp` 会给 0700 而 `dpkg-deb` 原样收录，脚本已 `chmod 755` 修掉）：

```bash
dpkg-deb -c dist/msi-psu-monitor_*_all.deb | head -1   # 期望 drwxr-xr-x ... ./
```

```bash
rm -rf /tmp/debroot && mkdir -p /tmp/debroot
dpkg-deb -x dist/msi-psu-monitor_*_all.deb /tmp/debroot
PYTHONPATH=/tmp/debroot/usr/lib/python3/dist-packages /tmp/debroot/usr/bin/msi-psu-monitor --version
```

（直接从解包目录跑需要 `PYTHONPATH`；装到真实根目录后 `/usr/lib/python3/dist-packages` 在默认路径里，无需设置。）

打包里那两个「只在安装时才被检查」的文件，用真正会拒绝它们的工具验一遍（smoke 的 [10] 也跑这两条）：

```bash
systemd-analyze verify systemd/msi-psu-monitor.service   # 退出码 0；坏 ExecStart 会非零
udevadm verify systemd/99-msi-psu.rules                  # Success: 1  Fail: 0（systemd ≥ 250）
```
安装路径的完整性由 `tests/test_packaging.py` 机器把关（unit 的 `--config` 指向的文件必须有人装、
两个安装器都要落 `/etc/msi-psu-monitor.conf`、`install.sh` 不得覆盖用户改过的那份、
示例文件装上去不改变任何取值、staged 文件必须带 `-m` 模式）。smoke 的 [10] 另外用
`umask 077` 构建一次 `.deb`，再从 `dpkg-deb -c` 读回模式：`cp` 而不是 `install -m` 会让产物
变成 root-only，而 udev 的 `uaccess` 本来就是给非 root 会话用的：

```bash
(umask 077; bash scripts/build_deb.sh)
dpkg-deb -c dist/msi-psu-monitor_*_all.deb | grep -E 'protocol|\.service'   # 期望 -rw-r--r--
dpkg-deb -c dist/msi-psu-monitor_*_all.deb | grep etc/msi-psu-monitor.conf  # 全注释的 conffile
```

`/etc/msi-psu-monitor.conf` 里的每一个值都是注释掉的，所以装上它不改变任何行为；
unit 也不钉 `--config`，直接走 `/etc` → `~/.config` 搜索路径，机器上没人配置过也能启动。
daemon 被显式喂了一个不存在的 `--config` 时只打一行 `Error: ...` 并 exit 1（不是 traceback，
否则 `Restart=always` 会每 `RestartSec` 刷一次堆栈）：

```bash
msi-psu-monitor-daemon --config /nonexistent.conf; echo $?   # 一行错误，exit 1
```

### 7.1 自包含二进制（官网下载形态）

官网发布物不要求目标机安装 Python。构建机必须是 Ubuntu 22.04（glibc 2.35）；在更新的
系统上构建会被 `build_binary.sh` 拒绝（`ALLOW_NEWER_GLIBC=1` 仅供本地烟测）。Phase 3 已用
Ubuntu 22.04 rootfs/chroot 构建并在 22.04 内运行通过（见 `docs/testing/test-report.md` §10.8）；
官方发布仍须 CI provenance：

```bash
uv sync --group dev --group build
bash scripts/build_binary.sh
bash scripts/build_deb_binary.sh
tar tzf dist/msi-psu-monitor_*_linux_x86_64.tar.gz | head
sha256sum -c dist/msi-psu-monitor_*_linux_x86_64.tar.gz.sha256
env -i PATH=/usr/bin:/bin HOME=/tmp MSI_PSU_DEMO=1 \
  ./dist/bin/linux-x86_64/msi-psu-monitor --once
dpkg-deb -f dist/msi-psu-monitor_*_amd64.deb Depends
# 期望：libc6 (>= 2.35), zlib1g —— 没有 python3
ldd ./dist/bin/linux-x86_64/msi-psu-monitor   # 不应出现 libpython
```

`env -i` 是关键：它证明二进制没有借用开发机的 `.venv` 或 PATH 里的 Python。tarball 内的
`install.sh` 只做 `install -m 755` + udev/systemd，不调用 python3/pip；`uninstall.sh`
默认保留配置与 `/var/lib/msi-psu-monitor`，`--purge` 才删除。正式发布由
`.github/workflows/release.yml` 在 `ubuntu-22.04` / `ubuntu-22.04-arm` 上构建并上传
`SHA256SUMS` 与 `SBOM-<arch>.json`；详细矩阵见 [release.md](release.md)，安全/支持/
应急流程见 [SECURITY.md](../SECURITY.md)、[support.md](support.md)、
[incident-response.md](incident-response.md)。

## 8. 真机到达后（唯一待补）

完整的机器准备、一键 `setup.sh` / `acceptance.sh` / 证据打包说明见
[hardware-acceptance.md](hardware-acceptance.md)；下面是手工验收清单。

```bash
sudo install -m 644 systemd/99-msi-psu.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=hidraw
sudo cp systemd/msi-psu-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now msi-psu-monitor
journalctl -u msi-psu-monitor -f
```

逐项验收：

1. `sudo msi-psu-monitor --once` 与 MSI Center / Afterburner 对照，误差 <1%；
2. 44B/62B `0xE0` 抓包确认 `BULK_*` 偏移（对照 `docs/protocol.md`）；
3. Ai1300TS（PID `0xAA6F`）能被扫到并正确判变体；
4. `--fan-duty 0/50/100` 写后读回一致，`F1h` 保存后断电重启仍生效；
4b. 配 `[fan] mode = customized` + `duty` 后重启 daemon，`journalctl` 出现
   `Restored the configured fan profile`，且电源侧设置确实被改写；
5. 满载下单针 >12A 触发 `ocp_pinN`，针差 >5A 触发 `pin_imbalance`；
6. 运行中拔插 USB：daemon 连续 5 次读失败后重扫并自动重连（`journalctl` 可见 `rescanning`）；
7. 72h 烤机：`state.json` 的 `energy_wh` 与插座功率计积分值偏差可接受；
8. `--ocp` 读出的 4 个阈值与 MSI Center 界面 / 出厂规格一致（12A/5A/20s/180s），
   且 `ConnN` 状态与 `--once` 的 `12V-2x6 Status` 行不矛盾；
9. `--ocp` 在 MEG P 系（`0x56D4`/`0xE749`）上输出 1 字节单多轨标志（`per-rail protection`
   或 `single combined-rail`），与 MSI Center 的对应开关一致，不产生 NAK 重试或超时；
10. `--ocp` 在 MEG Ai1600T（`0xC9EB`）上打印「not available」并 exit 0（两个 `0xC0` 视图
   都不支持），不产生 NAK 重试或超时；
11. `--zero-fan on/off` 写后读回一致（42h byte 4），`F1h` 保存后断电重启仍生效；
    `--buzzer-off` 在 12+4 OCP 蜂鸣触发时能让蜂鸣停止（C2h 无回读，只看 ACK 与听感）；
    再执行一次，确认它是「静音」还是 MSI 命名的「switch」（第二次是否会重新响）；
12. `--set-rail multi` / `--set-rail single` 在 MEG Ai1300P（`0x56D4`）上读回一致，
    断电重启后模式保持；Ai1000P（`0xE749`）同样验证；MPG TS 和 Ai1600T 应拒绝并
    exit 1（机型门），且不产生错误寄存器写入；
13. `--set-rail` 切换前后 `--ocp` 的 multirail 标志与读回一致；切换后的 OCP 行为
    （单轨总电流 vs 各轨独立限流）与 MSI Center 的 Multi Rail/Single Rail 一致；
13b. OCP 阈值写（仅 MPG TS）：先 `--dump-thresholds -f json > before.json` 留底；
    用 `--ocp-set` 写一组远离当前值的合法值（如 13,6,10,12,60），输出必须读回一致且
    F1h 后断电重启仍保持；再用 `--load-thresholds before.json` 恢复。写前后 `--ocp` 的
    4 个阈值必须与 MSI Center 一致。越界值应被 CLI 拒绝（exit 2），不能等到电源侧 clamp。
    常规运行不要自动改保护点；
14. MEG Ai1300P 上 `AC Input`（0x20）接近市电电压（220-240 V），MPG TS 上不出现该行
    且不产生 NAK 重试；Ai1600T 若 NAK 则自然省略，不算失败；
15. 触发一次真实告警并恢复：`alerts-YYYYMMDD.log` 先出现 `ALERT` 行、恢复后出现
    `RECOVERED` 行，`--show-alert-log` 能原样打印；5 MiB 轮转与 30 天清理不丢当天文件；
16. daemon 运行时 dashboard 的曲线每秒前进（`/api/live` 200），停 daemon 后 10 s 内
    `/api/live` 变 503、页面显示 stale；`[daemon] live_snapshot = no` 时回落到分钟级；
17. `systemd-analyze security msi-psu-monitor` 无 PrivateDevices、无多余 capability，
    `CapabilityBoundingSet` 为空时 hidraw 仍能打开。
