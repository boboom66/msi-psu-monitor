#!/bin/bash
# One-shot setup for a fresh Ubuntu test machine (root required).
#
# It installs either the self-contained binaries shipped in this kit, or
# (for a glibc/arch mismatch) a no-install source fallback that runs with the
# system Python 3.10+. It also installs the udev rule, systemd unit and config.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
if [ -x "$HERE/bin/msi-psu-monitor" ] || [ -d "$HERE/source" ]; then
    KIT_DIR=$HERE
elif [ -x "$HERE/../bin/msi-psu-monitor" ] || [ -d "$HERE/../source" ]; then
    KIT_DIR=$(cd "$HERE/.." && pwd)
else
    KIT_DIR=$(cd "$HERE/../.." && pwd)
fi
OPT=/opt/msi-psu-monitor
CONFIG=/etc/msi-psu-monitor.conf
UNIT=/etc/systemd/system/msi-psu-monitor.service
UDEV=/etc/udev/rules.d/99-msi-psu.rules
PREFIX=/usr/local
START=0
FORCE_SOURCE=0
NO_APT=0

info() { printf "[INFO] %s\n" "$*"; }
warn() { printf "[WARN] %s\n" "$*" >&2; }
die()  { printf "[ERROR] %s\n" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: sudo ./setup.sh [--start] [--source] [--no-apt]
  --start    enable and start the daemon now (default: enable only)
  --source   force the system-Python fallback even if the binary works
  --no-apt   do not try to install jq/curl/usbutils
EOF
}
while [ $# -gt 0 ]; do
    case "$1" in
        --start) START=1 ;;
        --source) FORCE_SOURCE=1 ;;
        --no-apt) NO_APT=1 ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
    shift
done

[ "$(id -u)" -eq 0 ] || die "run as root: sudo ./setup.sh"
[ -r /etc/os-release ] || die "cannot read /etc/os-release"
. /etc/os-release
ARCH=$(uname -m)
info "OS: ${PRETTY_NAME:-unknown} / arch: $ARCH / kernel: $(uname -r)"

if [ "$NO_APT" -eq 0 ] && command -v apt-get >/dev/null 2>&1; then
    info "Installing optional evidence tools (jq curl usbutils); failure is non-fatal"
    apt-get update -qq >/dev/null 2>&1 || warn "apt-get update failed; continuing offline"
    apt-get install -y -qq jq curl usbutils >/dev/null 2>&1 || warn "optional tools unavailable; continuing"
fi

MODE=binary
if [ "$FORCE_SOURCE" -eq 1 ]; then
    MODE=source
elif [ ! -x "$KIT_DIR/bin/msi-psu-monitor" ]; then
    MODE=source
elif ! "$KIT_DIR/bin/msi-psu-monitor" --version >/dev/null 2>&1; then
    warn "the shipped binary cannot run on this glibc/arch; using the Python source fallback"
    MODE=source
fi

install -d "$OPT" "$PREFIX/bin"
if [ "$MODE" = binary ]; then
    info "Installing the self-contained binaries into $OPT/bin"
    install -d "$OPT/bin"
    install -m 755 "$KIT_DIR/bin/msi-psu-monitor" "$KIT_DIR/bin/msi-psu-monitor-daemon" "$OPT/bin/"
    ln -sf "$OPT/bin/msi-psu-monitor" "$PREFIX/bin/msi-psu-monitor"
    ln -sf "$OPT/bin/msi-psu-monitor-daemon" "$PREFIX/bin/msi-psu-monitor-daemon"
else
    command -v python3 >/dev/null 2>&1 || die "source fallback needs python3 >= 3.10"
    python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
        || die "source fallback needs python3 >= 3.10"
    info "Installing the Python source fallback (no pip, stdlib only)"
    rm -rf "$OPT/source"
    install -d "$OPT/source"
    cp -a "$KIT_DIR/source/msi_psu_monitor" "$OPT/source/"
    cat > "$PREFIX/bin/msi-psu-monitor" <<'WRAP'
#!/bin/sh
exec env PYTHONPATH="__OPT__/source" python3 -m msi_psu_monitor "$@"
WRAP
    cat > "$PREFIX/bin/msi-psu-monitor-daemon" <<'WRAP'
#!/bin/sh
exec env PYTHONPATH="__OPT__/source" python3 -m msi_psu_monitor.daemon "$@"
WRAP
    sed -i "s|__OPT__|$OPT|g" "$PREFIX/bin/msi-psu-monitor" "$PREFIX/bin/msi-psu-monitor-daemon"
    chmod 755 "$PREFIX/bin/msi-psu-monitor" "$PREFIX/bin/msi-psu-monitor-daemon"
fi

info "Installing udev rule and systemd unit"
install -D -m 644 "$KIT_DIR/systemd/99-msi-psu.rules" "$UDEV"
install -D -m 644 "$KIT_DIR/systemd/msi-psu-monitor.service" "$UNIT"
if [ ! -e "$CONFIG" ]; then
    install -D -m 644 "$KIT_DIR/msi-psu-monitor.conf.example" "$CONFIG"
    info "Installed the example config at $CONFIG (all values commented out)"
else
    info "Keeping the existing $CONFIG"
fi
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger --subsystem-match=hidraw || true
fi
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload
    systemctl enable msi-psu-monitor.service >/dev/null 2>&1 || warn "could not enable the unit"
    if [ "$START" -eq 1 ]; then
        systemctl restart msi-psu-monitor.service || warn "unit did not start (is a PSU attached?)"
    fi
else
    warn "systemd is not running; install the unit manually when it is"
fi

install -d /var/log/msi-psu-acceptance
info "Verifying the installed command: $(msi-psu-monitor --version)"
MSI_PSU_DEMO=1 msi-psu-monitor --once >/dev/null || die "installed command cannot read the demo PSU"

cat <<EOF

[OK] msi-psu-monitor is installed ($MODE mode).

Next: plug in the PSU (USB data cable), then run:
    sudo "$KIT_DIR/acceptance.sh"

Read-only tests are the default. To include writes (fan/Zero Fan/buzzer/rail):
    sudo "$KIT_DIR/acceptance.sh" --writes

Dashboard:
    msi-psu-monitor --dashboard --port 8899
    (on a headless machine use: ssh -L 8899:127.0.0.1:8899 user@host)

Daemon:
    sudo systemctl start msi-psu-monitor
    journalctl -u msi-psu-monitor -f
EOF
