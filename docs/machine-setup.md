# 测试机系统准备（Ubuntu）

目标：机器到手后 30 分钟内进入可验收状态。

## 1. 选择系统

推荐 **Ubuntu 24.04 LTS Desktop x86_64**（原生安装，不是 WSL）。
也支持 Ubuntu 22.04：kit 的二进制若因 glibc 不匹配无法启动，`setup.sh` 会自动
改用系统 Python 3.10 运行随包源码，不需要 pip。

如果测试机是虚拟机（VMware/VirtualBox/KVM），必须把 PSU 的 USB 设备以
**USB 3.0/xHCI** 方式直通给虚拟机；只直通键盘鼠标不够。

## 2. 下载并制作安装 U 盘

在一台 Windows/Mac/Linux 上：

1. 从 <https://ubuntu.com/download/desktop> 下载 Ubuntu 24.04 LTS ISO；
2. 用 Rufus（Windows）、balenaEtcher 或 `dd` 写入 U 盘（U 盘会被清空）；
3. 测试机开机按 F2/F12/Del 进入 BIOS，选择 UEFI USB 启动。

Ubuntu Server 也可以：装完后执行 `sudo apt install -y ubuntu-desktop` 仅在你需要
浏览器看 Dashboard 时；验收脚本本身不需要桌面。

## 3. 安装 Ubuntu

- 选择“Erase disk and install Ubuntu”（测试机，不保留原系统）；
- 创建用户（例如 `psu`），记住密码；
- 不勾选额外第三方驱动也可以；
- 安装完成后重启，拔掉 U 盘。

首次进入系统后可选：

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y openssh-server   # 需要远程拷证据时
ip addr                              # 记下 IP
```

如果机器没有网络，跳过 apt；kit 的 `setup.sh --no-apt` 仍可安装。

## 4. 检查环境

```bash
uname -m                 # 应为 x86_64（或 aarch64）
ldd --version | head -1  # 22.04=2.35，24.04=2.39
lsusb | grep -i 0db0     # 插上 PSU 后应看到设备
ls -l /dev/hidraw*       # 应出现节点
```

## 5. 拷贝 kit 并安装

把 `msi-psu-monitor-hardware-kit-*.tar.gz` 和 `.sha256` 拷到测试机（U 盘/SCP）。
在测试机上：

```bash
sha256sum -c msi-psu-monitor-hardware-kit-*.tar.gz.sha256
tar xzf msi-psu-monitor-hardware-kit-*.tar.gz
cd msi-psu-monitor-hardware-kit-*
sudo ./setup.sh
```

然后按 `START-HERE.md` / [hardware-acceptance.md](hardware-acceptance.md) 继续。

## 6. 常见安装问题

| 现象 | 处理 |
|---|---|
| U 盘启动项看不到 | BIOS 关闭 Secure Boot 再试；确认 U 盘是 UEFI 写入 |
| 没有网络 | `setup.sh --no-apt`；验收只读项不需要网络 |
| 22.04 二进制报 GLIBC | `sudo ./setup.sh --source`；系统自带 Python 3.10 即可 |
| 虚拟机看不到 hidraw | 检查 USB 3.0 直通；不要用 WSL |

## 7. 需要下载的东西清单

- Ubuntu ISO（装系统）；
- Rufus/balenaEtcher（写 U 盘）；
- 本 kit tar.gz（随邮件/仓库提供）；
- 可选：`jq`、`curl`、`usbutils`（`setup.sh` 自动 apt 安装；离线可跳过）。

不需要：Python 安装包、pip、MSI Center、Windows 驱动、内核模块。
