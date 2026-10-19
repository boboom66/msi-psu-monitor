#!/bin/bash
set -euo pipefail

# Install the self-contained msi-psu-monitor release.
#
# No Python, pip or network access is needed on the target machine: the two
# executables in this directory already bundle CPython. Run as root:
#
#   sudo ./install.sh
#
# PREFIX=/usr/local by default; override to install elsewhere. The daemon is
# enabled and started as a systemd service when systemd is available.

PREFIX=${PREFIX:-/usr/local}
CONFIG=/etc/msi-psu-monitor.conf
UNIT=/etc/systemd/system/msi-psu-monitor.service
UDEV=/etc/udev/rules.d/99-msi-psu.rules
SRC=$(cd "$(dirname "$0")" && pwd)

info() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
die()  { echo "[ERROR] $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root: sudo ./install.sh"
for tool in msi-psu-monitor msi-psu-monitor-daemon; do
    [ -x "$SRC/$tool" ] || die "$tool is missing next to install.sh"
done

info "Installing the executables into $PREFIX/bin"
install -d "$PREFIX/bin"
install -m 755 "$SRC/msi-psu-monitor" "$SRC/msi-psu-monitor-daemon" "$PREFIX/bin/"

if command -v udevadm >/dev/null 2>&1; then
    info "Installing the udev rule"
    install -m 644 "$SRC/99-msi-psu.rules" "$UDEV"
    udevadm control --reload-rules || true
    udevadm trigger --subsystem-match=hidraw || true
else
    warn "udevadm not found; the hidraw node stays root-only"
fi

if [ -e "$CONFIG" ]; then
    info "Keeping the existing $CONFIG"
else
    info "Installing the example config (all values commented out)"
    install -m 644 "$SRC/msi-psu-monitor.conf.example" "$CONFIG"
fi

if [ -d /run/systemd/system ]; then
    info "Installing and starting the daemon unit"
    install -m 644 "$SRC/msi-psu-monitor.service" "$UNIT"
    mkdir -p /var/lib/node_exporter
    systemctl daemon-reload
    systemctl enable --now msi-psu-monitor.service
else
    warn "systemd is not running; install $SRC/msi-psu-monitor.service manually"
fi

info "Installed $("$PREFIX/bin/msi-psu-monitor" --version)"
echo ""
echo "  Read once:      msi-psu-monitor --once"
echo "  Watch mode:     msi-psu-monitor --watch 1"
echo "  No PSU at hand: MSI_PSU_DEMO=1 msi-psu-monitor --once"
echo "  Dashboard:      msi-psu-monitor --dashboard"
echo "  Alerts log:     journalctl -u msi-psu-monitor -f"
echo "  Configuration:  $CONFIG"
echo "  Remove:         sudo ./uninstall.sh [--purge]"
