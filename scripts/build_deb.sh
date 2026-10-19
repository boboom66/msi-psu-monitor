#!/bin/bash
set -euo pipefail

# Build a Debian package for msi-psu-monitor.
#
# The runtime is stdlib-only, so the package is just the Python modules, two
# console scripts, the systemd unit, the udev rule and the docs -- no build
# backend, no vendored wheels, no dependency resolution at install time.
# Requires dpkg-deb (present whenever you can install a .deb).

PKG=msi-psu-monitor
ARCH=${ARCH:-all}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${OUT:-$ROOT/dist}
PYTHON=${PYTHON:-python3}

info() { printf '\033[0;32m[INFO]\033[0m %s\n' "$*"; }
die()  { printf '\033[0;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

command -v dpkg-deb >/dev/null || die "dpkg-deb not found; install dpkg-dev first."

VERSION=$("$PYTHON" - "$ROOT/pyproject.toml" <<'EOF'
import re, sys, pathlib
text = pathlib.Path(sys.argv[1]).read_text()
match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
if not match:
    sys.exit('no version found in pyproject.toml')
print(match.group(1))
EOF
)
DEB="$OUT/${PKG}_${VERSION}_${ARCH}.deb"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
# mktemp hands out 0700, and dpkg-deb records the staging root as the package's
# "./" entry -- upload that verbatim and the archive ships with a 0700 root.
chmod 755 "$STAGE"

LIBDIR="$STAGE/usr/lib/python3/dist-packages/msi_psu_monitor"
install -d "$STAGE/DEBIAN" "$LIBDIR" "$STAGE/usr/bin" \
    "$STAGE/lib/systemd/system" "$STAGE/lib/udev/rules.d" "$STAGE/etc" \
    "$STAGE/usr/share/doc/$PKG"

info "Staging $PKG $VERSION ($ARCH)"
# install(1) rather than cp(1): a hardened umask (077) otherwise ships
# root-only modules, and the udev rule's uaccess promise is for non-root users.
install -m 644 "$ROOT"/msi_psu_monitor/*.py "$LIBDIR/"
install -m 644 "$ROOT/systemd/msi-psu-monitor.service" "$STAGE/lib/systemd/system/"
install -m 644 "$ROOT/systemd/99-msi-psu.rules" "$STAGE/lib/udev/rules.d/"
install -m 644 "$ROOT/README.md" "$ROOT/LICENSE" "$ROOT/SECURITY.md" \
   "$ROOT/docs/protocol.md" "$ROOT/docs/verify.md" "$ROOT/docs/requirements-traceability.md" \
   "$ROOT/docs/support.md" "$ROOT/docs/incident-response.md" \
   "$ROOT/docs/msi-psu-monitor.conf.example" \
   "$STAGE/usr/share/doc/$PKG/"
# Debian policy 12.5: the machine-readable copyright goes next to LICENSE.
install -m 644 "$ROOT/docs/copyright" "$STAGE/usr/share/doc/$PKG/copyright"
# Anything under /etc is a conffile: dpkg keeps a user's edits and asks on change.
# The example is all comments, so installing it enables nothing by itself.
install -m 644 "$ROOT/docs/msi-psu-monitor.conf.example" \
    "$STAGE/etc/msi-psu-monitor.conf"

for entry in monitor daemon; do
    name="msi-psu-monitor"
    [ "$entry" = daemon ] && name="msi-psu-monitor-daemon"
    cat > "$STAGE/usr/bin/$name" <<EOF
#!/usr/bin/python3
# Generated console script for $PKG.
import re
import sys
from msi_psu_monitor.$entry import main
if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?\$', '', sys.argv[0])
    sys.exit(main())
EOF
    chmod 755 "$STAGE/usr/bin/$name"
done

cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.10)
Recommends: prometheus-node-exporter
Maintainer: MSI PSU Monitor Contributors <contributors@example.com>
Homepage: https://github.com/HesiPullupTimbo/msi-psu-monitor
Description: Userspace monitor for MSI MPG PSUs over USB HID
 Reads voltages, currents, power, efficiency, temperature and fan telemetry
 from MSI MPG Ai1600TS / Ai1300TS (GPU Safeguard+ per-pin current monitoring)
 and MEG PSUs, exposes Prometheus metrics and raises over-current alerts.
 The runtime is Python standard library only; no third-party packages.
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

mkdir -p "$OUT"
info "Building $DEB"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB" >/dev/null

info "Done: $DEB"
dpkg-deb --info "$DEB" | sed 's/^/  /'
