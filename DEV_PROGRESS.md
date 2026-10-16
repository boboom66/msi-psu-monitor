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
uv run --group dev pytest -q                     → 414 passed
uv run --group dev ruff check .                  → All checks passed
uv run --group dev ruff format --check .         → 32 files already formatted
uv run --group dev mypy msi_psu_monitor/         → 10 files, no issues
bash scripts/build_deb.sh                        → dist/msi-psu-monitor_1.0.0_all.deb
bash scripts/smoke.sh                            → 53 项全过（三种格式/告警按机型/黑盒/OCP/风扇/daemon/dashboard）
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

### 文档不实（本轮又抓到一处）

- `DEV_PROGRESS.md` 的真机验收小节声称 10 项、下面只列 9 条，`requirements-traceability.md`
  也引用 10 项，而 `verify.md` §8 实际有 11 条（4b 与 Ai1600T 那条是后加的，没回头同步总数）。
  现全部改为 11 项，并加文档测试 `test_the_quoted_real_hardware_check_count_matches_verify_md`
  把「§8 里的编号条目数 == 文档里引用的总数 == DEV_PROGRESS 列表条数」变成机器护栏。

### 真机验收（`docs/verify.md` §8，共 11 项，均待样机）

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
