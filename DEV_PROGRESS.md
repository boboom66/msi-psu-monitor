# msi-psu-monitor 改造开发进度（2026-10-16）

> 本文件是开发会话交接点。新会话先读本文件，再读 `psu-file/01_需求文档/` 三份冻结文档。
> 仓库：`/home/timzhang/projects/project/msi-psu-monitor`（对开源套件 HesiPullupTimbo/msi-psu-monitor v1.0.0 的官方改造版）。

## 一、本会话已完成（2026-10-16）

1. **抢救代码落库**：从 `~/.claude/transcripts/ses_ecc3bac94ffeHbX42QdWWWdD10.jsonl` 抢救的 v2 代码已合入仓库：
   - `msi_psu_monitor/{protocol,monitor,alerts,config}.py`（含 P0 修复：FW ASCII、序列号去长度、AA6F、未知变体拒解、E1/C1/黑盒读取）
   - `tests/`（test_protocol、test_psu_sensors、test_alerts、test_cli_alerts、test_config、test_monitor、test_schema 等）
   - `systemd/99-msi-psu.rules`（双 PID uaccess）、`.github/workflows/ci.yml`
2. **mantissa 符号问题定论并修复**：REV6 原文 "Signed 5 bits / Unsigned 11 bits"（指数有符号、尾数无符号），MSI Center `ValueCalc` 同为无符号。全部 lin11 解码改为 `signed=False`（fan 本来就是）。**59 测试全绿**。
3. **protocol.py 扩展**（一期新功能底层）：
   - `detect_devices()` 返回全部匹配设备（多电源）；`detect_device()` 保留取第一个
   - `DeviceBusyError` + `HIDDevice.open()` 加 `flock LOCK_EX|LOCK_NB`（独占，REQ-17/18）
   - `HIDDevice.write_command()`（0x50 写，NAK→None）
   - `MSIPSU.read_fan_setting()`（41h: mode,duty）、`read_fan_duty()`（42h 四元组）、`set_fan_mode(mode,duty)`（写 41h+存 F1h）、`read_ocp_thresholds()`（C0h 8B, LINEAR11）
   - `MSIPSU._lin11_float()`（OCP 阈值解码）

## 二、冻结决策速查（已拍板，勿改）

- **风扇 CLI**：`--fan-mode auto|customized` + `--fan-duty 0-100`（**单值**，无 min/max；REV6 41h 只有 `[Mode,0,Duty]`）；写完读回验证，保存发 `[0x50 0xF1 0x00]`，超限电源自动钳制
- **验证策略**：先封"规格版"（L1：本地测试+打包可交付），L2 真机验证等样机（脚本我方备好）
- **告警**：阈值按 MSI Center（单针 12A / 针差 5A / 触发 20s / 警告 180s）；exit 0/1/2，连续超限 2 次才算；只 stderr + exit 2，无桌面弹窗
- **单 daemon**：flock 独占 hidraw；1s 判警 + 30s 原子写 `.prom`（`.tmp+os.replace`）+ 1 分钟追加 `daily-YYYYMMDD.log`；**废弃 timer 方案**
- **dashboard**：stdlib-only，`127.0.0.1:8899`（`--port` 可改），7 实时曲线 + Weekly，页内导 PNG/CSV，只读 daemon 数据不碰 hidraw，关即停
- **--export**：9 列全量版（全选/CPU/GPU/12V/5V/3.3V/温度/风扇/效率），读 `daily-*.log`，TS 上 CPU/GPU 记 N/A；`--from` 支持 `m/h/d`（如 `2h`）；非法 `--columns` 报错 exit 1
- **--watch [秒]** 秒数合一（`nargs='?' const=2.0`），`-i` 保留兼容
- **AVG/kWh**：落盘续算（重启不丢，保留 30 天）；json 加 `power_avg/efficiency_avg/status`
- **--serial**：多电源按序列号挑，默认第一颗，对不上报错打印列表
- **text 输出**（对齐冻结样例）：`Vendor/Firmware/Serial` 三行 + 三组电压电流 + per-pin 12 针 + `12V-2x6 Status` + `POWER/EFF (AVG …)` + `TEMP/FAN` + `Zero Fan: on Mode: customized` + `Uptime/Total uptime/Total energy`
- **prometheus 追加**：`power_avg/efficiency_avg/status_12v_2x6{status}/zero_fan{state}/total_energy_kwh`，`msi_psu_info` 加 serial 标签
- **帧/格式**：protect HID framing（64B、250ms、2B echo、NAK 0xFE）；LINEAR11 小端；针序 12V5 Pin1-6 + 12V3 Pin7-12
- 打包：`.deb`，`Depends: python3 (>=3.10)`，不内嵌 Python；udev 放普通用户（daemon 仍 root）

## 三、待办（下一步开发顺序）

1. **monitor.py 改造**（重点）：
   - CLI 参数补齐：`--fan-mode/--fan-duty`、`--serial`、`--export/--from/--columns`、`--watch [秒]` 合一、`--dashboard/--port`
   - text 格式对齐冻结样例；json 加 avg/status 等字段；prometheus 加指标
   - 风扇写 + 读回验证；dashboard 模式启动
2. **新模块**：
   - `state.py`（或 storage）：AVG 累计平均（`avg += (x-avg)/n` 不清零）、kWh 积分（`wh += w*dt/3600`）落盘 `/var/lib/msi-psu-monitor/`（或 XDG 回退），保留 30 天
   - `daemon.py`：常驻 daemon（1s 判警、30s 原子写 prom、1min 写 daily log、flock、重握手重试、失败重扫、设备拔出重连）
   - `dashboard.py`：stdlib `http.server`，内嵌 HTML/JS canvas，7 曲线 + Weekly，PNG/CSV 导出
3. **systemd**：daemon service（替换 `msi-psu-monitor.timer`，定时器方案废弃）；service 跑 root
4. **打包**：`scripts/build_deb.sh`（或 Makefile）产 `.deb`（DEBIAN/control、postinst：建 `/var/lib/node_exporter`、reload udev、enable daemon 手动启用说明）
5. **测试**：给新功能补测试（fan 写、export 列、AVG/kWh 计算、daemon 逻辑、状态文件轮转）
6. **文档**：`docs/protocol.md`（补 41h/42h/43h/F1h/C0h 章节 + multirail 修正）、`README.md`、`msi_psu_monitor/AGENTS.md`（更新约定：mantissa 无符号、flock、新的模块结构）

## 四、验收（封规格版）定义

- `pytest` 全绿 + `ruff`/`python -m py_compile` 通过
- `.deb` 可构建（dpkg-deb），`dpkg -c` 校验含：CLI、daemon、udev、systemd、docs
- 所有冻结文档中的 CLI/text/json/prometheus 样例与实现输出一致（本地 mock 验证）
- 真机清单（L2）另备：44B/62B 抓包、AA6F、风扇写读回、拔插恢复、对照 MSI Center ≤1%、72h 烤机

## 五、关键路径

- 原改造台账（含全部 P0-P14 明细）：Obsidian Vault `Projects/msi-psu-monitor需求精华.md`
- 抢救源：`~/.claude/transcripts/ses_ecc3bac94ffeHbX42QdWWWdD10.jsonl`
- REV6 规格全文提取文本：`/tmp/opencode/rev6.txt`（重启会丢，重要时重新提取）
- 参考实现副本：`psu-file/03_参考实现/msi-psu-monitor/`（与上游 v1.0.0 逐文件一致）
