#!/bin/bash
set -euo pipefail

# Build the zero-Python-dependency .deb from the frozen release binaries.
#
# Run scripts/build_binary.sh first: this packages dist/bin/linux-<arch>/.
# Ubuntu 22.04 is the reference build host (glibc 2.35); the control file
# records the matching libc6 floor and no python3 dependency.
#
# Output: dist/msi-psu-monitor_<version>_<arch>.deb (+ .sha256)

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

PKG=msi-psu-monitor
PY=${PYTHON:-python3}
[ -x .venv/bin/python ] && PY=.venv/bin/python

info() { echo "[INFO] $*"; }
die()  { echo "[ERROR] $*" >&2; exit 1; }

command -v dpkg-deb >/dev/null || die "dpkg-deb not found; install dpkg-dev first."

VERSION=$("$PY" - "$ROOT/pyproject.toml" <<'PY'
import pathlib
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
for line in text.splitlines():
    stripped = line.strip()
    if stripped.startswith('version ='):
        print(stripped.split('=', 1)[1].strip().strip('"'))
        break
else:
    sys.exit('no version found in pyproject.toml')
PY
)

ARCH=$(uname -m)
case "$ARCH" in
    x86_64) ARCH=x86_64; DEB_ARCH=amd64 ;;
    aarch64|arm64) ARCH=aarch64; DEB_ARCH=arm64 ;;
    *) die "unsupported architecture: $ARCH" ;;
esac

BIN_DIR="$ROOT/dist/bin/linux-$ARCH"
for tool in msi-psu-monitor msi-psu-monitor-daemon; do
    [ -x "$BIN_DIR/$tool" ] || die "$BIN_DIR/$tool is missing; run scripts/build_binary.sh first"
done

DEB="$ROOT/dist/${PKG}_${VERSION}_${DEB_ARCH}.deb"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
chmod 755 "$STAGE"

install -d "$STAGE/DEBIAN" "$STAGE/usr/bin" "$STAGE/lib/systemd/system" "$STAGE/lib/udev/rules.d" "$STAGE/etc" "$STAGE/usr/share/doc/$PKG"
install -m 755 "$BIN_DIR/msi-psu-monitor" "$BIN_DIR/msi-psu-monitor-daemon" "$STAGE/usr/bin/"
install -m 644 "$ROOT/systemd/msi-psu-monitor.service" "$STAGE/lib/systemd/system/"
install -m 644 "$ROOT/systemd/99-msi-psu.rules" "$STAGE/lib/udev/rules.d/"
install -m 644 "$ROOT/docs/msi-psu-monitor.conf.example" "$STAGE/etc/msi-psu-monitor.conf"
install -m 644 "$ROOT/README.md" "$ROOT/LICENSE" "$ROOT/SECURITY.md" \
  "$ROOT/docs/protocol.md" "$ROOT/docs/verify.md" "$ROOT/docs/release.md" \
  "$ROOT/docs/support.md" "$ROOT/docs/incident-response.md" "$STAGE/usr/share/doc/$PKG/"
install -m 644 "$ROOT/docs/copyright" "$STAGE/usr/share/doc/$PKG/copyright"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: $DEB_ARCH
Depends: libc6 (>= 2.35), zlib1g
Recommends: prometheus-node-exporter
Maintainer: MSI PSU Monitor Contributors <contributors@example.com>
Homepage: https://github.com/HesiPullupTimbo/msi-psu-monitor
Description: Userspace monitor for MSI MPG PSUs over USB HID
 Reads voltages, currents, power, efficiency, temperature, fan and
 12V-2x6 per-pin telemetry from MSI MPG Ai1600TS/Ai1300TS and the
 supported MEG models, exposes Prometheus metrics and raises
 over-current alerts.
 .
 This package ships self-contained executables: no Python or pip is
 required on the target machine.
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

if [ -x /usr/bin/udevadm ]; then
    udevadm control --reload-rules || true
    udevadm trigger --subsystem-match=hidraw || true
fi

if [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
    systemctl enable msi-psu-monitor.service >/dev/null 2>&1 || true
    systemctl restart msi-psu-monitor.service >/dev/null 2>&1 || true
fi
EOF

cat > "$STAGE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e

if [ "$1" = remove ] && [ -d /run/systemd/system ]; then
    systemctl stop msi-psu-monitor.service >/dev/null 2>&1 || true
    systemctl disable msi-psu-monitor.service >/dev/null 2>&1 || true
fi
EOF

chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm"

mkdir -p "$ROOT/dist"
info "Building $DEB"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB" >/dev/null
(
    cd "$ROOT/dist"
    sha256sum "$(basename "$DEB")" > "$(basename "$DEB").sha256"
)

info "Package: $DEB"
dpkg-deb --info "$DEB" | sed 's/^/  /'
ls -lh "$DEB"
cat "$DEB.sha256"
