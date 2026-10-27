# Agent 产品评审与 UX 改造 Playbook

> 目标：把“功能存在”变成“用户可用、好用、可验证”。
> 适用：`msi-psu-monitor` 1.0.x，OpenCode + `opencode-go/glm-5.3-flash` /
> `opencode-go/deepseek-v4.1-flash` / `opencode-go/qwen3.8-flash`（仅升级）。
> 核心原则：**先只读盘点 → 再设计 → 再实现 → 再验收；作者 ≠ 评审；证据优先；允许删减。**

## 0. 和“缺陷审计”的区别

上一版提示词解决“代码对不对”。这一版解决：

1. 这个功能值得存在吗？（用户 job、使用频率、差异化、维护成本）
2. 用户能不能发现、学会、完成、恢复？
3. 和同类工具比，差在哪？
4. 功能是否完整（happy / empty / error / help / docs / tests）？
5. 改造后是否真的更好（任务级验收，而不是“看起来更专业”）？

**产品级不是“功能多”，而是“每个用户旅程都有完整、可恢复、可验证的路径”。**

---

## 1. 三条主线

| 主线 | 问题 | 产物 |
|---|---|---|
| 功能组合 | 哪些保留 / 改进 / 替换 / 删除？ | Feature Card + 优先级 |
| 用户旅程 | 新用户 / 运维 / 评测人员能否完成目标？ | Journey friction 表 |
| 体验质量 | 输出、错误、帮助、性能、可访问性 | UX rubric + 验收任务 |

优先顺序：**功能组合 → 用户旅程 → 体验细节**。不要一上来改颜色和对齐。

---

## 2. 模型分工

| 阶段 | 模型 | 原因 |
|---|---|---|
| P0 功能盘点 / Feature Card | **GLM-5.3-Flash**（DeepSeek 可做机械提取） | 需要判断“值不值得存在” |
| P1 参考实现对比 | **GLM-5.3-Flash** 选型，**DeepSeek** 批量收集 | 判断 + 执行分离 |
| P2 Persona / Journey 走查 | **GLM-5.3-Flash** | 需要同理心和反事实推理 |
| P3 重设计方案 | **GLM-5.3-Flash** | 架构、交互、兼容性权衡 |
| P4 实现 | **DeepSeek**（高风险用 GLM-5.3-Flash） | 边界清晰、迭代快 |
| P5 可用性验收 | **GLM-5.3-Flash**（作者 ≠ 评审） | 需要独立判断 |
| P6 发布 / UX 门禁 | **GLM-5.3-Flash 判，DeepSeek 跑** | 判断 + 证据 |
| 升级/裁决（少量） | **Qwen3.8 Flash** | G/F 两次失败或结论冲突；≤3 次/阶段 |

**规则：**

1. 同一件事不要让同一个模型“又设计又验收”。
2. 一个会话只做一个功能或一条旅程；不要把 20 个 flag 塞进一个 prompt。
3. 让模型看**真实输出/截图/终端捕获**，不要让它凭空想象 UI。
4. 允许模型说“删除这个功能”；功能全面不等于功能堆砌。
5. 设计阶段禁止写代码；实现阶段禁止改验收标准。
6. **Qwen3.8 Flash 只做升级**：G/F 两次失败或结论冲突时才用；每阶段 ≤3 次，总计 ≤10 次；每次记录在 `DECISIONS.md`。不要用它做日常实现/文档。

---

## 3. 提示词链

### P0 — 功能盘点与基线（只读，GLM-5.3-Flash）

```text
# ROLE
你是产品负责人 + 资深 Linux 工具 UX 评审员，熟悉 CLI/TUI/Web/daemon/打包的
“首次体验”和“错误恢复”。你的任务不是改代码，而是判断每个功能是否值得存在、
是否完整、是否好用。

# MISSION
只读盘点 <repo> 的所有用户可见功能，建立 Feature Card、用户旅程图和 UX 风险表。
不要修改任何文件，不要先给实现方案。

# BASELINE
- repo: <path>
- commit: <sha>，干净 worktree
- 环境: Ubuntu 22.04 / 24.04（说明实际环境）
- 已运行: <commands + results>
- 无硬件时: MSI_PSU_DEMO=1；不得执行任何写 PSU 的命令

# SOURCES OF TRUTH
1. 当前 commit 的代码与测试
2. 实际 `--help`、示例输出、截图、错误信息
3. README / docs/verify.md / docs/protocol.md
4. 历史文档（DEV_PROGRESS、docs/archive/testing/*）只作线索，不得当作当前事实

# 必须覆盖的功能
- 采集：--once（text/json）、--watch、--format、--output、--serial
- 交互：--dashboard-text、--menu、--watch 的 TUI 重绘
- Web：--dashboard、--port、/api/live、时间范围、空/过期/错误状态
- 历史：--export、--from、--columns、daily-*.log、state.json、CSV 列
- 告警：E1h、[alerts] 本地阈值、--show-alert-log、exit 2、daemon 告警日志
- 控制：--fan-mode、--fan-duty、--zero-fan、--buzzer-off、--set-rail
- OCP：--ocp、--dump-thresholds、--ocp-set、--load-thresholds、--show-log
- 运维：daemon、Prometheus、alert rules、--dump-config、systemd/udev
- 交付：.deb、tar、二进制、hardware kit、install/uninstall、demo
- 支持：--help、--version、docs、troubleshooting、诊断信息

# METHOD
1. 尽量实际运行 demo，收集真实输出；不能运行的标 BLOCKED，不要编造。
2. 每个功能一张 Feature Card：
   - ID / 名称 / 入口（flag、config、daemon、HTTP）
   - 目标用户与 JTBD（当…我想…以便…）
   - 当前体验（实际命令 + 输出/截图）
   - 摩擦点（发现、学习、完成、恢复、性能、可访问性）
   - 参考实现（1-2 个同类工具）
   - 完整度：happy / empty / error / help / docs / tests
   - 决策建议：Keep / Improve / Replace / Remove
   - 优先级：P0/P1/P2/P3 + 理由
   - 验收任务（用户能完成什么）
3. 标出以下问题：
   - 同名不同义（例如“off”实际是 toggle）
   - 同义不同名（watts/W、rpm/RPM、mode/curve）
   - 隐藏功能（代码有、--help/README 没有）
   - 无错误路径（失败时只说 Error）
   - 无验收测试（只有实现，没有用户任务）
   - 功能重叠（--menu vs --dashboard-text vs --watch）
4. 用 3 个 persona 走 6 条 journey，记录 friction：
   - A：第一次用的 homelab 用户（不熟 Linux 硬件权限）
   - B：管理 20 台机器的 sysadmin（systemd/Prometheus/升级）
   - C：硬件评测/OCP 验证人员（写保护值、读回、恢复）
   - J1 安装 → 第一次读数
   - J2 日常监控 → 发现异常
   - J3 告警 → 诊断 → 恢复
   - J4 改设置（fan/rail/OCP）→ 验证 → 撤销
   - J5 导出/报告 → 分享
   - J6 升级/卸载 → 无残留

# EVIDENCE RULES
- 每条结论给实际输出、file:line 或截图路径。
- 没运行就说没运行；UNKNOWN 不算 PASS。
- 不把 demo/mock 当硬件证据。
- 不修改文件、不执行写 PSU 的命令。

# OUTPUT
1. Feature inventory 表（每行一个功能，字段同上）。
2. Journey friction 表：persona × journey × 摩擦 × 严重度 × 证据。
3. Top 10 UX 风险（用户影响 × 频率 × 修复成本）。
4. 功能组合建议：Keep / Improve / Replace / Remove，附理由。
5. 5 个“先别写代码”的问题，需要用户拍板。
6. 建议的 P0/P1 设计卡工单，每个 ≤1 个功能。

# STOP
需要真机/写操作/协议歧义 → 标 BLOCKED 并提问，不要猜。
```

---

### P1 — 参考实现对比（GLM-5.3-Flash 选型，DeepSeek 收集）

```text
# MISSION
为 <feature> 找 5 个同类实现，输出“可借鉴的模式”，不复制代码。
只比较行为、交互、打包、测试策略；不比较代码风格。

# REFERENCE MAP
- CLI / 设备发现：liquidctl
- 实时 TUI：btop、nvtop、s-tui
- 菜单：nmtui、raspi-config
- Web dashboard：netdata、Cockpit、Glances
- Prometheus：node_exporter、smartctl_exporter
- 告警/守护进程：smartd
- 硬件控制/udev：liquidctl、coolercontrol、OpenRGB
- 历史/导出：sar、vnstat、sensors
- 诊断：powertop、nvidia-smi
- 打包：Debian Policy、lintian、systemd/udev 文档

# COMPARE
1. 首次安装 → 第一次成功使用需要几步？
2. 设备发现/多设备：有没有 list/select？默认值是否安全？
3. 默认输出：一屏能不能看懂？单位、对齐、颜色、无颜色？
4. 高级输出：JSON/CSV/Prometheus 的命名是否一致？
5. 错误信息：说清楚“发生了什么、为什么、下一步”？
6. 帮助：--help 是否按任务分组？有没有示例？
7. 配置：默认值、优先级、校验、--dump-config？
8. 写操作：dry-run、确认、读回、撤销/恢复？
9. 告警：是否可行动？是否去重/恢复？
10. 打包/升级/卸载：是否一条命令？是否有残留？
11. 测试：有没有用户任务级测试，而不只是单测？
12. 文档：quick start 是否可复制执行？有没有截图/故障排查？

# OUTPUT
| 参考项目 | License | 值得借鉴的 3 个做法 | 如何迁移到本项目 | 风险/不适用 |
...

# RULES
- clean-room：只借鉴交互和模式，不复制代码。
- GPL 项目（liquidctl/coolercontrol/OpenRGB 等）以各自 LICENSE 为准；
  本项目 MIT，不能把 GPL 代码粘进来。
- 每条参考给 URL；不能联网就标 UNKNOWN。
```

---

### P2 — Persona / Journey 走查（GLM-5.3-Flash）

```text
# PERSONAS
A. 新用户：刚买 MSI PSU，第一次在 Ubuntu 上用硬件监控工具；会 sudo，但不熟 udev。
B. Sysadmin：20 台机器，systemd + Prometheus + 远程升级；关心稳定、可观测、回滚。
C. 评测人员：要验证 12V-2x6 OCP 阈值；关心写入安全、读回、断电保持、恢复。

# JOURNEYS
J1 安装 → 第一次读数（5 分钟内？）
J2 日常监控 → 发现异常（TUI/Web/Prometheus）
J3 告警 → 诊断 → 恢复（exit 2、alert log、dashboard）
J4 改设置（fan/zero fan/rail/OCP）→ 验证 → 撤销
J5 导出/报告 → 分享（CSV/JSON/截图）
J6 升级/卸载 → 无残留

# TASK
对每个 persona × journey：
1. 写出用户的实际步骤（命令、点击、读到的文字）。
2. 标出 friction：找不到入口、看不懂输出、不知道怎么修、怕写坏硬件、升级破坏配置。
3. 给严重度 P0-P3 和证据（实际输出/截图）。
4. 回答：如果只能改一个地方，改哪里收益最大？
5. 回答：这个功能如果删掉，用户会用什么替代？如果答不上来，考虑删除。

# OUTPUT
- persona × journey 矩阵
- Top 10 friction（按“用户放弃概率”排序）
- 每个 persona 的“最小可用体验”定义
- 3 个“ delight ”机会（不是必须，但能让产品脱颖而出）
```

---

### P3 — 重设计方案（GLM-5.3-Flash，不写代码）

```text
# MISSION
基于 P0-P2，为每个 P0/P1 问题给一张设计卡。不要写代码，不要改文件。

# DESIGN CARD
- ID / 功能 / 目标用户 / JTBD
- 现状：实际输出/截图 + 摩擦
- 目标：用户完成后能做什么
- 方案 A：最小改动（兼容优先）
- 方案 B：理想设计（可以破坏兼容，但给迁移）
- 命令/输出示例：before → after，必须能直接复制
- 交互：键位、确认、取消、退出、非 TTY 回退
- 错误文案：发生了什么 / 为什么 / 下一步
- 兼容性：旧 flag、旧 JSON/CSV、旧配置、旧 state
- 验收任务：3-5 条用户任务
- 工作量 / 风险 / 依赖
- 决策：Keep / Improve / Replace / Remove

# 特别要求
- 每张卡必须回答“为什么现在的做法不够好”，不能只说“更好”。
- 不允许用“增加一个 flag”解决 discoverability，除非证明这是最小方案。
- 写操作必须有 dry-run / 确认 / 读回 / 撤销或恢复路径。
- 优先减少概念数量：能合并的合并，能删的删。
- 给一个 now / next / later 路线图，按用户价值 ÷ 成本排序。

# OUTPUT
- 设计卡（每张 ≤1 页）
- 统一命名/单位/退出码矩阵
- 迁移与弃用计划
- 需要用户拍板的 5 个问题
```

---

### P4 — 单功能实现（DeepSeek，高风险用 GLM-5.3-Flash）

```text
# TICKET
UX-<id>: <one sentence>
Design: <link to design card>
Severity: P1
Allowed files: ...
Non-goals: ...

# ACCEPTANCE（先写测试）
1. 用户任务：<persona> 能在 <步骤> 内完成 <目标>。
2. 期望输出/截图：<before/after>。
3. 错误状态：<no PSU / permission denied / unsupported model / stale dashboard>。
4. 兼容性：旧 flag/JSON/CSV/配置/state 不变，或给出迁移。
5. 文档：--help、README、CHANGELOG 更新。

# PROCESS
1. 先加/更新 acceptance test；在当前代码上失败，贴出失败输出。
2. 最小实现；不得删除/跳过/弱化现有测试；不得新增运行时依赖。
3. 跑 gates：ruff / format / mypy / pytest / coverage / smoke。
4. 更新 --help 示例和 README 对应段落。
5. 如果发现设计卡不成立，停下报告，不要扩大改动。

# OUTPUT
- 用户任务 before/after
- diff 摘要
- 失败测试 → 通过测试
- 兼容性/回滚
- 未覆盖的边界
```

---

### P5 — 可用性验收（GLM-5.3-Flash，作者 ≠ 评审）

```text
# ROLE
独立验收人。你没有参与实现，不要相信作者的解释，只相信实际输出、截图和任务完成情况。

# TASKS（逐条 PASS/FAIL/UNKNOWN）
1. 干净 Ubuntu 22.04/24.04：从 README 到第一个读数，计时；超过 5 分钟记 FAIL。
2. 没有 PSU：错误信息是否说明“没找到设备 / 权限 / 下一步”？
3. 不支持的型号：是否解释原因，并以 0 或明确错误退出？
4. 权限不足：是否给出 udev/sudo 的具体下一步？
5. daemon 未运行：dashboard 是否 503/显示“stale”，而不是冻结图表？
6. 告警：消息是否包含 measured vs limit、severity、下一步？
7. fan/rail 写：是否有确认/读回/撤销？
8. OCP 写：是否有 dry-run、备份、读回、断电保持、restore？
9. export：列名、单位、时区、空数据、stdout (`-O -`) 是否可用？
10. 升级：配置/state 是否保留？失败是否可回滚？
11. 卸载：是否无残留（unit/udev/config/state）？
12. TUI 80x24 / 120x40：是否可读、可退出、可 resize？
13. Web 320/768/1920：是否可读、无横向滚动、颜色不是唯一信号？
14. `--help`：能否在 30 秒内找到目标功能？
15. 文档：quick start 的命令能否直接复制执行？

# OUTPUT
| task | expected | actual | verdict | severity | fix |
...

# VERDICT
- SHIP / SHIP WITH KNOWN ISSUES / NOT READY
- 每个 FAIL 给最小修复和验收命令
- UNKNOWN 不算 PASS
```

---

### P6 — 发布 / UX 门禁（GLM-5.3-Flash 判，DeepSeek 跑）

```text
# MISSION
最终产品门禁：确认没有 P0/P1 UX 问题，所有关键旅程有证据，文档/截图与构建一致。

# CHECKS
- Feature Card 全部有 Keep/Improve/Replace/Remove 决策，且已执行或记录债务。
- 0 个 open P0/P1 UX 问题。
- 安装 → 第一次读数 ≤5 分钟（干净环境，含文档）。
- 5 个型号 × 关键旅程有真机证据（或明确 BLOCKED）。
- OCP 写：dry-run/备份/读回/断电保持/restore 全部有记录。
- 告警：measured vs limit、恢复、exit code、alert log 一致。
- TUI/Web：空/过期/错误/小屏/无颜色 全部可用。
- 升级/卸载：配置/state 保留；无残留。
- Prometheus：promtool 通过；命名警告有决策。
- 文档：README/--help/截图与当前版本一致；无 803/859 漂移。
- 产物：.deb/tar/kit 可安装；无 Python 依赖；SHA256/SBOM。

# VERDICT
SHIP / SHIP WITH KNOWN ISSUES / NOT READY
每个 FAIL 给 owner、证据、修复工单。
```

---

## 4. Feature Card 模板

| 字段 | 内容 |
|---|---|
| ID / 名称 | F-01 `--dashboard-text` |
| 入口 | CLI flag / config / daemon / HTTP / systemd |
| 目标用户 | A/B/C |
| JTBD | 当…我想…以便… |
| 当前体验 | 实际命令 + 输出/截图 |
| 摩擦 | 发现 / 学习 / 完成 / 恢复 / 性能 / 可访问性 |
| 参考 | btop / nvtop / liquidctl |
| 完整度 | happy / empty / error / help / docs / tests |
| 决策 | Keep / Improve / Replace / Remove |
| 优先级 | P0/P1/P2/P3 + 理由 |
| 验收任务 | 用户能完成什么 |

---

## 5. 功能组合评分

对每个功能打分（1-5）：

| 维度 | 问题 |
|---|---|
| 用户价值 | 不做这个，用户会痛吗？ |
| 使用频率 | 每天 / 每周 / 一年一次？ |
| 差异化 | 竞品没有，或我们明显更好？ |
| 维护成本 | 代码、测试、文档、支持成本？ |
| 风险 | 写坏硬件/安全/数据损失？ |
| 完整度缺口 | happy/empty/error/help/docs/tests 缺几个？ |

排序：**高价值 × 低风险 × 低维护成本** 先做；**低价值 × 高维护成本** 删除或延后。

---

## 6. UX Rubric（本项目）

1. **首次体验**：5 分钟内看到第一个读数；无需读源码。
2. **可发现性**：每个功能在 `--help` 或 README 有入口；`--help` 按任务分组。
3. **一致性**：同一个概念在 text/JSON/CSV/Prometheus/TUI/Web 用同一个名字和单位。
4. **错误可行动**：每个错误回答“发生了什么 / 为什么 / 下一步命令”。
5. **写操作安全**：dry-run、确认、读回、撤销/恢复；不可逆操作必须明确警告。
6. **降级**：无 TTY、无颜色、无浏览器、无 PSU、daemon 未运行，都有清晰状态。
7. **性能**：1s 刷新不闪烁；daemon RSS/fd 有上限；dashboard 不阻塞。
8. **可访问性**：颜色不是唯一信号；80x24 可用；320px 可用；NO_COLOR 生效。
9. **可恢复**：state 损坏、磁盘满、权限变化、拔插，都不需要重装。
10. **可支持**：`--version`、`--dump-config`、日志、诊断包足以定位问题。

---

## 7. 反模式

- 用“再加一个 flag”解决 discoverability。
- 用“全面重构”解决局部 UX 问题。
- 追求 100% 覆盖率，却没有用户任务级测试。
- 让同一个模型既设计又验收。
- 把 demo/mock 当硬件证据。
- 为了“功能全面”保留没人用的功能。
- 写操作没有 dry-run/撤销。
- 颜色是唯一状态信号。
- 破坏旧 flag/JSON/CSV/退出码，却不给迁移。
- 文档写 803/859/645 这种会漂移的数字。

---

## 8. 本项目建议先验证的假设

> 这些是**假设**，不是结论。P0 用实际输出/截图验证或推翻。

| # | 假设 | 参考 | 验证方式 |
|---|---|---|---|
| H-01 | 25+ 个扁平 flag 让 `--help` 难扫，新用户找不到入口 | liquidctl 的子命令 | 让 3 个新用户找“设置风扇”“导出 CSV” |
| H-02 | `--buzzer-off` 实际是 toggle，名字会误导 | smartctl 的显式动作 | 读代码 + 实际输出 |
| H-03 | `--fan-mode performance` 是 auto 的别名，概念重复 | liquidctl | `--help` + 文档 |
| H-04 | 没有 `--list`/`--device`，多 PSU 只能靠 `--serial` 猜 | liquidctl list | 无硬件/demo 走查 |
| H-05 | 没有 `--doctor`，权限/udev/state 问题只能看 traceback | nvidia-smi/liquidctl | 模拟 permission denied |
| H-06 | OCP 写缺少 dry-run/备份/restore 的引导 | smartctl/liquidctl | 读 `--ocp-set` 帮助 |
| H-07 | `--menu` / `--dashboard-text` / `--watch` 功能重叠 | btop/nmtui | 让用户选一个完成同一任务 |
| H-08 | dashboard 的空/过期/错误状态不够显眼 | netdata/Cockpit | 停 daemon、删 latest.json、截图 |
| H-09 | 告警文案可能缺少 measured vs limit / 下一步 | smartd | 触发本地阈值，读 ALERT 行 |
| H-10 | 退出码 2 同时表示“告警”和“用法错误”，脚本难区分 | POSIX/GNU 惯例 | 运行错误参数 + 触发告警 |
| H-11 | 安装需要 root/udev，首次体验摩擦大 | liquidctl 安装文档 | 干净 Ubuntu 计时 |
| H-12 | 文档数字/命令/截图与当前版本漂移 | — | 803/859/645 对比 |
| H-13 | 同一概念在 text/JSON/CSV/Prometheus/TUI/Web 命名/单位不一致 | node_exporter | 建命名矩阵 |
| H-14 | README 24KB，缺少“3 条命令 quick start”和截图/GIF | liquidctl/btop | 5 分钟首次体验 |
| H-15 | 错误信息只说 Error，没有下一步命令 | liquidctl/smartd | 抽取所有错误字符串 |
| H-16 | 没有支持包/诊断命令，用户只能贴 traceback | nvidia-smi/liquidctl | 模拟权限/设备缺失 |
| H-17 | fan/rail 写没有撤销/确认，OCP 写有范围校验但缺 dry-run 引导 | liquidctl | 读 `--help` + 实际写 |
| H-18 | demo 模式发现性低（环境变量），输出标注是否足够明显 | — | 新用户走查 |

---

## 8.1 先让 DeepSeek 做的 4 个低风险盘点（为 P0 准备素材）

这些任务不改行为，只产出事实，适合 DeepSeek V4.1 Flash：

1. **错误信息清单**：抽取 `parser.error`、`Error:`、`logger.error`、`ALERT` 的全部字符串，
   按“发生了什么 / 为什么 / 下一步 / 退出码”分类，标出不可行动的。
2. **命名/单位矩阵**：把 text、JSON、CSV、Prometheus、TUI、Web 的同一概念列在一张表里，
   标出不一致（例如 `power_total` / `power` / `POWER` / `msi_psu_power_watts`）。
3. **帮助/文档一致性**：把实际 `--help` 的 flag 与 README/docs 的表格对比，
   标出“代码有、文档没有”“文档有、代码没有”“名字不一致”。
4. **界面证据包**：在 demo 模式下截取：
   - `--help`、`--once`、`--once -f json`、`--watch 1`（2 帧）
   - `--dashboard-text` 80x24 / 120x40
   - `--menu` 主菜单 / 二级菜单 / 非 TTY
   - dashboard 320/768/1920，正常/空/daemon 停止/`latest.json` 删除
   把证据目录与索引写进本轮评审报告，并在 `docs/archive/testing/` 下留档，供评审复核。

---

## 9. 最小执行顺序

1. **P0**（GLM-5.3-Flash）：Feature Card + Journey friction，只读。
2. **P1**（GLM-5.3-Flash/DeepSeek）：参考对比，填表。
3. **P2**（GLM-5.3-Flash）：3 persona × 6 journey 走查。
4. **P3**（GLM-5.3-Flash）：设计卡 + now/next/later，用户拍板。
5. **P4**（DeepSeek/GLM-5.3-Flash）：一次一个功能，先失败测试后实现。
6. **P5**（GLM-5.3-Flash）：可用性验收，UNKNOWN 不算 PASS。
7. **P6**（GLM-5.3-Flash/DeepSeek）：发布门禁。
8. **升级**：G/F 两次失败或结论冲突 → Qwen3.8 Flash 裁决一次（≤3/阶段，总计 ≤10），记录 `DECISIONS.md`。

**不要跳过 P0-P3 直接让模型改代码。** 否则你会得到一堆“看起来更现代”的改动，但用户旅程仍然断裂。
