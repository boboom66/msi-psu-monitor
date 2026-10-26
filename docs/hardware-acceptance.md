# 硬件验收：机器到了之后怎么做

本文档是给“PM 寄来测试机 + MSI PSU”用的最短路径。所有命令都在测试机上执行，
不需要预先安装 Python（若二进制能运行）。

## 1. 机器准备

推荐 **原生 Ubuntu 24.04 LTS Desktop/Server**（x86_64）。也支持 Ubuntu 22.04：
kit 里的二进制若因 glibc 不匹配无法运行，`setup.sh` 会自动回退到随包源码
（使用系统 Python 3.10+，不需要 pip/网络）。

不要用 WSL 直接测 USB：WSL 的 USB 设备透传不稳定，hidraw 往往看不到。
如果是虚拟机，必须把 PSU 的 USB 设备以 USB 3.0 方式直通给虚拟机。

硬件连接：

- 把 PSU 的 **USB 数据线**接到主板/测试机（不是只接风扇线）；
- 开机进入系统后执行 `lsusb | grep -i 0db0`，应看到 `0db0:808c/aa6f/56d4/e749/c9eb` 之一；
- 执行 `ls -l /dev/hidraw*`，应出现 hidraw 节点。

## 2. 安装工具包

把 `msi-psu-monitor-hardware-kit-<version>-linux-x86_64.tar.gz` 拷到测试机（U 盘/SCP 均可）：

```bash
sha256sum -c msi-psu-monitor-hardware-kit-*.tar.gz.sha256
tar xzf msi-psu-monitor-hardware-kit-*.tar.gz
cd msi-psu-monitor-hardware-kit-*
sudo ./setup.sh
```

`setup.sh` 会：

- 优先使用包内自包含二进制（目标机不需要 Python）；
- 若二进制因 glibc/架构不匹配无法运行，则回退到 `source/` + 系统 Python 3.10+；
- 安装 udev 规则、systemd unit、`/etc/msi-psu-monitor.conf`；
- 安装可选证据工具 `jq curl usbutils`（无网络时跳过，不影响只读验收）；
- 用 demo 数据自检安装后的命令。

它**不会**自动启动 daemon；需要时再 `sudo systemctl start msi-psu-monitor`。

## 3. 只读验收（默认，安全）

```bash
sudo ./acceptance.sh
```

它会自动检查：

1. 版本/身份；
2. `--once` 文本、JSON、Prometheus；
3. `-O` 文件输出；
4. `--ocp`、`--show-log`、`--show-alert-log`；
5. `--watch` 多帧；
6. daemon 两次采样 → state/history/prom/latest；
7. Dashboard 的 `/`、`/api/state`、`/api/live`、`/api/export`；
8. CSV 导出；
9. 本地阈值告警：临时 `[alerts] power_w = 1` 触发 `exit 2` + `power_high` +
   `Thresholds` 行；`--dump-config` 打印 `[alerts]` 生效值；
10. 报告中列出 MANUAL 项（需要你对照 MSI Center / 实际负载确认）。

报告与证据在 `/var/log/msi-psu-acceptance/<时间>/`，并自动打包为同前缀 `.tar.gz`。
把 tar.gz 发回即可。

**DEMO 自测**（没有硬件时验证工具链）：

```bash
./acceptance.sh --demo
```

DEMO 结果不能证明真实硬件通信；报告里会明确标注。

## 4. 写入验收（可选）

确认只读项通过后，再考虑写入。默认不写电源。

```bash
sudo ./acceptance.sh --writes
```

脚本会先询问；写入项包括风扇 duty 60 并恢复原设置。`--zero-fan`、
`--buzzer-toggle`、`--set-rail` 会以手动命令形式提示，因为：

- 蜂鸣器 C2h 没有回读，无法从脚本确认状态；
- 多轨切换需要真机确认断电保持/OCP 行为；
- Zero Fan 只在 12+4 TS 机型可读回；
- 12V-2x6 OCP 阈值写（MPG TS）**不自动执行**：先 `--dump-thresholds -f json` 留底，
  手写一组合法值并读回/断电保持验证，然后 `--load-thresholds` 恢复；详见
  [verify.md](verify.md) §2.2 与 §8 第 13b 项。

手动写入前请阅读 [verify.md](verify.md) §8，并确认当前没有重要负载。

## 5. 手工对照项

报告中的 MANUAL 项不会自动 PASS：

- 与 MSI Center 对照电压/电流/功率/效率/温度/风扇；
- 12V-2x6 每针电流与状态在负载下是否合理；
- 待机是否误报、真实告警是否出现并恢复；
- 若执行 `--writes`，风扇声音/转速是否变化，Zero Fan/蜂鸣器是否符合预期；
- MEG 机型：`AC Input` 是否接近 220-240 V；多轨切换后是否保持。

## 6. 启动常驻 daemon / Dashboard

```bash
sudo systemctl enable --now msi-psu-monitor
journalctl -u msi-psu-monitor -f
msi-psu-monitor --dashboard --port 8899
```

如果是远程无桌面：

```bash
ssh -L 8899:127.0.0.1:8899 user@test-machine
# 本地浏览器打开 http://127.0.0.1:8899
```

Dashboard 只监听 loopback；非 loopback Host 会返回 421。

## 7. 证据与排错

证据文件包括：

- `environment.txt`（OS/kernel/arch/glibc/lsusb/hidraw/dmesg）；
- 每条命令的 stdout/stderr；
- `report.md`；
- daemon 的 state/history/prom/latest；
- dashboard 响应与 CSV。

排错：

| 现象 | 处理 |
|---|---|
| `lsusb` 看不到 `0db0` | 换 USB 数据线/端口；确认是 PSU 的数据口，不是风扇/ARGB 口 |
| 有 lsusb 无 `/dev/hidraw*` | `sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=hidraw`；重新插拔 |
| `Permission denied` | 用 sudo；或确认 udev uaccess 规则已加载 |
| `busy` | 停掉 MSI Center/其他占用进程；`systemctl stop msi-psu-monitor` |
| 二进制报 GLIBC 错误 | `sudo ./setup.sh --source` 使用系统 Python 回退 |
| 22.04 无 Python 3.10 | 安装系统自带 `python3`（Ubuntu 22.04 默认 3.10） |
| Dashboard 无数据 | 先让 daemon 跑一次；检查 `/var/lib/msi-psu-monitor/latest.json` |

## 8. 卸载

```bash
sudo ./uninstall.sh            # 保留配置和 state
sudo ./uninstall.sh --purge    # 删除配置和 state
```

## 9. 结果判定

- 自动项全 PASS、MANUAL 项已确认，且报告注明真机（非 DEMO）→ 可进入发布验收；
- 任一 FAIL 或仍有未解释的 MANUAL → 把证据 tar.gz 发回，先不要宣布通过；
- DEMO 报告不能替代真机报告。
