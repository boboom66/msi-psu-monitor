#!/bin/bash
set -euo pipefail

# Build the self-contained release binaries for the official download.
#
# The target machine needs no Python: PyInstaller bundles CPython and this
# stdlib-only package into two executable files. Build on Ubuntu 22.04
# (glibc 2.35) so the result runs on Ubuntu 22.04+ / Debian 12+; a newer build
# host is refused unless ALLOW_NEWER_GLIBC=1 (local smoke builds only).
#
# Output:
#   dist/bin/linux-<arch>/msi-psu-monitor{,-daemon}
#   dist/msi-psu-monitor_<version>_linux_<arch>.tar.gz
#   dist/msi-psu-monitor_<version>_linux_<arch>.tar.gz.sha256

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

ALLOW_NEWER_GLIBC=${ALLOW_NEWER_GLIBC:-0}
GLIBC_FLOOR=2.35

info() { echo "[INFO] $*"; }
die()  { echo "[ERROR] $*" >&2; exit 1; }

PY=${PYTHON:-python3}
[ -x .venv/bin/python ] && PY=.venv/bin/python

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
    x86_64) DEB_ARCH=amd64 ;;
    aarch64|arm64) ARCH=aarch64; DEB_ARCH=arm64 ;;
    *) die "unsupported architecture: $ARCH" ;;
esac

GLIBC=$(ldd --version | head -1 | awk '{print $NF}')
if "$PY" - "$GLIBC" "$GLIBC_FLOOR" <<'PY'
import sys

current = tuple(int(part) for part in sys.argv[1].split('.'))
floor = tuple(int(part) for part in sys.argv[2].split('.'))
sys.exit(0 if current > floor else 1)
PY
then
    if [ "$ALLOW_NEWER_GLIBC" != 1 ]; then
        die "build host glibc $GLIBC > $GLIBC_FLOOR: the binary will not start on Ubuntu 22.04 / Debian 12. Build on ubuntu-22.04, or set ALLOW_NEWER_GLIBC=1 for a local smoke build."
    fi
    info "WARNING: glibc $GLIBC > $GLIBC_FLOOR; this build is for local testing only."
fi

BUILD="$ROOT/build/binary"
DIST="$BUILD/dist"
WORK="$BUILD/work"
ENTRY="$WORK/entry"
rm -rf "$BUILD"
mkdir -p "$DIST" "$ENTRY" "$ROOT/dist/bin/linux-$ARCH"

cat > "$ENTRY/monitor_entry.py" <<'PY'
import sys

from msi_psu_monitor.monitor import main

if __name__ == '__main__':
    sys.exit(main())
PY
cat > "$ENTRY/daemon_entry.py" <<'PY'
import sys

from msi_psu_monitor.daemon import main

if __name__ == '__main__':
    sys.exit(main())
PY

build_one() {
    local name=$1
    local entry=$2
    info "Freezing $name"
    uv run --frozen --group build pyinstaller --onefile --clean --noconfirm --strip --paths "$ROOT" --name "$name" --distpath "$DIST" --workpath "$WORK/$name" --specpath "$WORK" "$entry" >/dev/null
    [ -x "$DIST/$name" ] || die "PyInstaller did not produce $name"
}

build_one msi-psu-monitor "$ENTRY/monitor_entry.py"
build_one msi-psu-monitor-daemon "$ENTRY/daemon_entry.py"

# The release must be self-contained AND functional before it is packaged.
info "Smoke-testing the frozen binaries"
"$DIST/msi-psu-monitor" --version | grep -q "$VERSION" || die "binary --version does not report $VERSION"
STATE=$(mktemp -d)
trap 'rm -rf "$STATE"' EXIT
MSI_PSU_DEMO=1 MSI_PSU_STATE_DIR="$STATE" "$DIST/msi-psu-monitor" --once >/dev/null || die "frozen monitor cannot read the demo PSU"
MSI_PSU_DEMO=1 MSI_PSU_STATE_DIR="$STATE" "$DIST/msi-psu-monitor-daemon" --iterations 1 >/dev/null 2>&1 || die "frozen daemon cannot run one iteration"
MSI_PSU_DEMO=1 MSI_PSU_STATE_DIR="$STATE" "$DIST/msi-psu-monitor" --zero-fan off >/dev/null || die "frozen Zero Fan write failed"
MSI_PSU_DEMO=1 MSI_PSU_STATE_DIR="$STATE" "$DIST/msi-psu-monitor" --buzzer-off >/dev/null || die "frozen buzzer command failed"
MSI_PSU_DEMO=1 MSI_PSU_STATE_DIR="$STATE" "$DIST/msi-psu-monitor" --fan-mode performance >/dev/null 2>&1 || die "frozen performance alias failed"
MSI_PSU_DEMO=1 MSI_PSU_DEMO_MODEL=ai1300p MSI_PSU_STATE_DIR="$STATE" "$DIST/msi-psu-monitor" --set-rail multi >/dev/null 2>&1 || die "frozen multirail write failed"
MSI_PSU_DEMO=1 MSI_PSU_STATE_DIR="$STATE" "$DIST/msi-psu-monitor" --show-alert-log >/dev/null || die "frozen alert-log viewer failed"
MSI_PSU_DEMO=1 MSI_PSU_DEMO_MODEL=ai1300p MSI_PSU_STATE_DIR="$STATE" "$DIST/msi-psu-monitor" --once | grep -q 'AC Input' || die "frozen VIN/AC Input missing"

install -m 755 "$DIST/msi-psu-monitor" "$DIST/msi-psu-monitor-daemon" "$ROOT/dist/bin/linux-$ARCH/"

STAGE="$BUILD/release/msi-psu-monitor_${VERSION}_linux_${ARCH}"
mkdir -p "$STAGE/docs"
install -m 755 "$DIST/msi-psu-monitor" "$DIST/msi-psu-monitor-daemon" "$STAGE/"
install -m 755 "$ROOT/scripts/install_binary.sh" "$STAGE/install.sh"
install -m 755 "$ROOT/scripts/uninstall_binary.sh" "$STAGE/uninstall.sh"
install -m 644 "$ROOT/systemd/99-msi-psu.rules" "$ROOT/systemd/msi-psu-monitor.service" "$STAGE/"
install -m 644 "$ROOT/docs/msi-psu-monitor.conf.example" "$STAGE/msi-psu-monitor.conf.example"
install -m 644 "$ROOT/README.md" "$ROOT/LICENSE" "$ROOT/SECURITY.md" "$ROOT/CHANGELOG.md" "$STAGE/"
install -m 644 "$ROOT/docs/protocol.md" "$ROOT/docs/verify.md" "$ROOT/docs/release.md" \
  "$ROOT/docs/support.md" "$ROOT/docs/incident-response.md" \
  "$ROOT/docs/prometheus-rules.yml" "$STAGE/docs/"
printf 'version=%s\narch=%s\ndeb_arch=%s\nbuild_glibc=%s\n' "$VERSION" "$ARCH" "$DEB_ARCH" "$GLIBC" > "$STAGE/BUILD-INFO"
(
    cd "$STAGE"
    sha256sum msi-psu-monitor msi-psu-monitor-daemon install.sh uninstall.sh > SHA256SUMS
)

OUT="$ROOT/dist/msi-psu-monitor_${VERSION}_linux_${ARCH}.tar.gz"
tar --sort=name --mtime='UTC 2020-01-01' --owner=0 --group=0 --numeric-owner -C "$BUILD/release" -cf - "msi-psu-monitor_${VERSION}_linux_${ARCH}" | gzip -9n > "$OUT"
(
    cd "$ROOT/dist"
    sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256"
)

info "Release: $OUT"
info "Binaries: $ROOT/dist/bin/linux-$ARCH/"
ls -lh "$OUT" "$ROOT/dist/bin/linux-$ARCH/"*
cat "$OUT.sha256"
