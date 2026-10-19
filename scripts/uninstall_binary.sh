#!/bin/bash
set -euo pipefail

# Remove the executables, unit and udev rule installed by install.sh.
# User data is kept unless --purge is given:
#   /etc/msi-psu-monitor.conf
#   /var/lib/msi-psu-monitor (state.json + daily logs)

PREFIX=${PREFIX:-/usr/local}
PURGE=${1:-}
CONFIG=/etc/msi-psu-monitor.conf
UNIT=/etc/systemd/system/msi-psu-monitor.service
UDEV=/etc/udev/rules.d/99-msi-psu.rules
STATE=/var/lib/msi-psu-monitor

info() { echo "[INFO] $*"; }
die()  { echo "[ERROR] $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root: sudo ./uninstall.sh [--purge]"

if [ -d /run/systemd/system ] && [ -e "$UNIT" ]; then
    info "Stopping and disabling the daemon"
    systemctl stop msi-psu-monitor.service || true
    systemctl disable msi-psu-monitor.service || true
fi

info "Removing the executables"
rm -f "$PREFIX/bin/msi-psu-monitor" "$PREFIX/bin/msi-psu-monitor-daemon"

if [ -e "$UNIT" ]; then
    rm -f "$UNIT"
    [ -d /run/systemd/system ] && systemctl daemon-reload || true
fi

if [ -e "$UDEV" ]; then
    info "Removing the udev rule"
    rm -f "$UDEV"
    if command -v udevadm >/dev/null 2>&1; then
        udevadm control --reload-rules || true
        udevadm trigger --subsystem-match=hidraw || true
    fi
fi

if [ "$PURGE" = "--purge" ]; then
    info "Purging configuration and state"
    rm -f "$CONFIG"
    rm -rf "$STATE"
fi

info "Uninstalled."
[ "$PURGE" = "--purge" ] || echo "Kept $CONFIG and $STATE (use --purge to remove them)."
