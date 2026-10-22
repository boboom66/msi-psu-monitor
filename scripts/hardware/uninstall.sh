#!/bin/bash
# Remove the hardware-kit installation; keep config/state unless --purge.
set -euo pipefail
CONFIG=/etc/msi-psu-monitor.conf
UNIT=/etc/systemd/system/msi-psu-monitor.service
UDEV=/etc/udev/rules.d/99-msi-psu.rules
STATE=/var/lib/msi-psu-monitor
PURGE=${1:-}
info() { printf "[INFO] %s\n" "$*"; }
die() { printf "[ERROR] %s\n" "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "run as root: sudo ./uninstall.sh [--purge]"
if [ -d /run/systemd/system ]; then
    systemctl stop msi-psu-monitor.service 2>/dev/null || true
    systemctl disable msi-psu-monitor.service 2>/dev/null || true
fi
# Remove the unit even when systemd is not running: setup.sh installs it on
# non-systemd hosts too, and leaving it behind made uninstall incomplete.
rm -f "$UNIT"
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload 2>/dev/null || true
fi
rm -f "$UDEV"
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger --subsystem-match=hidraw 2>/dev/null || true
fi
rm -f /usr/local/bin/msi-psu-monitor /usr/local/bin/msi-psu-monitor-daemon
rm -rf /opt/msi-psu-monitor
if [ "$PURGE" = "--purge" ]; then
    info "Removing configuration and state"
    rm -f "$CONFIG"
    rm -rf "$STATE"
else
    info "Kept $CONFIG and $STATE (use --purge to remove)"
fi
info "Uninstalled msi-psu-monitor hardware kit."
