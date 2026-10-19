#!/bin/bash
# Build a self-contained hardware acceptance kit (binary + source fallback).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
ARCH=${1:-x86_64}
case "$ARCH" in x86_64|aarch64) ;; *) echo "unsupported arch: $ARCH" >&2; exit 1 ;; esac
VERSION=$(grep -m1 '^version = ' pyproject.toml | cut -d'"' -f2)
BIN_DIR=dist/bin/linux-$ARCH
[ -x "$BIN_DIR/msi-psu-monitor" ] || { echo "missing $BIN_DIR; run scripts/build_binary.sh first" >&2; exit 1; }
STAGE=dist/hardware-kit/msi-psu-monitor-hardware-kit-$VERSION-linux-$ARCH
rm -rf "$STAGE"
mkdir -p "$STAGE/bin" "$STAGE/source" "$STAGE/systemd" "$STAGE/docs"

cp "$BIN_DIR/msi-psu-monitor" "$BIN_DIR/msi-psu-monitor-daemon" "$STAGE/bin/"
chmod 755 "$STAGE/bin/"*
cp -a msi_psu_monitor "$STAGE/source/"
rm -rf "$STAGE/source/msi_psu_monitor/__pycache__"
cp scripts/hardware/setup.sh "$STAGE/setup.sh"
cp scripts/hardware/acceptance.sh "$STAGE/acceptance.sh"
cp scripts/hardware/uninstall.sh "$STAGE/uninstall.sh"
chmod 755 "$STAGE/setup.sh" "$STAGE/acceptance.sh" "$STAGE/uninstall.sh"
cp systemd/99-msi-psu.rules systemd/msi-psu-monitor.service "$STAGE/systemd/"
cp docs/msi-psu-monitor.conf.example "$STAGE/msi-psu-monitor.conf.example"
cp README.md LICENSE SECURITY.md "$STAGE/"
cp docs/verify.md docs/protocol.md docs/support.md docs/hardware-acceptance.md \
   docs/machine-setup.md "$STAGE/docs/"

{
    printf "version=%s\n" "$VERSION"
    printf "arch=%s\n" "$ARCH"
    printf "built=%s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf "commit=%s\n" "$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
    printf "build_glibc=%s\n" "$(ldd --version | head -1 | awk '{print $NF}')"
} > "$STAGE/BUILD-INFO"

cat > "$STAGE/START-HERE.md" <<'EOF'
# MSI PSU 硬件验收工具包

版本：__VERSION__ / 架构：__ARCH__

这个包包含：

- 自包含二进制 `bin/msi-psu-monitor`（目标机不需要 Python；本包二进制构建于 glibc 2.39，
  22.04 上若无法运行会自动回退到 `source/` 的 Python 3.10 标准库源码）；
- `setup.sh`：安装 udev 规则、systemd unit、配置、命令；
- `acceptance.sh`：一键硬件验收，默认只读；`--writes` 才做风扇写测试；
- `uninstall.sh`：卸载（默认保留配置和状态）；
- `docs/`：协议、验收清单、支持文档。

## 最短路径

```bash
# 1. 解压到任意目录（可放 U 盘）
tar xzf msi-psu-monitor-hardware-kit-__VERSION__-linux-__ARCH__.tar.gz
cd msi-psu-monitor-hardware-kit-__VERSION__-linux-__ARCH__

# 2. 安装（需要 sudo；会安装 udev/systemd/配置）
sudo ./setup.sh

# 3. 把 PSU 的 USB 数据线接到这台机器，确认 lsusb 能看到 0db0:xxxx
lsusb | grep -i 0db0
ls -l /dev/hidraw*

# 4. 只读验收（不会写电源）
sudo ./acceptance.sh

# 5. 需要验证风扇写入时（会询问确认）
sudo ./acceptance.sh --writes
```

报告与证据在 `/var/log/msi-psu-acceptance/<时间>/`，同目录会生成 `.tar.gz`，
把该 tar.gz 发回即可。

没有硬件时先自测工具链：`./acceptance.sh --demo`（demo 结果不能证明真机）。

系统安装步骤见 `docs/machine-setup.md`；详细验收与排错见 `docs/hardware-acceptance.md`。
EOF
sed -i "s/__VERSION__/$VERSION/g; s/__ARCH__/$ARCH/g" "$STAGE/START-HERE.md"

# SHA256SUMS must not include itself.
( cd "$STAGE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )

OUT="$ROOT/dist/msi-psu-monitor-hardware-kit-$VERSION-linux-$ARCH.tar.gz"
tar --sort=name --mtime="UTC 2020-01-01" --owner=0 --group=0 --numeric-owner \
    -C "$ROOT/dist/hardware-kit" -cf - "msi-psu-monitor-hardware-kit-$VERSION-linux-$ARCH" | gzip -9n > "$OUT"
( cd "$ROOT/dist" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
printf "[OK] %s\n" "$OUT"
printf "[OK] %s\n" "$OUT.sha256"
printf "[OK] stage: %s\n" "$STAGE"
