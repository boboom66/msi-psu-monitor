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

三条全绿即通过。当前基线：**145 passed**、`ruff check` 全过、`mypy` 10 个文件无问题。

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

## 3. 告警路径（exit 2 + stderr 单行）

`MSI_PSU_DEMO_ALERT` 可让任意一条告警位置 1（取值见 `alerts.py` 的 `ALERT_DESCRIPTIONS`）。

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

退出码 0，接着应生成三个文件：

```bash
ls /tmp/psu-demo && head -3 /tmp/psu-demo/msi-psu.prom && cat /tmp/psu-demo/state.json
```

`daily-*.log`（每分钟一行 CSV）、`msi-psu.prom`（原子替换，无 `.tmp` 残留）、
`state.json`（累计 count / 平均功率 / kWh / product / serial）。

```bash
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --export --from 30m --columns all | head -3
```

首行表头固定为 `time,cpu,gpu,12v,5v,3v3,temp,fan,eff`；7ZPU 单轨机型 `cpu`/`gpu` 记 `N/A`。

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
```

约定：`0` 正常 / `1` 程序或参数错误 / `2` 告警或参数冲突（argparse 用法错误）。

## 7. 打包

```bash
bash scripts/build_deb.sh
dpkg-deb -c dist/msi-psu-monitor_1.0.0_all.deb | awk '{print $6}'
```

应包含 `usr/bin/msi-psu-monitor`、`usr/bin/msi-psu-monitor-daemon`、
`usr/lib/python3/dist-packages/msi_psu_monitor/*.py`、`lib/systemd/system/msi-psu-monitor.service`、
`lib/udev/rules.d/99-msi-psu.rules`、`usr/share/doc/msi-psu-monitor/*`。

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
5. 满载下单针 >12A 触发 `ocp_pinN`，针差 >5A 触发 `pin_imbalance`；
6. 运行中拔插 USB：daemon 连续 5 次读失败后重扫并自动重连（`journalctl` 可见 `rescanning`）；
7. 72h 烤机：`state.json` 的 `energy_wh` 与插座功率计积分值偏差可接受。
