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

- **FW revision**：设备只回 **2 个 ASCII 数字**（`b"10"`），小数点由读取方插入 → `1.0`（对齐 `CPSU.cs:497-507`）；非「两位数字」的载荷原样透传。旧 `<I` 十进制拼法（上游 README 的 `FW: 49.48`）已废弃。
- **Serial**：TS 的首字节是长度前缀，按长度切片，不再把长度当号码。
- **PID**：补齐 `0xAA6F`（Ai1300TS），共 5 个 `0db0:*`。
- **未知机型拒解**：产品字符串匹配不上时抛错，不再猜布局。
- **变体分派**：按产品字符串子串（`Ai1600TS` → mpg 先于 `Ai1600` → meg，然后 `Ai1300`/`Ai1000`），**不按 PID**。
- **截断的机型名不再被当成另一台机器（本轮）**：`MPG Ai1300TS` 是 12 个字符，而 MSI Center 只在 TS 的 PID 上向
  `GET_MFR_MODEL` 要 12 字节、MEG 上要 11 字节（`CPSU.cs`）——短读恰好丢掉结尾那个 `S`，
  而 `MPG Ai1300T` **仍然**匹配 `Ai1300` 分支，于是被按 MEG Ai1300P 的载荷布局解码：
  数值全错、报错为零、`--ocp` 还会输出一套不存在的 8 字节阈值。现识别这种「MPG + 结尾 T」
  的形态并**拒解**（`variant=None` → `error`），不猜。
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
- **dashboard 页面拿不到 Python 常量，图表其实一张都没画（本轮）**：页内 JS 里写了
  `rows.slice(-ROW_LIMIT)`，而 `ROW_LIMIT = 20000` 只存在于 Python 侧——
  浏览器里那是个未声明标识符，`load()` 一进去就 `ReferenceError`，`render()` 永不执行；
  HTTP 全 200、接口全正常、测试因为只 grep HTML 而全绿，**页面却是空的**。现改为占位符
  注入（`render_page()` 替换 `__REFRESH_MS__`/`__ROW_LIMIT__`），并加两条机器护栏：
  「PAGE 里出现的每个 `__X__` 都必须被替换」「JS 用到的 UPPER_SNAKE 标识符必须在页内声明」；
  `load()` 也补了 `r.ok` 检查与 try/catch，轮询失败会写进 `#info` 而不是静静留白。
- **FW 版本是厂商的两位数字串（本轮）**：设备回的是 `b'10'`，MSI 自己插小数点
  （`CPSU.cs:497-507` 的 `Insert(1, ".")`）→ `1.0`。此前按 `<I` 解成十进制整数，
  上游 README 里的 `FW: 49.48` 就是这么来的（`'0'`=48、`'1'`=49 拼出来的假版本号）。
- **两字节 NAK 不再被当成成功（本轮）**：`msi-psu.c:190-194` 说明拒绝回复有两种长度
  （`[cmd, NAK]` 与 `[cmd, reg, NAK]`），此前只认后者，前者落进「有回复」分支 →
  `write_command()` 对**被拒绝的写入返回 True**，风扇/OCP 写会被报成成功。
- **`read_multirail_ocp()` 按机型门控**：0xC0 在 TS 系是 8 字节 12V-2x6 配置，其第 0 字节
  恰好也是「OCP 使能」标志，读成「单多轨」会**看起来像有数据**。现只在 `MULTIRAIL_VARIANTS`
  上发问，其余机型返回 `None`（拒答而不是编造）。
- **坏 `state.json` / 坏历史行不再伪装成数据（本轮）**：合法 JSON 里的错误类型
  （`{"count": "bad"}`、`{"last_ts": []}`）此前直接抛 `ValueError`/`TypeError` 穿出
  `main()`；`iter_history` 只挡 `OSError`，NUL 字节会渲染成 `{'time': '\x00'}`、非法
  UTF-8 会带着 `UnicodeDecodeError` 逃出去；`append_history` 用「文件大小 > 0」判表头，
  被截断的表头文件从此每天都错列；时钟回拨后 `last_ts` 无条件覆盖，**能量被重复积分**
  （600 W / 100 s 记成 33.3 Wh，真值 16.7 Wh）。现：数值一律过 `_finite_float`
  （非数值/NaN/inf 回落 0）、日桶非法即丢、历史坏行跳过并告警、表头按**内容**判断
  （能解析成时间戳就当数据行只补表头，否则当残片重写）、`last_ts` 只在时间前进时更新；
  「每次写入都原子」也收敛成一个 `state.atomic_write_text()`。
- **配置文件里的 `%` 与 `nan`（本轮）**：`ConfigParser()` 默认开
  `BasicInterpolation`，值里一个游离 `%`（路径、注释里的百分号）会在 `.get()` 时抛
  `InterpolationSyntaxError`——而 `try/except` 只包了 `parser.read()`，于是 traceback
  照样穿出。现 `interpolation=None`（这些就是普通取值）。`_as_float` 也补了有限性检查：
  `nan`/`inf` 能通过「`<= 0` 回退」的守卫，随后 `time.sleep(nan)` 直接抛异常、
  `now >= now + nan` 永远为假 → **prometheus 与历史再也不写**，而日志里一句抱怨都没有。
- **prometheus 输出不再「谎报健康」（本轮）**：ident-only 或长度错配的样本以前仍导出
  `msi_psu_info ... 1`（`_info` 按惯例恒为 1，但没有任何健康信号），Grafana 上看起来
  一切正常。现始终导出 `msi_psu_up`（有读数才 1）并在 0 时附
  `msi_psu_error_info{reason="..."}`（reason 取实测原因：`error` / `payload_error`）。
- **`--ocp` 写文件时把首行写丢（本轮）**：不支持 OCP 的机型走 text 分支，两次 `emit()`
  指向同一个 `-O` 路径——第二次把第一次覆盖，于是**文件里没有表头行，stdout 却有**。
  现合并成一次 `emit()`；`emit()` 本身也改成原子写（fifo/`/dev/stdout` 这类特殊文件除外，
  它们无法被 `os.replace` 替换）。
- **`--serial` 不再把「打不开设备」说成「没有这个序列号」（本轮）**：扫描时
  `except (OSError, DeviceBusyError): continue` 把 `PermissionError`（没装 udev 规则）
  和「daemon 正占用」一起吞掉，最后只打印 `Available: none`——用户会去找一个**正插在
  机器上**的电源。现逐台告警 `Skipping <path>: <原因>`，并在**一台都打不开**时明确说
  「could not open any MSI PSU device…（试试 root / 装 udev 规则）」；`--export -O` 写不
  下去也报一行错误 + exit 1，而不是留个截断文件或 traceback。
- **参数校验补漏（本轮）**：`--watch -1`／`--watch 0`／`--watch nan`／`-i 0` 此前全部放行
  （`--watch 0` 会变成忙循环），`--dashboard` 与 `--export`/`--watch`/`--show-log`/风扇写
  混用也静默「按第一种动作执行」。现前者 usage error（exit 2），后者明确拒绝；
  `--dashboard -f json` 同样拒绝（页面只出 HTML，配置里的 `format` 仍不冲突）。
- **又一批「参数/输出不对劲却不出声」（本轮第二轮）**：
  - `--port 99999`／`--port -1` 走 CLI 时没有范围校验（配置层钳了，CLI 没钳），
    `bind()` 抛的是 **`OverflowError`（不是 `OSError`）**，`serve()` 只 catch `OSError`
    → 一行 traceback 收场。现 CLI usage error，`serve()` 也同时 catch `OverflowError`。
  - `--dashboard --port 0` 会绑到随机空闲端口，而横幅打印的是**真实**端口
    （`httpd.server_port`）；但 `print` 默认块缓冲，`--dashboard > log` 或 systemd
    （stdout 是管道）下这行 URL **永远不会出现**——它正是文档里找端口的唯一途径。
    现 `flush=True`（并有测试用 `select` 断言横幅在进程阻塞前就可见）。
  - `--columns ''`（`--columns "$COLS"` 而 `COLS` 未设）此前被当成「未指定」→ 静默导出
    全部 11 列；现报错。`--from ''` 的报错也不再谎称「没给 --from」。
  - `--fan-mode auto --fan-duty 50` 里 duty 被静默丢弃（auto 下 REV6 只发 Duty=0，
    MSI 同样忽略）；现直接拒绝，免得用户以为 50% 生效了。
  - `--watch -O 文件` 此前 **`-O` 被完全忽略**：帧照样打到 stdout，那个文件连建都不建，
    也没有一行提示——需求里 `-O` 的定义是「存成文件，不打屏」。现按需求实现：追加到文件
    （行缓冲，`tail -f` 能实时看到）、stdout 保持干净、启动时在 stderr 说明一句，
    路径写不了就 exit 1。smoke 增两条检查（文件有内容 / stdout 为空）。
- **demo 与 state 的两处「默默收下」**：`MSI_PSU_DEMO_ALERT=pin_imbalance`（或任何本机型
  报不出的名字）原来被接受然后从不置位——无硬件验收会跑出「全部正常」的假通过，与
  `MSI_PSU_DEMO_MODEL` 打错会告警的处理不一致，现同样告警并列出本机型能报的名字；
  `state.json` 若是指向 `/dev/zero`/FIFO 的软链（glob 之外的另一条读取路径），
  `read_text()` 会一直读到 `MemoryError`，现按「不是普通文件」跳过并告警。

- **读失败不再把「上次的健康 prom」留在盘上（本轮）**：`write_prometheus()` 只在采样成功
  后调用，所以电源被拔掉后 textfile 一直保留最后一次内容——node_exporter 每次抓取都照样
  上报 `msi_psu_up 1` 和那个瓦数，看板上「一小时前就拔掉的电源」一直显示成在线（与 README
  里 `msi_psu_up` 的承诺直接冲突）。现在读失败即把同一文件改写成 `msi_psu_up 0` +
  `msi_psu_error_info{reason="…"}`，**每个不同原因只写一次**（不是每秒重写），恢复后照常写回。
- **另外三处「静默」**：`--export` 一行都没匹配到（state 目录不对 / daemon 从没跑过 /
  窗口比保留期还长）时只在 stdout 打一个表头就 exit 0，现补一句 stderr 说明；
  `--once`/`--watch` 原来用内置 30 天调 `prune()`，用户设的 `retention_days = 60` 被
  静默砍半（daemon 侧认这个值），现两边一致；时钟被 NTP 往回拨时积分会**无声冻结**
  （AVG 还在动、kWh 不动），现每次「往外拨」告警一次并说明原因。

- **告警状态不再由半个数据源下结论（本轮，P1）**：`collect_alerts()` 原来把「E1h 位图
  没应答」也算成「有数据」——只要 12+4 pin 的软件镜像有读数（**哪怕全是 False，dict 也
  是真值**），`12V-2x6 Status` 就打 `Normal`。可镜像只看得见 OCP 针脚与针差，看不见
  E1h 独有的 `opp`/`otp`/`fan`，而 `fan`（风扇堵转、约 10 s 后关机）正是唯一的 critical
  位。于是 E1h 读失败时：`--once` 打 `Normal` 且 exit 0、daemon 导出
  `status="Normal"`，全程无声。现改判「E1h 位图是否应答」（`have_e1h`）：只有镜像作答
  时状态是 `Unknown`（镜像看到的告警照常上报，exit 2 也照常），并且**读失败不会清掉
  已经 firing 的告警**（engine 只覆盖传入的键，这条不变量现在有测试锁住）。

- **看板不再把「读不到」装成「没有数据」（本轮）**：
  - `/api/*` 在 state 目录读不了时回 **503 + 原因**（页面本身仍 200，页内 JS 把原因
    显示成 `Data may be stale (HTTP 503: … is not readable by this user)`）。修前它与
    「daemon 从没跑过」完全一样：`count: 0`、`avg 0.00 W`、`total 0.000 kWh`、HTTP 200。
  - `urlparse` 挪进 `_route` 的 try 里：请求行 `GET http://[/x HTTP/1.1`（合法请求行）
    会让它抛 `ValueError: Invalid IPv6 URL`，而它在 try **外面**，于是异常直接穿出
    `do_GET`——客户端拿到的是断连（连状态行都没有）+ 服务端一条 traceback，而不是 400。
  - 页内 `okJson` 非 2xx 时把响应正文读出来一起报（原来只有 `HTTP 503` 四个字，
    操作员看不出该干什么）。
  - 顺带修掉一个**测不出问题的测试**：`test_server_binds_loopback_only` 断言的正是它
    自己刚传进去的 host（换成 `0.0.0.0` 也照过），README 的「loopback only」因此没有
    任何能失败的测试覆盖。现改为断言 `dashboard.DEFAULT_HOST` 与 `run_dashboard` 真的
    传了 loopback。

- **坏文件不再伪造成数据或崩掉（本轮，复核子代理挑出，P1×3）**：
  - `state.json` 不是 UTF-8（编辑器存成 UTF-16/Latin-1、或坏一个字节）时 `read_text()`
    抛的是 `UnicodeDecodeError`——**是 `ValueError` 不是 `OSError`**，`except OSError`
    接不住，`load()` 直接炸：daemon 在 `Restart=always` 下变成 5 s 崩溃循环，CLI 甩
    traceback。同一个文件里另外三条读取路径都catch了它，只有这条漏了。现改为
    `except (OSError, UnicodeDecodeError)`；且**每次丢数据都要出声**（读不了 / 不是 JSON /
    版本号不对各打一条 warning），缺失文件（首次运行）保持安静。
  - `daily-*.log` 没有表头（旧版本写的、或表头写一半崩了）、表头被手工改名、或带
    UTF-8 BOM 时，`DictReader` 会把**第一条数据行当成列名**：于是每一行的 `time` 都是
    `None`，**整个文件静默读成空**，一整天在 `--export` 和看板上消失且毫无提示。现按
    位置读列（列序就是 `HISTORY_COLUMNS`），并说明一句；首行能解析成时间戳就当数据
    （不丢第一行），否则当表头跳过。
  - `--config` 指向的文件不是 UTF-8 时同样漏成 traceback（`ConfigParser.read` 只在
    `open()` 外面接 `OSError`）→ 现包成 `ConfigError`。
  - `--config ""`（`$CONF` 没设）与 `-O ""`/`--from ""` 同一类静默 no-op（悄悄改用默认
    搜索路径、跑在默认值上）→ 现 usage error + `load_config('')` 报 `ConfigError`。
  - 历史文件的**撕裂末行**：上一次 flush 被打断（ENOSPC、断电）后残留半行，下一条
    样本会被粘在它后面；合并后的行**仍以可解析的时间戳开头**，于是被当成真数据导出，
    撕裂点之后的每一列都错位、当次样本也丢了。现追加前先确认末尾是换行，不是就先补
    一个（把残行留作自己的一行，读时按时间戳不合法跳过）。
  - 历史 `time` 列改为**带时差的绝对时刻**（`…T02:30:00+08:00`）：naive 本地时间表达
    不了夏令时回拨那一小时，回拨夜的第二个 02:30 会按第一个解析，于是被 `--from 90m`
    当成「太旧」丢掉。老的无时差行照旧能读。

- **两条指标检查本来永远查不出问题（本轮，复核子代理挑出）**：smoke 用子的 `case *"$2"*`
  子串匹配去查 `msi_psu_up 1` / `msi_psu_ocp_available 1`，而这两个指标上方的
  `# HELP msi_psu_up 1 when the last sample carried sensor readings` /
  `# HELP msi_psu_ocp_available 12V-2x6 … (1) or not (0)` **本身就含这串**——把 gauge 改成 0
  也照样打印 ok（已用最小脚本复现：旧写法 ok、新写法 FAIL）。现加 `assert_line`
  整行锚定（首行/末行都测过，因为命令替换会吃掉文件末尾换行），三条指标检查改用它；
  顺带补上 P 系那半边本来只有单测覆盖的端到端检查（`msi_psu_multirail_ocp{} 1` +
  `msi_psu_ocp_available 0`）。smoke 51 → 53 项。

- **复核子代理挑出的「`-O`/`-i` 被接受然后无视」整类（本轮）**：只读审计发现同一类缺陷还留着
  四个口子，逐条复跑确认后全部堵上：
  - `-O ""`（`$OUT` 没设）此前等价于「没给 `-O`」→ 输出照旧打屏、文件不建。与 `--columns ''`/
    `--from ''` 同一类，现 usage error（exit 2）。`--once`/`--watch`/`--export` 都覆盖。
  - `--show-log`、`--fan-mode/--fan-duty` 此前**完全无视 `-O`**（直接 `print`）：现走 `emit()`，
    与其它模式一致（文件替代屏幕）。`--dashboard` 没有输出文件，改为明确拒绝而不是收下不用。
  - `-i` 单独用此前被静默忽略（手册写的是「与 `-w` 搭，单用无效」）→ usage error。
  - `[monitor] interval` 此前是**死配置**：`conf.example` 写着「--watch 的默认轮询间隔」，
    但没有任何代码读它（裸 `--watch` 永远用 argparse 的 const 2.0）。现裸 `--watch` 取该值，
    `--watch <n>` 与 `-i <n>` 依次优先。实现上 `--watch` 的 const 用字符串哨兵 + 自定义
    `type` 转换器（argparse 会把 `type` 也套在 const 上，`type=float` 会直接炸）。
  - 顺带两处「静默」：`[monitor] format = json` 配 `--watch` 会被丢掉（命令行同样组合是
    usage error）→ 现在告警并回落 text；`-q` 之前压不住新加的 `-O` 横幅（横幅不是错误）→
    现在压得住；首帧就报错时 `-O` 文件会留个 0 字节空壳 → 现在把原因行写进去（对齐 `--once`）。

- **daemon 的 prometheus 现在也带 OCP 块（本轮）**：`--ocp` 只读展示此前只有 CLI 有，daemon
  的 textfile 里没有任何 OCP 指标——Grafana 上看不到单针阈值，也没法按它告警。现在 daemon
  在每次写 prom 时（默认 30 s）读一次 C0h/C1h 并附上 `msi_psu_ocp_*`。两个「不许骗人」的
  细节：**C1h 是 5 s 滚动平均**，所以不能整个会话只读一次（那是把 stale 电流当实时导出去）；
  **MEG 机型 0xC1 是 26 字节黑盒**，所以按机型门控、一次都不读，改为导出
  `msi_psu_ocp_available 0`——「不支持」和「exporter 坏了」在面板上必须能分开。换机（重扫）
  时清空缓存，不拿上一台的阈值糊弄。MEG P 系（0xC0 的另一种含义）则导出
  `msi_psu_multirail_ocp`（1 = 逐轨保护）。四类机型在真 daemon 上逐个复验过：
  MPG TS 出阈值+状态、MEG Ai1600T 只有 `available 0`、MEG P 出 multirail、两者都不出多余指标。

- **daemon 打不开设备时的重试节奏（本轮）**：`_ensure_psu()` 的 except 分支设了
  `_next_discovery` 却**没有清掉 `device_path`**，下一 tick 直接跳过发现节流、每秒重开
  一次设备刷一行告警（`DISCOVERY_RETRY_S = 5` 形同虚设）。现清空路径，节流真正生效。
- **demo 也要讲真话（本轮）**：`demo.read_ocp_thresholds()` 未按机型门控，给非 TS 机型
  「编造」了 8 字节 0xC0 配置——无硬件时最容易把错的验收结论跑成「通过」。现与真机一致
  地返回 `None`。

### 质量门禁

```
uv run --group dev pytest -q                     → 569 passed
uv run --group dev ruff check .                  → All checks passed
uv run --group dev ruff format --check .         → 34 files already formatted
uv run --group dev mypy msi_psu_monitor/         → 10 files, no issues
bash scripts/build_deb.sh                        → dist/msi-psu-monitor_1.0.0_all.deb
bash scripts/smoke.sh                            → 58 项全过（三种格式/告警按机型/黑盒/OCP/风扇/Zero Fan/蜂鸣器/daemon/dashboard/.deb 内容与权限）
```

护栏（机器强制，不靠人记）：

- `[tool.ruff.format] exclude` + `force-exclude = true`：4 个历史文件不被格式化，
  所以 `ruff format --check .` 可以进 CI（此前只能逐文件跑）。
- `tests/test_pid_consistency.py`：五处 USB PID 列表 + README 载荷大小必须与解析器一致。
- `tests/test_stdlib_only.py`：`python -I` 子进程导入全部模块，第三方依赖混入即失败。
- `ast.parse(feature_version=(3, 10))`：全部 `.py` 通过 3.10 语法校验（静态兜底）。
- **3.12 与 3.10 矩阵真跑过**（turn8 重跑）：`uv venv --python /usr/bin/python3.12` 与
  `uv venv --python 3.10` 各建裸环境（只装 dev 组 pytest，不装本包），把工作树复制一份、
  不带 `.venv`，直接跑 `python3 -m pytest`：**3.12.3 → 569 通过**、**3.10.21 → 569 通过**。
  3.10 这条以前根本跑不起来：两个测试模块 `import tomllib`（3.11+），CI 的 3.10 矩阵会在
  收集阶段就红；本轮加 `tomli>=2; python_version < '3.11'`（dev 组）并 try/except 回退。
  `bash scripts/smoke.sh`（**58 项全过**）在 3.12 裸环境重跑过（turn10）。
- CI 含 3.10 / 3.12 / 3.13 三矩阵 + `ruff check` + `ruff format --check` + `mypy` + `pytest`
  + **构建 `.deb`**。

运行期零第三方依赖（`pyproject.toml` 的 `dependencies = []`），仅 dev 组含 pytest/ruff/mypy
（以及只在 3.10 安装的 tomli）。

## 待办

### 只读复核（turn8）turn7 剩余的 11 条（本轮已全部处理）

turn7 留下的 11 条已逐条修完；每条都补了「改回旧行为就会红」的测试。turn7 的 report 原件
（`/tmp/review-turn7-report.*`）已被清掉，下面的记录自足。

**dashboard-http 车道（2 个 P1 + 3 个 P2）**

1. **[P1] 停掉的 daemon / 一周前的数据仍像实时的**：`/api/state` 现在回 `last_ts`，页面显示
   「last sample … ago」；超过 `dashboard.STALE_AFTER_S`（300 s = 10 个 30 s prom 写盘周期）
   就把表头标成陈旧（`.sub.stale`），不再只在 HTTP 失败时才提示。测试：
   `test_state_endpoint_exposes_the_last_sample_time`、`test_the_page_shows_sample_age_and_marks_stale_data`。
2. **[P1] 目录可读但 `state.json` 坏掉时仍 200 + 全 0**：新增 `state.StateError` 与
   `MonitorState.load(strict=True)`；CLI/daemon 仍走宽容默认。`/api/state` 捕获后回 503 + 原因，
   目录级问题仍由 `_state_dir_problem()` 负责。**`/api/history` 不受影响**（页面也改成两个 fetch
   独立处理），一个坏文件不会连历史曲线一起藏掉。测试：
   `test_a_corrupt_state_file_is_a_503_while_history_still_serves`、
   `test_an_unreadable_state_file_is_a_503_with_its_path` 与 `test_state.py` 的四条 strict-load 用例。
3. **[P2] 空查询值被静默换成默认**：`_query()` 改用 `keep_blank_values=True`，`?from=` 与
   `?columns=` 现在和 CLI 一样是硬错误（400），不再悄悄变成默认窗口/全列。
   测试：`test_blank_query_values_are_400_not_defaults`。
4. **[P2] 曲线用行号当 x 轴**：`series()` 携带 `Date.parse(r.time) / 1000`，`draw()` 在全部点都有
   时间戳时按真实时间跨度映射，取不到时间才回退行号；两端画 `HH:MM` / `MM-DD HH:MM` 轴标签。
   停机 6 小时不再看起来像两个相邻样本。测试：`test_the_chart_x_axis_uses_real_timestamps`。
5. **[P2] 周图按 150 px 画、被 CSS 压到 120 px**：CSS 收窄为
   `#grid canvas { height: 120px }` + `#weekly { height: 150px }`，`drawWeekly()` 改为读
   `canvas.clientHeight`；两个图表都按实际盒子高度画。测试：
   `test_the_weekly_canvas_is_drawn_at_its_css_height`。

**tests-truth 车道（1 个 P1 + 5 个 P2）**

6. **[P1] 两条叫「atomic」的测试从没测过原子性**：状态写盘与 prometheus 写盘各补一条「临时文件
   写完、`os.replace` 失败」的用例，断言目标仍是旧字节、只多出一个 `.tmp`；换成原地
   `write_text()` 这两条都会红。测试：`test_an_interrupted_save_keeps_the_previous_state_intact`、
   `test_a_failed_prometheus_replace_keeps_the_previous_textfile`。
7. **[P2] `docs/verify.md` 的覆盖表把功劳算给了错的模块**：§1.1 重写为 20 行（补上漏掉的
   `test_protocol_discovery.py` / `test_packaging.py`），每行点名至少一个真实测试函数；
   `test_docs_consistency.py` 用 `pytest --collect-only` 的实际收集结果核对函数名，并要求每个
   测试文件都有行。顺带修正文件名正则不收数字的问题：`test_protocol_lin11.py` 之前根本不在
   两条文档校验的覆盖范围内。测试：`test_the_coverage_table_names_real_test_functions`。
8. **[P2] turn7 留下的裸计数不在护栏里**：`TEST_COUNT_RE` 补 `通过|通過`。那个未受护栏保护的旧通过数已按裸环境实跑对齐：
   3.12.3 与 3.10.21 各 **569 通过**（细节见上节「质量门禁」）。
9. **[P2] 零依赖探针漏了 `__main__.py`**：`SHIPPED_MODULES` 元组补 `__main__`，并新增
   `test_the_probe_covers_every_shipped_module`，把元组与 `msi_psu_monitor/*.py` 精确对齐。
10. **[P2] `test_pid_consistency.py` 比的是 `bulk_size` 而不是真正的门限 `payload_size`**：README
    的 0xE0 列改成「62 bytes (44 data)」两个数，测试分别对 `bulk_size` / `payload_size` 断言；
    docstring 里那个仓库中不存在的 `_parse_bulk` 已删。
11. **[P2] 包内 `AGENTS.md` 还留着作废的「ruff format 不得全仓跑」禁令**：该段改为
    「`ruff format --check .` 全仓可跑、CI 已跑」，并新增
    `test_no_document_still_forbids_repo_wide_ruff_format`，该措辞在任何文档里再出现都会红。

顺带发现并修掉一个 CI 必然失败：3.10 矩阵在**收集阶段**就红——`tests/test_docs_consistency.py`
与 `tests/test_stdlib_only.py` 直接 `import tomllib`（3.11 才有）。现在改为 try/except 回退到
`tomli`，dev 组加 `tomli>=2; python_version < '3.11'`，3.10.21 裸环境已全绿。

### 产品级加固（turn9，样机前，无硬件可测）

样机未到，本轮只做不依赖硬件的产品级收口；每条都有「改回旧行为就会红」的回归测试。

- **掉电不再把 kWh 清零（P1）**：`state.atomic_write_text` 原来只有 rename、没有 fsync，
  掉电后可能出现「改名成功、内容为空」的 state.json。现在临时文件 `flush + fsync`，
  rename 后再 fsync 目录（不支持的 FS 静默跳过）。测试：
  `test_atomic_write_fsyncs_the_file_and_its_directory`。
- **文本 IO 与 locale 解耦（P1）**：配置/state/历史显式 UTF-8（读 `utf-8-sig` 容忍 BOM，
  写 UTF-8），`emit` 与 CSV 也显式。systemd 继承 `LC_ALL=C` 时，一份带中文注释的配置
  过去会直接 `ConfigError`；现在正常加载。测试：
  `test_a_utf8_config_is_read_under_an_ascii_locale`、
  `test_state_files_are_read_as_utf8_regardless_of_locale`、
  `test_a_utf8_bom_is_tolerated`、`test_load_accepts_a_utf8_bom`。
- **`| head` 不再像是崩溃（P1）**：CLI 统一收口 BrokenPipeError（行缓冲 + 最终 flush），
  `--once` / `--help` / `--version` 在已关闭的 stdout 上都是 exit 0、无
  `Exception ignored`；此前是 exit 120。测试：
  `test_a_closed_stdout_pipe_is_not_a_traceback`。
- **dashboard 客户端提前断开不再刷 traceback（P2）**：新增 `DashboardServer.handle_error`，
  ConnectionError/TimeoutError 降到 debug，真实异常仍带堆栈进 logger；`_send` 捕获
  ConnectionError，空闲连接 30 s 超时。测试：
  `test_an_early_client_disconnect_does_not_print_a_traceback`、
  `test_an_unexpected_handler_error_keeps_its_traceback`。
- **响应头（P2）**：全部响应加 `X-Content-Type-Options: nosniff`、
  `X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`。测试：
  `test_security_headers_are_present_on_every_route`。
- **配置拼写错误不再静默（P2）**：未知 section/option 各打一行 warning，
  `intervall = 5` 不会再悄悄用默认值。测试：
  `test_unknown_sections_and_options_are_reported`。
- **systemd 纵深防御（P2）**：补 ProtectKernel*/ProtectControlGroups/ProtectClock/
  Restrict*/LockPersonality；仍不碰 `/dev/hidraw*`，明确不加 `UMask=0077`
  （会让 state.json 对 uaccess 用户不可读，打破非 root dashboard）。测试：
  `test_the_unit_keeps_the_hardening_baseline_without_breaking_hidraw`。
### REV6 功能补齐（turn10）：Zero Fan / 蜂鸣器 / 黑盒顺序

对照 REV6 与 MSI Center 源码补了三个缺口；每条都有不依赖硬件的 mock 回归：

- **Zero Fan 开关（43h + F1h）**：`--zero-fan on|off`，写后读回 42h byte 4，3 次重试；
  `[fan] zero_fan = on|off` 让 daemon 在重连时随风扇 Profile 一起恢复；MEG 机型明确拒绝
  （`set_zero_fan` 返回 False，CLI exit 1），不会向语义未验证的寄存器写入。
- **蜂鸣器静音（C2h）**：`--buzzer-off`，TS 专属、写后无回读（ACK 即成功）；用于 12+4 OCP
  蜂鸣已触发时静音。
- **黑盒顺序按 REV6 p.13**：InfoID 1 是最新记录。`read_blackbox` 返回的槽序即新→旧，
  `format_blackbox` 改为按 InfoID 升序展示，不再用累计计数器重排（计数器可能回绕/清零）；
  docs/protocol.md 与两份 AGENTS 同步纠正。
- **写操作收口**：`run_write_controls` 只 emit 一次（`-O` 不会被第二行覆盖）；Zero Fan 先写、
  风扇后写，与 Cooling Wizard 顺序一致；CLI 冲突校验覆盖 `--watch/--export/--show-log/--ocp/--dashboard`。
- **测试**：513（新增 26 条：协议帧、CLI 读回/组合/冲突、demo、config、daemon 恢复）。
- **真机验收**：verify.md §8 增加第 12 项（Zero Fan 读回 + 断电保持、buzzer 实际静音），
  两份清单同步为 12 项。
### 官网分发（turn11）：自包含二进制 + 零 Python .deb

目标改成「官网直接下载、目标机不装 Python」；源码 `.deb` 仅保留给开发/CI。

- **build 依赖组**：`pyinstaller==6.16.0`（仅构建期；`[project]` 仍无 runtime 依赖）。
- **`scripts/build_binary.sh`**：两个 onefile（CLI/daemon），Ubuntu 22.04/glibc 2.35 基线，
  产出 x86_64/aarch64 tar.gz + `BUILD-INFO` + `SHA256SUMS`；打包前对冻结产物跑
  `--version` / demo `--once` / daemon 1 次 / `--zero-fan` / `--buzzer-off` 烟测。
- **`scripts/build_deb_binary.sh`**：从同一二进制产出 `.deb`，`Depends` 只有
  `libc6 (>= 2.35), zlib1g`，没有 `python3`。
- **`scripts/install_binary.sh` / `uninstall_binary.sh`**：目标机零 Python；不覆盖用户配置；
  uninstall 默认保留 state/config，`--purge` 才删。
- **CI**：`ci.yml` 新增 `freeze` job（ubuntu-22.04，每次 push 构建并断言 Depends 无 python）；
  `release.yml`（tag `v*`）在 ubuntu-22.04 / ubuntu-22.04-arm 双架构构建并发布 GitHub Release
  + 合并 `SHA256SUMS`。
- 本机 24.04/glibc 2.39 只能用 `ALLOW_NEWER_GLIBC=1` 做本地烟测；正式包必须 22.04。
  已在本机用 `env -i` 跑通打包后的二进制（无 python、无 libpython）。
- **测试**：当时 521 项（新增 8 条发布链路静态回归）。
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

### 换机型后不再永久挂着上一台的告警（本轮，P1）

`AlertEngine` 只在「某名字这一轮被报为 False」时才清 latch，而 TS 专有的名字
（`ocp_pin1`..`ocp_pin12`、`pin_imbalance`）在 MEG 的 `ALERT_INDEXES` 里根本不存在：
daemon 拔掉 TS 换上 MEG 之后（`_drop_psu()` 会清 OCP 缓存，但从不碰 `self.engine`），
那些名字再也不会被报一次，于是**永远**挂在导出与状态行里——`msi_psu_alert{alert="ocp_pin1"} 1`
和 `Status: ocp_pin1, pin_imbalance` 会出现在一台没有逐针采样的电源上，而它自己的 E1h
寄存器是 Normal。反向（MEG Ai1600T 的 `ac` 挂到 TS 上）同理。

现加 `AlertEngine.retain(names)`：**只在这一轮真的读到了 E1h** 时，用这台设备能报的名字
集合收窄引擎状态（失败的读什么都不动，保住「读失败不清告警」那条不变量）。
两条新测试：机型互换后 TS 专有名字消失而两台都报的 `otp` 保留；E1h 失败时绝不收窄。

### 读回包首字节是 0xFE 时不再被当成 NAK（本轮，P0 级数据丢失）

`HIDDevice.send_command()` 里判「写被拒」的那个 `resp[2] == PSU_NAK` 被同时用在了**读**上，
而读回包的 byte 2 是**载荷第一个字节**：12 V 轨的 LINEAR11 字（11.984 V = `0xCEFE`，MEG
Ai1600T 的 20 字节布局里正好是 `data[0:2]`）和 uptime 计数器（每 256 秒出现一次 0xFE）
都能取到这个值。后果：**整帧 0xE0 被丢掉**——`get_sensors()` 只回 ident、`--once` 报
`Error: no sensor payload in this sample` 并 exit 1，daemon 把健康电源记成读失败并改写
`msi_psu_up 0`，uptime 每 256 秒静默消失一次。参考实现 `msi-psu.c:186-198` 写得很清楚：
不支持寄存器的回包只有两字节 `[cmd, NAK]`（读也一样），`[cmd, reg, NAK]` 是**写**被拒的形状。
现 byte-2 判定只在 `data[0] == PSU_WRITE` 时生效，并把三种形状都写进了参数化测试
（读 2 字节 NAK / 写 2 字节 NAK / 写被拒 3 字节 NAK / 读载荷以 0xFE 开头），另加一条
端到端测试：MEG Ai1600T 的 0xE0 帧首字节 0xFE 必须解出 `vout_12v == 11.984 V`。

### 每条安装路径都启用了一个没有配置文件的 daemon（本轮，P1）

`systemd/msi-psu-monitor.service` 的 `ExecStart` 写死了
`--config /etc/msi-psu-monitor.conf`，而 `scripts/install.sh` 只在收尾**打印**一句「想配置的话
自己 `install` 那个示例文件」，`scripts/build_deb.sh` 只 stage 模块/unit/udev/文档、
**不装任何 `/etc` 文件**——可它的 postinst 照旧 `systemctl enable` + `restart`（三条都带 `|| true`，
失败也不出声）。于是 apt 打印成功、unit 被启用，然后每一次启动都撞上
`config.py` 的 `ConfigError`；CLI 侧有 `try`（`monitor.py` 把参数错误变成一行 + exit 1），
**daemon 侧没有**：`daemon.main()` 唯一的 `try` 包着 `daemon.run()`，`load_config()` 在它外面，
异常直接以 traceback 逃逸 → `Restart=always` 每 `RestartSec` 再撞一次，journal 里堆栈刷屏。

三处一起改：unit 不再钉 `--config`（配置文件本来就是可选的、走 `CONFIG_FILES` 搜索路径，
所以「什么都没配」的机器也能正常起来）；`build_deb.sh` 把示例 stage 成
`/etc/msi-psu-monitor.conf`（dpkg conffile，用户改过会在升级时被询问保留），
`install.sh` 只在文件不存在时写它（**永不覆盖用户改过的那份**）；`daemon.main()` 捕 `ConfigError`
打一行 `Error: ...` 并返回 1（与 CLI 同一套退出码）。

### 打包/冒烟里三个「看着通过其实没测」的口子（本轮，P2）

- **`.deb` 里的权限跟着构建者的 umask 走**：`build_deb.sh` 用 `cp` 拷模块与 unit，`umask 077`
  下产物是 **root-only**，而 udev 规则的 `uaccess` 承诺本来就是给非 root 会话用的——权限错了
  等于功能坏了。改成 `install -m 644`，并在 `scripts/smoke.sh` 里**用 `umask 077` 构建、
  再从 `dpkg-deb -c` 读回模式**（此前没有任何一步看过产物内部）。
- **`smoke.sh --keep` 是空头承诺**：`cleanup()` 读的是 `$1`，而 `trap 'cleanup' EXIT` 一个参数都不传，
  于是 `--keep` 被文档化、被接受、然后静默忽略（临时目录照删）。改成在脚本开头记住 `$KEEP`。
- **dashboard 段可能在对着别人的服务器打勾**：4 条检查只看 `curl` 的响应，端口上如果是
  （残留的）别的 dashboard，本脚本的子进程明明以 `cannot serve ... Address already in use` 死了，
  这一段仍然全绿。现加一条「子进程还活着且 stderr 为空」的检查——注意**只 `kill -0` 不够**：
  未被回收的子进程是僵尸，照样通过；而 curl 会在我们子进程还没跑到 `bind()` 时就被占用端口的
  监听者应答，所以检查前留 1 秒宽限。实测：外来 dashboard 占住端口时，该检查如实 FAIL、脚本 exit 1。

### 只读复核（turn6）protocol-bits 车道的四条 P2（本轮）

1. **`docs/protocol.md` 的 NAK 章节自相矛盾**：那一节写「命令不支持或出错时回包以
   `[0xFE, ...]` 开头」——**没有任何一种回包长这样**。真实形状是读 `[0x51, 0xFE]`、
   写被拒 `[0x50, <reg>, 0xFE]`（`msi-psu.c:186-198`），而且同一份文档 15 行前刚写对过。
   照着这一节实现会去找 byte 0，永远找不到。现改成形状表 + 说明「数据回包即使首字节是
   `0xFE` 也不是 NAK」（正是上一轮修的那个 P0 的文档侧）。
2. **`fw_revision` 会把更长的数字开头载荷截断**：判据是 `len(revision) >= 2`，于是
   `b'1234'` 被渲染成 **`1.2`**——一个设备从没发过的版本号；而 `docs/protocol.md:70`
   承诺「非两位数字的载荷原样透传」。改成 `len(revision) == 2 and revision.isdigit()`，
   三种长度都进测试（`b'1234'`→`1234`、`b'100'`→`100`、`b'10\x00\x00'`→`1.0`）。
3. **黑盒记录的「新→旧」三方打架**：reader 的 docstring 说「oldest last」、格式化器表头说
   「newest first」并按**读到的顺序**打印、demo 又把 `#2` 摆在 `#1` 前面（且 `#2` 的
   `total_time`/`total_count` 更大）。三条里至少一条是错的，而冒烟/验收正是拿 demo 在练。
   固件到底哪个槽更新**没有可核对的依据**，所以不去猜：每条记录自己带着写入时刻的
   累计运行时长与触发次数（`TOTAL_UPTIME` 同源的单调计数器），`format_blackbox` 就按
   `(total_time, total_count)` **降序**排——顺序与被打印出来的数字自洽，肉眼可核；
   同分保留设备的槽序。demo 的数据同时改成「槽 1 = 最新」，与 `docs/protocol.md` 的
   「InfoID 1..10 新→旧」一致。
4. **`[monitor] no_alerts` 是死配置**：配置示例写着「同 `--no-alerts`，跳过 E1h 轮询」，
   CLI 认（`monitor.py` 两处），**daemon 连字符串都没有**——而 unit 加载的正是
   `/etc/msi-psu-monitor.conf`。也就是说用户在正常模式（常驻 daemon）下关告警，E1h 照轮询、
   `msi_psu_alert{…}` 照导出。现 daemon 与 CLI 同样处理：不轮询、`status`/`alerts` 两个键
   都不设（于是没有 Status 行、没有告警指标、没有 ALERT 行），并在启动时打一行
   「Alert polling disabled by config」——**「什么都没报」和「一切正常」不是一件事**。

### 只读复核（turn6）docs-truth 车道剩下的三条 P2（本轮）

- **README 写「单针 > 12 A」，代码是 `>= 12 A`**（`alerts.py:125`）。C0h 的触发点本身是**含**端点
  的（`value >= PIN_OCP_THRESHOLD_A`），照 README 去「修」成严格大于，等于把镜像削弱一个量化
  步进。改文案，并补一条钉住边界的测试：`[12.0]*12` 必须 12 个 `ocp_pinN` 全亮、`[11.9]*12`
  一个不亮；针差是**严格** `> 5 A`（正好 5.0 不算）且**按 6 针连接器**分别算（跨连接器差 6 A、
  各自内部只差 1 A 时不算）——这三处此前没有任何测试。
- **AGENTS.md 把 unit 的沙箱行说成「注释掉的」**：实际上 `ProtectSystem=full`/`ProtectHome=yes`/
  `PrivateTmp=yes`/`NoNewPrivileges=yes` **都是生效的**，注释只解释了为什么不加
  `PrivateDevices`。照旧文案去「解开沙箱注释」可能顺手加进 `PrivateDevices`——正是那条注释要
  防的故障（daemon 全程持有 `/dev/hidraw*`）。
- **「不要全仓跑 `ruff format`」这句话已经作废**：四个混引号的历史文件早被
  `[tool.ruff.format] exclude` + `force-exclude = true` 挡住，`ruff format --check .` 全仓绿、
  且已进 CI 门禁。同一份 `docs/verify.md` 在 50 行前刚说过它安全，两句自相矛盾。两处都改成
  当前事实（「exclude 列表就是那个修复」），免得后来者不敢跑门禁或以为 CI 是红的。

### 文档里的 `[fan]` 示例其实不生效（本轮，P1）

README 的配置片段写的是

```ini
mode = customized   ; auto | customized
duty = 60           ; 0-100, ignored by the PSU in auto mode
```

而 `ConfigParser` **不剥行尾注释**：`mode` 的真实取值是
`customized   ; auto | customized`，不是任何已知模式，于是 `load_config` 告警一次、整节被忽略
——照文档抄一遍，功能一点没生效，而且（在 `-q` 下）连那句告警都看不见。这与本项目一直在堵的
「参数被接受然后无声不生效」是同一类。现把注释挪到独立行，并加两条测试：
`test_the_readme_fan_snippet_is_copy_pasteable`（把 README 里的 ```ini``` 块抽出来
反解析，取值必须等于它声称的 `customized`/`60`）与「README 不得有两个同名 `##` 标题」
（同一轮还发现 `## Kernel Module` 连写两遍，第二遍是空的）。

### 测试自身的环境依赖（本轮抓到）

- `tests/test_stdlib_only.py` 给子进程传了 `PYTHONPATH=<repo>` 却同时带 `-I`——`-I` 会
  **忽略** `PYTHONPATH`，而且自 3.11 起连 cwd 也不再进 `sys.path`。它之所以一直绿，只是因为
  `.venv` 里装了本包（editable）。换个裸 3.12 环境一跑就 `ModuleNotFoundError`：**这条测试
  测的是「环境里装了什么」，不是「工作树能不能只靠标准库 import」**。现改为在子进程里显式
  `sys.path.insert(0, <repo>)`，并把注释里那句「`-I` 忽略 site-packages」改对（那是 `-S`；
  `.deb` 本来就装进 site-packages，真正把关的是 `foreign` 泄漏集合）。

### 文档不实（本轮又抓到一处）

- `DEV_PROGRESS.md` 的真机验收小节声称 10 项、下面只列 9 条，`requirements-traceability.md`
  也引用 10 项，而 `verify.md` §8 实际有 11 条（4b 与 Ai1600T 那条是后加的，没回头同步总数）。
  现全部改为 11 项，并加文档测试 `test_the_quoted_real_hardware_check_count_matches_verify_md`
  把「§8 里的编号条目数 == 文档里引用的总数 == DEV_PROGRESS 列表条数」变成机器护栏。

### 只读复核（turn7）tests-truth 车道：真机发现路径根本没被测过（本轮，P0）

第七轮只读复核开了两条新车道：`tests-truth`（测试自己是不是真的会失败）与
`dashboard-http`（HTTP 面与页内 JS）。13 条 finding 全部先复跑成真再动手，本轮修掉
2 条，其余 11 条列在 `## 待办` → 「turn7 复核剩余 11 条」。

- **`detect_devices()` 返回 `/dev/device`（`protocol.py:216-217`）**：节点名取的是
  uevent 的 `dirname` 再 `basename`，而 `/sys/class/hidraw/hidraw5/device/uevent` 的
  dirname 是 `.../hidraw5/device`，于是拿到 `device`。返回值非空，调用方以为「发现成功」：
  `--once`/`--watch`/daemon 拿到 `/dev/device` 去 `os.open` → FileNotFoundError → 退出 1；
  `--serial` 走 `resolve_device()` 把它算进 blocked，打印「Run as root, or install the
  udev rule」——把权限问题指给一个不存在的设备。上游基线（`807b681`）写的是
  `uevent.split('/')[4]`，是本仓库重写协议层时引入的回归。
  **没有任何自动化路径能发现它**：`tests/test_cli_features.py:86,229,240,395` 与
  `tests/test_cli_alerts.py:56` 全都 monkeypatch 掉 `detect_device`/`detect_devices`，
  `scripts/smoke.sh` 全局 `MSI_PSU_DEMO=1`（demo 在 sysfs 之前就返回），而
  `docs/requirements-traceability.md` 那一行还写着「测试：`test_psu_sensors.py`、
  `test_demo.py`」——两个文件里都没有发现逻辑的测试。
  现新增 `tests/test_protocol_discovery.py`（16 条）：把扫描路径提成
  `protocol.SYSFS_HIDRAW_GLOB`，测试用**假 sysfs 树**跑真解析器（不 stub），覆盖 5 个
  PID、错误厂商/未知型号/畸形 `HID_ID`/空值/uevent 不可读、排序、去重，两条端到端
  只 stub `HIDDevice`/`MSIPSU` 走 `monitor.resolve_device()`（真路径 + blocked 语义），
  一条钉「扫描模式的两级父目录就是节点名」防漂移，一条证明 demo 模式不过 sysfs。
  把修复改回 `/dev/device`，16 条里 12 条失败（已实测）。

### 只读复核（turn7）tests-truth 车道：跑一次单测会写用户真实的 state.json（本轮，P1）

- `tests/test_cli_alerts.py` 是唯一没有隔离 state 目录的 CLI 测试模块（`test_cli_features.py`
  的 autouse fixture 只作用于自己那个文件），却把 `monitor.main()` 跑到最后：`run_once()`
  会 `prune(days=cfg['retention_days'])` + `save()`，用的是**默认**目录与**默认** 30 天保留。
  实测跑完该模块，`~/.local/state/msi-psu-monitor/state.json` 里出现了
  `{"product": "MPG Ai1600TS", "serial": "", "count": 2, ...}`——用户配了 60 天也照裁 30 天。
  测试看不见这次写入，所以一直绿。现把 autouse 的 `isolated_state` 提到
  `tests/conftest.py`（对全套生效，新模块不可能忘记），并加一条不靠同义反复的护栏：
  先删掉 override 证明默认目录确实不同，再桩住 `MonitorState.save` 记录本次运行写过的
  每个路径，要求全部落在 tmp 里。

### 真机验收（`docs/verify.md` §8，共 18 项，均待样机）

诊断命令与判定标准在 `docs/verify.md` §8；这里只列清单，项数与它逐条对齐（文档测试强制）。

1. `--once` 读数与 MSI Center 对照（误差 <1%）。
2. 抓包核对 62B 与 40B 变体的 `0xE0` 布局。
3. Ai1300TS（PID `0xAA6F`）变体识别。
4. `--fan-duty 0/50/100` 读回一致 + F1h 断电重启后仍生效。
4b. `[fan] mode = customized` 的 daemon 恢复确实改写了电源侧设置（`journalctl` 有
   `Restored the configured fan profile`）。
5. 满载 >12A/针差 >5A 能触发告警。
6. 拔插 5 次失败后 daemon 自动重连。
7. 72h 烤机 kWh 与插座功率计积分对照。
8. `--ocp` 阈值与 MSI Center/出厂规格一致，且连接器状态与 `12V-2x6 Status` 行不矛盾。
9. `--ocp` 在 MEG P 系上输出单多轨标志，与 MSI Center 开关一致（不发 NAK、不超时）。
10. `--ocp` 在 MEG Ai1600T 上打印「not available」并 exit 0（不发 NAK、不超时）。
11. `--zero-fan on/off` 读回一致（42h byte 4）+ `F1h` 断电重启后仍生效；
    `--buzzer-off` 能让 12+4 OCP 蜂鸣停止（无回读，听感确认），再按一次确认是否为
    MSI 命名的 switch。
12. `--set-rail multi/single` 在 MEG Ai1000P/Ai1300P 上读回一致、断电重启后保持；
    MPG TS/Ai1600T 拒绝且 exit 1。
13. 切换前后 `--ocp` 的 multirail 标志一致，单/多轨 OCP 行为与 MSI Center 一致。
14. MEG 上 `AC Input`（0x20）接近市电；TS 不显示且不产生 NAK 重试。
15. 真实告警/恢复各写一行 `alerts-*.log`，`--show-alert-log` 可读，5 MiB 轮转正常。
16. daemon 运行时 dashboard 每秒前进（`/api/live` 200），停 daemon 后 10 s 变 503/stale。
17. `systemd-analyze security` 无 PrivateDevices、无多余 capability，hidraw 仍可打开。

## 决策记录（本轮新增）

- **单多轨检视提前落地**：需求把「單多軌模式檢視」列在二期，但它是同一个 `0xC0`
  地址的只读读法（`CPSU.cs:823`，1 字节，`==2` 为多轨），零写入风险，因此与一期
  `--ocp` 一并做出：MPG TS 出 12V-2x6 阈值，MEG P 系出单多轨模式，Ai1600T 打印原因。
- **demo 覆盖全机型**：`MSI_PSU_DEMO_MODEL` 让多轨/单轨两条路径在无硬件时可端到端跑
  （CLI/daemon/prometheus/history/export），此前它们只有单测覆盖。
- **风扇 Profile 恢复放在 daemon**：`[fan] mode/duty/zero_fan` 是 opt-in，daemon 每次
  打开/重连 PSU 重发 41h + F1h（及 43h + F1h）；不配置则永不写电源。
- **打包根目录权限**：`mktemp -d` 的 0700 会被 `dpkg-deb` 收进 `./`，已在
  `build_deb.sh` 里 `chmod 755`。

### 可选增强（非阻塞）

- dashboard 页内 JS 保留内嵌（有意决策：`.deb` 无需 package-data，服务器单文件可审计）；
  `do_HEAD` 语义已补全（与 GET 同状态、同 Content-Type、同 Content-Length，含 404/400）。
- `0xC0` 8 字节 OCP 阈值写入（仍冻结；MSI Center 也无 UI 入口）；单多轨切换已以
  `--set-rail` 提前落地，需样机确认写入安全。
- `0xE1` 告警位图之外的二级告警源（当前 E1h + 软件镜像足够）。

## turn12（2026-10-19）：全量复核 + MSI 功能补齐 + 发布安全基线

- 全量读取 psu-file 的 01-06（REV6、产品页、MSI Center PSU 源码/CRA、参考实现、11 张截图、
  官网存档），3 个并行审计交叉核对；02/04 为准，01 的讨论与冻结项按变更控制处理。
- 功能补齐：VIN(0x20，非 TS)、多轨切换 `--set-rail`、AlertLog + `--show-alert-log`、
  Dashboard CPU/GPU 曲线 + 1 s `/api/live`、`--fan-mode performance` 别名。
- 安全：systemd 地址族/能力/Proc 收敛、设备字符串与 Prometheus 标签清洗、写操作审计行、
  SBOM 生成 + release 集成、SECURITY/support/incident-response 文档。
- 测试 569（新增 VIN/AlertLog/live/rail/性能/清洗/发布安全）；smoke 58 不变；
  3.10/3.12 裸环境与 ruff/mypy 在本轮末尾复跑。
- 变更控制：官网零 Python 覆盖 01 的「源码 .deb 依赖 python3」冻结；8 字节 OCP 阈值写仍冻结，
  多轨 1 字节写仅显式 `--set-rail`，需真机验证。
