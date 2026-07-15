#!/bin/bash
set -euo pipefail

# msi-psu-monitor Install Script
# Installs the Python package, systemd service, and optional kernel module

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

# Detect PSU
HIDRAW_DEV=$(ls /dev/hidraw* 2>/dev/null | while read dev; do
    udevadm info --query=all --name="$dev" 2>/dev/null | grep -q 'ID_MODEL_ID=808c' && echo "$dev" && break
done || true)

if [[ -z "$HIDRAW_DEV" ]]; then
    warn "No MPG Ai1600TS PSU detected. Install will proceed but the tool won't work until the PSU is connected."
    warn "Expected USB ID: 0db0:808c"
else
    info "Detected PSU at $HIDRAW_DEV"
fi

# Install Python package
info "Installing Python package..."
cd "$(dirname "$0")/.."
pip install -e . 2>&1 | sed 's/^/  /'

# Verify CLI works
if command -v msi-psu-monitor &>/dev/null; then
    info "CLI tool installed: $(which msi-psu-monitor)"
else
    warn "CLI tool not found in PATH after install"
fi

# Install systemd service and timer
info "Installing systemd service and timer..."
cp systemd/msi-psu-monitor.service /etc/systemd/system/
cp systemd/msi-psu-monitor.timer /etc/systemd/system/
systemctl daemon-reload

# Create node_exporter directory if it doesn't exist
mkdir -p /var/lib/node_exporter

# Enable and start timer
systemctl enable --now msi-psu-monitor.timer 2>&1 | sed 's/^/  /'

info "Installation complete!"
echo ""
echo "  Test the tool:  sudo msi-psu-monitor --once"
echo "  Watch mode:     sudo msi-psu-monitor --watch"
echo "  Prometheus:     sudo msi-psu-monitor --format prometheus --output /var/lib/node_exporter/msi-psu.prom"
echo "  Timer status:   systemctl status msi-psu-monitor.timer"
echo ""
echo "  Kernel module (optional):"
echo "    See kernel/ directory for the MPG Ai1600TS patch."
echo "    Build when Proxmox 7.0 kernel headers become available:"
echo "      cd kernel && patch -p1 < msi-psu-ai1600ts.patch"
echo "      make -C /lib/modules/\$(uname -r)/build M=\$(pwd) modules"
