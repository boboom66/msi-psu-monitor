#!/bin/bash
set -euo pipefail

# msi-psu-monitor install script (source checkout).
#
# Installs the Python package, the udev rule and the systemd daemon unit.
# Prefer `scripts/build_deb.sh` + `apt install ./dist/*.deb` on Debian/Ubuntu:
# this script is the fallback for running straight from a checkout.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Check root
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (sudo)."
    exit 1
fi

ROOT=$(cd "$(dirname "$0")/.." && pwd)

# Detect PSU (all supported USB IDs, not just the Ai1600TS)
if command -v udevadm >/dev/null; then
    for dev in /dev/hidraw*; do
        [[ -e "$dev" ]] || continue
        props=$(udevadm info --query=all --name="$dev" 2>/dev/null || true)
        for pid in 808c aa6f 56d4 e749 c9eb; do
            if grep -qi "ID_MODEL_ID=$pid" <<<"$props"; then
                info "Detected PSU at $dev (USB ID 0db0:$pid)"
                detected=1
            fi
        done
    done
fi

if [[ -z "${detected:-}" ]]; then
    warn "No supported MSI PSU detected. Install will proceed, but the tool"
    warn "cannot read anything until the PSU is connected."
    warn "Expected USB IDs: 0db0:{808c, aa6f, 56d4, e749, c9eb}"
fi

# Install the Python package (stdlib-only runtime, no dependencies to resolve)
info "Installing the Python package..."
python3 -m pip install --break-system-packages "$ROOT" 2>/dev/null \
    || python3 -m pip install "$ROOT"

for tool in msi-psu-monitor msi-psu-monitor-daemon; do
    if command -v "$tool" >/dev/null; then
        info "Installed CLI tool: $(command -v "$tool")"
    else
        warn "$tool not found in PATH after install"
    fi
done

# udev: let a logged-in session use the PSU without root (uaccess)
info "Installing the udev rule..."
install -m 644 "$ROOT/systemd/99-msi-psu.rules" /etc/udev/rules.d/
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw

# systemd: one resident daemon (there is no timer any more)
info "Installing the systemd unit..."
install -m 644 "$ROOT/systemd/msi-psu-monitor.service" /etc/systemd/system/
rm -f /etc/systemd/system/msi-psu-monitor.timer   # legacy timer installs
mkdir -p /var/lib/node_exporter
systemctl daemon-reload
systemctl enable --now msi-psu-monitor.service

info "Installation complete!"
echo ""
echo "  Read once:      sudo msi-psu-monitor --once"
echo "  Watch mode:     sudo msi-psu-monitor --watch 1"
echo "  No PSU at hand: MSI_PSU_DEMO=1 msi-psu-monitor --once"
echo "  Dashboard:      msi-psu-monitor --dashboard"
echo "  Alerts log:     journalctl -u msi-psu-monitor -f"
echo "  Service state:  systemctl status msi-psu-monitor"
echo "  Configuration:  install -m 644 $ROOT/docs/msi-psu-monitor.conf.example /etc/msi-psu-monitor.conf"
echo ""
echo "  No-hardware verification checklist: $ROOT/docs/verify.md"
echo "  Preferred install on Debian/Ubuntu:  bash $ROOT/scripts/build_deb.sh"
echo ""
echo "  Kernel module (optional, out-of-tree):"
echo "    Jack Doan's msi-psu driver covers the MEG models; kernel/ carries the"
echo "    MPG Ai1600TS patch. Build once Proxmox 7.0 kernel headers exist:"
echo "      cd kernel && patch -p1 < msi-psu-ai1600ts.patch"
echo "      make -C /lib/modules/\$(uname -r)/build M=\$(pwd) modules"
