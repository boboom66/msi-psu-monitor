# 无硬件自检手册

> 没有真机也能验证 CLI、告警、daemon、历史落盘、prometheus 与 dashboard 全链路。
> 下面每条命令都已在 `/usr/bin/python3` 3.12 + `uv` 环境下实跑通过。
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

现在 `ruff format --check .` 也安全了（`[tool.ruff.format] exclude` +
`force-exclude = true` 把 4 个历史文件挡在外面），CI 已把它加进门禁：

```bash
uv run --group dev ruff format --check .
```

### 1.1 测试模块清单

| 模块 | 覆盖 |
|------|------|
| `tests/test_protocol.py` | 命令帧拼装、握手、NAK 处理、`lin11_to_int` 标度 |
| `tests/test_protocol_lin11.py` | LINEAR11 原始向量（含 exp −4 / −7 边界与无符号尾数） |
| `tests/test_psu_sensors.py` | 62 B / 40 B / 20 B 三种载荷解析、P 系五轨、未知机型拒解 |
| `tests/test_alerts.py` | 阈值判定、`consecutive_required` 去抖、严重度、告警行格式 |
| `tests/test_state.py` | 累计统计、`rail_watts()`、历史追加/裁剪、`--export` 列 |
| `tests/test_config.py` | INI 解析、`[daemon]`、`[fan]` 段与非法值回落；显式 `--config` 缺失/格式错误必须报错而非静默用默认值；越界 port 回落 |
| `tests/test_monitor_format.py` | text / json / prometheus 三种 formatter 输出串 |
| `tests/test_cli_alerts.py` | CLI 告警路径与退出码 2 |
| `tests/test_cli_features.py` | `--watch`/`-O`/`--serial`/`--show-log`/`--fan-*`/`--export`/互斥校验 |
| `tests/test_ocp.py` | 0xC0 阈值 / 0xC1 状态 / 单多轨标志的三格式输出与机型门 |
| `tests/test_daemon.py` | 采样节拍、原子写、重扫、历史、风扇 Profile 恢复；`OSError`（拔插）计入重扫而非崩主循环；只答 ident 的样本判为读失败 |
| `tests/test_dashboard.py` | HTTP 端点、历史/状态载荷、CSV 导出、HEAD 与错误码一致；端口被占时一行错误 + exit 1 |
| `tests/test_demo.py` | 合成电源、5 机型切换、告警位注入 |
| `tests/test_schema.py` | JSON / prometheus 输出结构契约 |
| `tests/test_monitor.py` | 遗留冒烟（兼容旧接口，勿删） |
| `tests/test_pid_consistency.py` | 五处 USB PID 列表 + README 载荷大小一致性 |
| `tests/test_stdlib_only.py` | `python -I` 子进程导入全部模块（零第三方依赖） |
| `tests/test_docs_consistency.py` | 文档里的用例数、测试文件名、CLI 参数清单、版本号双重来源不得与事实不符 |

`tests/test_docs_consistency.py` 是这轮新加的「文档防伪」，四项检查：

1. 任何文档写了 `N passed` 就必须等于 `pytest --collect-only` 的真实数字；
2. 引用的 `` `tests/xxx.py` `` 必须存在；
3. 每个测试文件都必须在某处文档里被提到；
4. README 的 Usage 参数清单必须与 `build_parser()` 完全一致（少写/多写都失败）。

一条命令跑完整条无硬件链路（三种格式 / 告警 exit 2 及按机型鉴名 / 黑盒 / OCP /
风扇写 / daemon→prometheus+历史 / dashboard HTTP / 3.10 语法），共 39 项，失败即非零退出：

```bash
bash scripts/smoke.sh          # 加 --keep 保留临时目录便于排查
```

它与下面第 1 节的门禁互补：门禁查「代码是否合规」，冒烟查「整条链路是否真的跑得通」。
CI 里两者都会跑。

三条全绿即通过。当前基线：**301 passed**、`ruff check` 全过、`mypy` 10 个文件无问题。

> `ruff format --check` **不要全仓跑**：`protocol.py`/`__init__.py`/`__main__.py`/`tests/test_monitor.py`
> 等历史文件混用引号风格，全仓 format 会产生大量无意义 diff。只对本次改动的文件跑。

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
.venv/bin/msi-psu-monitor -f prometheus | grep -E 'power_avg|status_12v_2x6|zero_fan|total_energy|serial='
```

```bash
.venv/bin/msi-psu-monitor --show-log
```

```bash
.venv/bin/msi-psu-monitor --fan-duty 75 && .venv/bin/msi-psu-monitor --fan-mode auto
```

### 2.0.1 风扇配置按 Profile 恢复（daemon）

`[fan] mode` 一旦配置，daemon 每次**打开/重连** PSU 都会重发 41h + F1h 并读回校验
（MSI Center 接管设备时同样会重新下发 Profile；PSU 的 41h 能熬过休眠但熬不过断电）。
不配置 `mode` 则永不写电源。

```bash
cat > /tmp/fan.conf <<'EOF'
[daemon]
state_dir = /tmp/psu-fan

[fan]
mode = customized
duty = 55
EOF
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor-daemon --config /tmp/fan.conf --iterations 2 2>&1 | grep -i fan
```

预期：`Restored the configured fan profile: customized duty 55%`
（该行只在读回值与写入值一致时才出现；电源拒写则打 warning 而不中断监控）。

> demo 的风扇状态是**进程内**的，所以不要用另起一个 CLI 进程去读回；
> demo 下的读回校验就是上面那行日志。真机上可用
> `msi-psu-monitor --once`（daemon 未占用设备时）看到 `Mode: customized`。

```bash
# 单进程内直接验证写入 + 读回
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --fan-mode customized --fan-duty 55   # expect: Fan mode: customized   Duty: 55%
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --fan-mode auto                       # expect: Fan mode: auto
```

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

非 12V-2x6 机型（MEG 系列）应打印「not available on this model」并 **exit 0**——
这是机型事实而非错误，脚本可无条件调用；该分支由 `tests/test_ocp.py` 覆盖：

```bash
uv run --group dev pytest -q tests/test_ocp.py
```

`--ocp` 与 `--watch`/`--export`/`--show-log`/`--dashboard`/风扇写互斥（argparse 报错 exit 2）。

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
kill %1
```

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
.venv/bin/msi-psu-monitor --ocp --show-log;             echo "exit=$?"   # 2：两个查询互斥
```

约定：`0` 正常 / `1` 程序或参数错误 / `2` 告警或参数冲突（argparse 用法错误）。

## 7. 打包

```bash
bash scripts/build_deb.sh
dpkg-deb -c dist/msi-psu-monitor_1.0.0_all.deb | awk '{print $6}'
```

应包含 `usr/bin/msi-psu-monitor`、`usr/bin/msi-psu-monitor-daemon`、
`usr/lib/python3/dist-packages/msi_psu_monitor/*.py`、`lib/systemd/system/msi-psu-monitor.service`、
`lib/udev/rules.d/99-msi-psu.rules`、`usr/share/doc/msi-psu-monitor/*`（README / LICENSE /
`protocol.md` / `verify.md` / `requirements-traceability.md` / `msi-psu-monitor.conf.example` / `copyright`）。

同时确认包根目录不是 0700（`mktemp` 会给 0700 而 `dpkg-deb` 原样收录，脚本已 `chmod 755` 修掉）：

```bash
dpkg-deb -c dist/msi-psu-monitor_1.0.0_all.deb | head -1   # 期望 drwxr-xr-x ... ./
```

```bash
rm -rf /tmp/debroot && mkdir -p /tmp/debroot
dpkg-deb -x dist/msi-psu-monitor_1.0.0_all.deb /tmp/debroot
PYTHONPATH=/tmp/debroot/usr/lib/python3/dist-packages /tmp/debroot/usr/bin/msi-psu-monitor --version
```

（直接从解包目录跑需要 `PYTHONPATH`；装到真实根目录后 `/usr/lib/python3/dist-packages` 在默认路径里，无需设置。）

## 8. 真机到达后（唯一待补）

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
   都不支持），不产生 NAK 重试或超时。
