# Ubuntu 22.04 chroot 构建（本地复现）

> **历史构建证据（2026-10-19，v1.0.0）**。当前源码版本为 1.0.1，测试基线为 803/94%；发布产物仍需按当前 tag 重新构建，本文步骤可复用。

目的：在本机 24.04/glibc 2.39 上生成并验证 **22.04/glibc 2.35** 的 PyInstaller 产物。
不修改宿主 `/etc`，只在用户命名空间 chroot 内操作。

## 1. 准备 rootfs

```bash
curl -fsSL https://cdimage.ubuntu.com/ubuntu-base/releases/22.04/release/ubuntu-base-22.04.5-base-amd64.tar.gz -o /tmp/u2204.tar.gz
mkdir /tmp/u2204
tar xzf /tmp/u2204.tar.gz -C /tmp/u2204
cp /etc/resolv.conf /tmp/u2204/etc/resolv.conf
```

## 2. 安装 Python（userns chroot）

```bash
unshare -r chroot /tmp/u2204 /bin/sh -c 'apt-get -o APT::Sandbox::User=root update -qq'
unshare -r chroot /tmp/u2204 /bin/sh -c 'DEBIAN_FRONTEND=noninteractive apt-get -o APT::Sandbox::User=root install -y -qq python3 python3-venv python3-pip binutils'
```

注：无 systemd/udev 的 rootfs 中 fontconfig 等 trigger 可能报 chown 警告；Python 仍会安装成功。

## 3. 构建

```bash
# 拷入源码（不含 .git/.venv/dist/build）
tar ... | tar xf - -C /tmp/u2204/src
unshare -r chroot /tmp/u2204 /bin/sh -c '/usr/bin/python3 -m venv /opt/venv && /opt/venv/bin/pip install pyinstaller==6.16.0'
```

在 chroot 内用 `/opt/venv/bin/pyinstaller --onefile --clean --noconfirm --strip --paths /src ...`
分别以 `monitor_entry.py`/`daemon_entry.py` 为入口构建，输出到 `/out`。

## 4. 验证

```bash
unshare -r chroot /tmp/u2204 /bin/sh -c 'cd /out && MSI_PSU_DEMO=1 ./msi-psu-monitor --version && MSI_PSU_DEMO=1 ./msi-psu-monitor --once'
```

再将本地 `dist/...tar.gz` 和 `.deb` 解包到 chroot 内运行一次；本次结果为 PASS。

## 5. 限制

- 这是**本地 chroot**，不是 GitHub Actions `ubuntu-22.04`；发布 provenance 仍须 CI。
- arm64 未构建；真实硬件/真实 systemd 未验证。
