# 开发进度

> 最后更新：v2 改造「一期」功能全部落地（CLI/daemon/dashboard/状态/打包/systemd/文档/测试）。
> 验证方式见 [`docs/verify.md`](docs/verify.md)（无硬件可全链路自检）。

## 已完成

### 一期功能（全部完成）

| 模块 | 内容 |
|------|------|
| **CLI** | `--once`/`--watch [秒]`/`-f text,json,prometheus`/`-O`/`--serial`/`--show-log`/`--export --from 30m\|2h\|7d --columns`/`--dashboard [--port]`/`--no-alerts`/`--config`/`-v`/`-q`/`--version`；退出码 0/1/2 |
| **风扇控制** | `--fan-mode auto\|customized`、`--fan-duty 0-100`（41h 写 + F1h 保存 + 3 次读回验证）；41h/42h 读显示 |
| **告警** | E1h 告警位图 + 12V-2x6 每针软件镜像（单针 ≥12A、同 6 针连接器针差 >5A）；`AlertEngine` 去抖（默认连续 2 次）；`ALERT [severity] name: desc` 走 stderr，exit 2 |
| **状态落盘** | `state.json`（AVG 功率/效率、`Time_Daily`/`Time_Total`、kWh 冻结积分、30 天日桶）+ `daily-YYYYMMDD.log`（1 分钟 1 行 9 列 CSV，30 天保留）；全部 `.tmp` + `os.replace` 原子写 |
| **daemon** | `msi-psu-monitor-daemon`：1s 采样判警、30s 原子写 prometheus、60s 追加历史、1h 轮转；连续 5 次读失败重扫设备；SIGINT/SIGTERM 干净退出 |
| **dashboard** | `--dashboard` 起 stdlib `ThreadingHTTPServer`，仅绑 `127.0.0.1:8899`；7 条实时曲线 + 每周能量柱状 + 每图 PNG/CSV 导出；端点 `/`、`/api/history`、`/api/state`、`/api/export` |
| **demo 模式** | `MSI_PSU_DEMO=1` 合成 PSU（5 分钟 idle→满载→idle 循环、零风扇随负载、per-pin 轻不平衡、黑盒预置 2 条）；`MSI_PSU_DEMO_ALERT=<name>` 卡告警位 |
| **打包** | `scripts/build_deb.sh` → `dist/msi-psu-monitor_1.0.0_all.deb`（2 个 console script、systemd unit、udev 规则、文档；postinst 自动 reload + enable） |
| **systemd** | `msi-psu-monitor.service`（`Type=simple` + `Restart=always` + `StateDirectory`，**不加 `PrivateDevices`**）；旧 timer 方案已废弃并删除文件 |
| **文档** | `README.md`、`AGENTS.md`、`msi_psu_monitor/AGENTS.md`、`docs/protocol.md`、`docs/verify.md`、`docs/msi-psu-monitor.conf.example` |

### 数据正确性修复（P0，已冻结）

- **FW revision**：TS 按 2 字节 ASCII 透传（`1.0`），非可打印才回退；废弃旧的 `<I` 十进制拼法。
- **Serial**：TS 的首字节是长度前缀，按长度切片，不再把长度当号码。
- **PID**：补齐 `0xAA6F`（Ai1300TS），共 5 个 `0db0:*`。
- **未知机型拒解**：产品字符串匹配不上时抛错，不再猜布局。
- **变体分派**：按产品字符串子串（`Ai1600TS` → mpg 先于 `Ai1600` → meg，然后 `Ai1300`/`Ai1000`），**不按 PID**。
- **LINEAR11 尾数符号**：REV6 无符号（`signed=False` 仅风扇 RPM），调用点四舍五入（V/A 3dp、W 1dp、% 2dp、RPM int）。

### 质量门禁

```
uv run --group dev pytest -q              → 145 passed
uv run --group dev ruff check .           → All checks passed
uv run --group dev mypy msi_psu_monitor/  → 10 files, no issues
```

运行期零第三方依赖（`pyproject.toml` 的 `dependencies = []`），仅 dev 组含 pytest/ruff/mypy。

## 待办

### 外部阻塞

- **Q6 EPS 数量**：等 MSI 回函；未回前按 2×EPS 处理。
- **Q10 Pin6 / AVG 数值**：待真机复核。
- **内核模块**：`kernel/msi-psu-ai1600ts.patch` 需 Proxmox 7.0 内核头文件，仓库内无法构建；用户态工具是受支持路径。

### 真机验收（`docs/verify.md` §8，共 7 项，均待样机）

1. `--once` 读数与 MSI Center 对照（误差 <1%）。
2. 抓包核对 62B 与 40B 变体的 `0xE0` 布局。
3. Ai1300TS（PID `0xAA6F`）变体识别。
4. `--fan-duty 0/50/100` 读回一致 + F1h 断电重启后仍生效。
5. 满载 >12A/针差 >5A 能触发告警。
6. 拔插 5 次失败后自动重连。
7. 72h 烤机 kWh 与实测电量对照。

### 可选增强（非阻塞）

- dashboard 页内 JS 抽到独立 `static/`，并补 `do_HEAD` 语义。
- `0xC0` OCP 阈值写入（三期专批，需样机确认写入安全）。
- `.github/workflows/ci.yml` 已引用 `uv sync --group dev`（dev 组已恢复，可直接用）。
