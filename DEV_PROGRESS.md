# 开发进度

> 最后更新：v2 改造「一期」功能全部落地（CLI/daemon/dashboard/状态/打包/systemd/文档/测试）。
> 验证方式见 [`docs/verify.md`](docs/verify.md)（无硬件可全链路自检）。

## 已完成

### 一期功能（全部完成）

| 模块 | 内容 |
|------|------|
| **CLI** | `--once`/`--watch [秒]`/`-f text,json,prometheus`/`-O`/`--serial`/`--show-log`/`--ocp`/`--export --from 30m\|2h\|7d --columns`/`--dashboard [--port]`/`--no-alerts`/`--config`/`-v`/`-q`/`--version`；退出码 0/1/2（2 兼含 argparse 用法错误） |
| **风扇控制** | `--fan-mode auto\|customized`、`--fan-duty 0-100`（41h 写 + F1h 保存 + 3 次读回验证）；41h/42h 读显示 |
| **风扇 Profile 恢复** | `[fan] mode = auto\|customized` + `duty`：daemon 每次打开/重连 PSU 重发 41h + F1h 并读回校验（对应需求「風扇配置按 Profile 恢復」）；不配置则永不写电源，拒写只 warning |
| **告警** | E1h 告警位图 + 12V-2x6 每针软件镜像（单针 ≥12A、同 6 针连接器针差 >5A）；`AlertEngine` 去抖（默认连续 2 次）；`ALERT [severity] name: desc` 走 stderr，exit 2 |
| **状态落盘** | `state.json`（AVG 功率/效率、`Time_Daily`/`Time_Total`、kWh 冻结积分、30 天日桶）+ `daily-YYYYMMDD.log`（1 分钟 1 行 CSV，30 天保留）；全部 `.tmp` + `os.replace` 原子写 |
| **多轨机型** | ai1000p/ai1300p 的 12V1..12V5 单轨读数（text/json/prometheus 三处均出）+ CPU/GPU 瓦特（CPU=12V2、GPU=12V3+4+5，同 MSI Center），`--export --columns cpu,gpu` 在单轨机型仍记 `N/A` |
| **daemon** | `msi-psu-monitor-daemon`：1s 采样判警、30s 原子写 prometheus、60s 追加历史、1h 轮转；连续 5 次读失败重扫设备；SIGINT/SIGTERM 干净退出 |
| **dashboard** | `--dashboard` 起 stdlib `ThreadingHTTPServer`，仅绑 `127.0.0.1:8899`；7 条实时曲线 + 每周能量柱状 + 每图 PNG/CSV 导出；端点 `/`、`/api/history`、`/api/state`、`/api/export` |
| **demo 模式** | `MSI_PSU_DEMO=1` 合成 PSU（5 分钟 idle→满载→idle 循环、零风扇随负载、per-pin 轻不平衡、黑盒预置 2 条）；`MSI_PSU_DEMO_ALERT=<name>` 卡告警位；`MSI_PSU_DEMO_MODEL=<variant>` 可切全部 5 机型（多轨/单轨路径无硬件可达） |
| **OCP 检视（只读）** | `--ocp`：MPG TS 出 0xC0 阈值（单针/针差/触发/针差触发/警告 + 可设范围）与 0xC1 实时状态（每连接器状态码 + 运行/总计时 + 6 针 5 秒均值）；MEG P 系出 1 字节 0xC0 单多轨模式（二期只读项）；MEG Ai1600T 打印说明并 exit 0；三格式均支持 |
| **打包** | `scripts/build_deb.sh` → `dist/msi-psu-monitor_1.0.0_all.deb`（2 个 console script、systemd unit、udev 规则、文档；postinst 自动 reload + enable） |
| **systemd** | `msi-psu-monitor.service`（`Type=simple` + `Restart=always` + `StateDirectory`，**不加 `PrivateDevices`**）；旧 timer 方案已废弃并删除文件 |
| **文档** | `README.md`、`AGENTS.md`、`msi_psu_monitor/AGENTS.md`、`docs/protocol.md`、`docs/verify.md`、`docs/msi-psu-monitor.conf.example` |

### 数据正确性修复（P0，已冻结）

- **FW revision**：TS 按 2 字节 ASCII 透传（`1.0`），非可打印才回退；废弃旧的 `<I` 十进制拼法。
- **Serial**：TS 的首字节是长度前缀，按长度切片，不再把长度当号码。
- **PID**：补齐 `0xAA6F`（Ai1300TS），共 5 个 `0db0:*`。
- **未知机型拒解**：产品字符串匹配不上时抛错，不再猜布局。
- **变体分派**：按产品字符串子串（`Ai1600TS` → mpg 先于 `Ai1600` → meg，然后 `Ai1300`/`Ai1000`），**不按 PID**。
- **0xC0 是重载寄存器**：同一地址既是 `MULTIRAIL_OCP`（1B，`==2`，仅 MEG P 系）又是
  `OCP12V2x6_CONFIG`（8B，仅 MPG TS 系），两条命令的机型门互补；MEG Ai1600T 两条都不支持。
  因此 `--ocp` 按变体判定能力，绝不按载荷长度猜（`CPSU.cs:823-832` vs `840-856`）。
- **0xC1 同样重载**：InfoID `0x00` 为 42B OCP 实时状态，InfoID `1..10` 为黑盒日志。
- **LINEAR11 尾数符号**：REV6 无符号，MSI 的 `ValueCalc` 也是 `Mantissa = ((High & 7) << 8) + Low`（不扩展符号），因此 `lin11_to_int` 的默认值
  改为 `signed=False`（此前默认 `True` 是个陷阱：任何漏传实参的新调用点都会静默偏离参考实现）。
  调用点四舍五入（V/A 3dp、W 1dp、% 2dp、RPM int）。
- **标度真义**：MSI 的 `ValueCalc` 就是 `mantissa * 2**exponent`（`CPSU.cs:1248`），单位由指数决定；11 位尾数意味着 3.3 V 只能靠负指数表示（−7 → 3.296 V），不可写成 3300 mV。
- **变体最小载荷**：原先 44B 硬门槛会把 **Ai1600T（20B 载荷）整段拒掉**；现按 `VARIANTS[...]['payload_size']`（TS 44 / P 40 / 1600T 20）裁定。MSI 的 `i = 10` 只是输出数组下标，不是载荷前缀跳过。
- **42h 风扇占空比的后两字节只有 TS 系有定义**：MSI Center 在 MEG 机型上读完
  前两字节就返回（`CPSU.cs:810`），此前本实现对全部机型读第 3/4 字节，于是
  MEG 上的 `Zero Fan` 状态是**编造**出来的（拿未定义字节当开关）；现 MEG 报
  `None`（text 显示 `unknown`），TS 仍出四元组。另按 MSI 的 `Mode == 3 ? RxData[5] : 0`
  只在 customized 模式导出 `fan_duty`（auto 模式下残存的设定值不是风扇实际转速）。
- **载荷长度不对时不再只会说「读取失败」（本轮）**：`get_sensors()` 现在区分三件事——
  设备没应答（`read_all()` 返回 `None`，保持可容忍的瞬时态）、**应答了但长度不对**
  （新增 `payload_error`，带上「got 20 of 44 bytes」这类实测数字）、机型未知（变体判定
  前移，直接 `error` 拒解，不再因为「长度也不够」而混成同一个笼统提示）。`run_once`
  以 exit 1 报出真实原因，`--watch`/daemon 各自沿用既有的「容忍一帧 / 计入重扫」策略但
  打印同一条具体原因；text 输出也带上该行，让 `-O` 存下来的产物能自证。
  动机：机型误判（例如产品串含 `MPG Ai1600` 却是 20 字节的 MEG 布局）**不会**产出错数据
  （长度门先拒），但以前只能看到「0xE0 read failed」，等于把一个可诊断的错配说成掉线。
- **`StateDirectory=` 与代码里的状态目录不再各说各话（本轮）**：`state.default_state_dir()`
  改为认 systemd 导出的 `STATE_DIRECTORY`（多个用 `:` 分隔时取第一个），优先级
  `MSI_PSU_STATE_DIR` > `STATE_DIRECTORY` > `/var/lib/msi-psu-monitor` > XDG。以前两者
  只因为**名字恰好相同**才对得上；一旦 unit 里改了目录名（或改成用户级 `systemd --user`
  + `StateDirectory=`），代码会退到 `~/.local/state`，而 unit 的 `ProtectHome=yes` 让家目录
  根本不可写——累计电量与历史会**静默不落盘**。
- **配置文件不再「静默失效」或「把 CLI 打断」（本轮）**：
  - `--config /typo.conf` 以前被 `configparser.read()` 悄悄忽略 → 用户按自己写的配置
    期待行为，实际跑的是内置默认值（`state_dir` 尤其危险：daemon 会写到别处）。现
    显式指定却读不到时抛 `ConfigError`，`main()` 干净地 exit 1 并报出文件名；
    格式错误的 INI（缺 section 头之类）同理，不再冒 traceback。
  - `[monitor] format = xml` 这种自由文本值以前直接进 `FORMATTERS[...]` → KeyError 炸在
    读取中途。现 `resolve_format()` 白名单校验，未知值告警并回落 text（与 `[fan] mode`
    的既有处理方式一致），且解析发生在 `setup_logging()` **之后**，告警才真的看得见。
  - `[daemon] port` 越界（如 99999）会让 bind 抛 `OverflowError`；现配置层钳回默认值，
    `dashboard.serve()` 也把 bind 失败（端口被占、特权端口）变成一行错误 + exit 1。
- **拔插不再拖垮 daemon（本轮）**：`HIDDevice.send_command()` 里的 `os.write`／`os.read`／
  `select` 全裸奔——电源一拔就 `OSError(ENODEV)` 穿到 `sample()` → `tick()`（只挡了
  prom/history 的写盘）→ 主循环直接崩。systemd 的 `Restart=always` 会把它伪装成「正常」，
  但内存里的告警 debounce 与能量积分每次都清零，而「连续 5 次失败才重扫」这条验收项
  永远走不到。现全部设备错误统一映射为 `None`（等同 NAK），并在 `sample()` 里补
  `OSError` 兜底；`--watch` 与 `--once` 也各自给出可读结论。
- **「只答 ident、不答载荷」不再算成功**：`get_sensors()` 在 0xE0 读失败时返回只有
  ident/uptime 的字典，`run_once` 因此 **exit 0**——脚本会读成「一切正常」而一个数值
  都没有，daemon 也不计失败、永不重扫。现 `has_readings()` 判定：一次读拿不到任何
  数值即读失败（`--once` exit 1 + stderr 说明；daemon 计入 5 次重扫）。**告警优先**：
  E1h 是独立寄存器，即使载荷缺失，已触发的告警仍以 exit 2 报出而不是被降级成 1。
- **`append_history()` 的「空文件」坑**：判据从 `path.exists()` 改为「不存在或大小为 0」。
  此前若进程恰好在建文件与写表头之间被杀，第二天起该文件缺表头，`csv.DictReader` 会把
  第一行数据当列名 → 当天所有导出静默错列。
- **寄存器表逐字节复核（本轮）**：把 REV6 规格书（`02_官方规格/...REV6.pdf`）的文字流解出来，
  逐表核对了 C0h 8 字节配置（p.11：enable/单针 A/针差 A/触发 s/针差触发 s/警告 s，出厂
  1/12/5/20/20/180，窗口 10-14 A、4-8 A、5-30 s、5-30 s、30-240 s）、C1h 42 字节实时表
  （p.12）、C1h 黑盒 26 字节表（p.13）与 E0h 44 字节表（p.15）。**偏移与字段全部一致**，
  因此这几项的剩余风险只剩「真机是否按规格吐数」，不再是「我们读错位置」。
- **E1h 告警位序按机型查表**：MSI Center 在解名之前先按 PID 选三张索引数组之一
  （`CPSU.cs:1046-1057`），所以**同一个字节在 MEG 是 `OVP_12V`、在 TS 是 `OCP_12V`**。
  此前全机型共用 TS 那一张表，MEG P 系每条告警名都是错的（第 0/3/13 字节尤其），
  且 Ai1600T 实际只回 13 字节却被按 18B 门槛判为「无数据」。现按
  `ALERT_INDEXES` 分机型解名、按各自长度收包，未知机型**拒答**（Status 显示 `Unknown`）
  而不猜；`demo` 同步按所模拟机型出位图，否则无法在无硬件时覆盖这条路径。
- **P 系 40B 布局**：`0-19` 是 12V1..12V5 各 (V,I)，`20-23` 是**合并** 12V (V,I)——文档此前误记为「6 轨 × 4B」，且这 5 条单轨读数此前被整段丢弃。

### 质量门禁

```
uv run --group dev pytest -q                     → 307 passed
uv run --group dev ruff check .                  → All checks passed
uv run --group dev ruff format --check .         → 30 files already formatted
uv run --group dev mypy msi_psu_monitor/         → 10 files, no issues
bash scripts/build_deb.sh                        → dist/msi-psu-monitor_1.0.0_all.deb
bash scripts/smoke.sh                            → 39 项全过（三种格式/告警按机型/黑盒/OCP/风扇/daemon/dashboard）
```

护栏（机器强制，不靠人记）：

- `[tool.ruff.format] exclude` + `force-exclude = true`：4 个历史文件不被格式化，
  所以 `ruff format --check .` 可以进 CI（此前只能逐文件跑）。
- `tests/test_pid_consistency.py`：五处 USB PID 列表 + README 载荷大小必须与解析器一致。
- `tests/test_stdlib_only.py`：`python -I` 子进程导入全部模块，第三方依赖混入即失败。
- `ast.parse(feature_version=(3, 10))`：全部 `.py` 通过 3.10 语法校验（本机只有 3.12/3.13）。
- CI 含 3.10 / 3.12 双矩阵 + `ruff check` + `ruff format --check` + `mypy` + `pytest`
  + **构建 `.deb`**。

运行期零第三方依赖（`pyproject.toml` 的 `dependencies = []`），仅 dev 组含 pytest/ruff/mypy。

## 待办

### 外部阻塞

- **Q6 EPS 数量**：等 MSI 回函；未回前按 2×EPS 处理。
- **Q10 Pin6 / AVG 数值**：待真机复核。
- **内核模块**：`kernel/msi-psu-ai1600ts.patch` **是草稿，不可构建**（本轮核实）。
  以前 README/`install.sh` 把它说成「加上 MPG Ai1600TS 支持，装好内核头文件即可 build」——
  实际逐块读完：`PSU_VARIANT_MPG_AI1600TS,` 被插在两个 `#define` 之间（文件作用域），
  `priv->last_read_all = t;` 插进了没有 `t` 的 `msipsu_fw_init()`，`case PSU_REG_IOUT_3V:`
  落在 switch 之外，`msipsu_hwmon_ops_read()` 那块出现第二个 `default:` 且 `break;` 掉到
  switch 外，`debugfs_create_file()` 引用了全文件没有定义的 `iout_pins_fops`，而且没有任何
  代码把 62B 载荷填进 `msipsu_all_ai1600ts`（**即便编译过也只会报未初始化的针脚电流**——
  正是本项目最忌讳的「没测到的健康」）。现三处如实标注为草稿 + 列出致命点，不再指示用户 build。
  要做完需要：钉版的上游 `msi-psu.c`、目标内核头文件、真机 62B 回读验证——三者仓库内都没有。

### 真机验收（`docs/verify.md` §8，共 10 项，均待样机）

1. `--once` 读数与 MSI Center 对照（误差 <1%）。
2. 抓包核对 62B 与 40B 变体的 `0xE0` 布局。
3. Ai1300TS（PID `0xAA6F`）变体识别。
4. `--fan-duty 0/50/100` 读回一致 + F1h 断电重启后仍生效。
5. 满载 >12A/针差 >5A 能触发告警。
6. 拔插 5 次失败后自动重连。
7. 72h 烤机 kWh 与实测电量对照。
8. `--ocp` 阈值与 MSI Center/出厂规格一致，且连接器状态与 `12V-2x6 Status` 行不矛盾。
9. `--ocp` 在 MEG 机型上打印「not available」并 exit 0（不发 NAK、不超时）。

## 决策记录（本轮新增）

- **单多轨检视提前落地**：需求把「單多軌模式檢視」列在二期，但它是同一个 `0xC0`
  地址的只读读法（`CPSU.cs:823`，1 字节，`==2` 为多轨），零写入风险，因此与一期
  `--ocp` 一并做出：MPG TS 出 12V-2x6 阈值，MEG P 系出单多轨模式，Ai1600T 打印原因。
- **demo 覆盖全机型**：`MSI_PSU_DEMO_MODEL` 让多轨/单轨两条路径在无硬件时可端到端跑
  （CLI/daemon/prometheus/history/export），此前它们只有单测覆盖。
- **风扇 Profile 恢复放在 daemon**：`[fan] mode` 是 opt-in，daemon 每次打开/重连 PSU
  重发 41h + F1h；不配置则永不写电源。
- **打包根目录权限**：`mktemp -d` 的 0700 会被 `dpkg-deb` 收进 `./`，已在
  `build_deb.sh` 里 `chmod 755`。

### 可选增强（非阻塞）

- dashboard 页内 JS 保留内嵌（有意决策：`.deb` 无需 package-data，服务器单文件可审计）；
  `do_HEAD` 语义已补全（与 GET 同状态、同 Content-Type、同 Content-Length，含 404/400）。
- `0xC0` OCP 阈值写入 / 单多轨切换（三期专批，需样机确认写入安全）。
- `0xE1` 告警位图之外的二级告警源（当前 E1h + 软件镜像足够）。
