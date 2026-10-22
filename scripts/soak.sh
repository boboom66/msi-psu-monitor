#!/bin/bash
# Accelerated no-hardware soak: run the resident daemon against the demo PSU.
#
# Usage: scripts/soak.sh [SAMPLES]     (default 5000, minimum 100)
#
# It proves the daemon completes a long sample loop, keeps writing its state
# files, and does not leak file descriptors or unbounded memory. This is a
# synthetic-PSU reliability gate, not a hardware test.
set -u

SAMPLES=${1:-5000}
ROOT=$(cd "$(dirname "$0")/.." && pwd)

case "$SAMPLES" in
    ''|*[!0-9]*)
        echo "usage: $0 [SAMPLES]  (SAMPLES must be a positive integer)" >&2
        exit 2
        ;;
esac
if [ "$SAMPLES" -lt 100 ]; then
    echo "SAMPLES must be at least 100 (got $SAMPLES)" >&2
    exit 2
fi

if [ -n "${MSI_PSU_DAEMON:-}" ]; then
    DAEMON=$MSI_PSU_DAEMON
elif [ -x "$ROOT/.venv/bin/msi-psu-monitor-daemon" ]; then
    DAEMON=$ROOT/.venv/bin/msi-psu-monitor-daemon
elif command -v msi-psu-monitor-daemon >/dev/null 2>&1; then
    DAEMON=$(command -v msi-psu-monitor-daemon)
else
    echo "soak: no msi-psu-monitor-daemon found (run uv sync --group dev)" >&2
    exit 2
fi

TMP=$(mktemp -d) || exit 1
PID=""
cleanup() {
    if [ -n "$PID" ]; then
        kill "$PID" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
    fi
    rm -rf "$TMP"
}
trap cleanup EXIT INT TERM

CONF=$TMP/soak.conf
cat > "$CONF" <<'CONF_EOF'
[daemon]
sample_interval = 0.002
history_interval = 3600
prom_interval = 3600
CONF_EOF

export MSI_PSU_DEMO=1
"$DAEMON" --config "$CONF" --state-dir "$TMP" --prom-path "$TMP/psu.prom" \
    --iterations "$SAMPLES" >"$TMP/daemon.log" 2>&1 &
PID=$!

PEAK=0
FDS=0
POLLS=0
while kill -0 "$PID" 2>/dev/null; do
    # Sample before sleeping: a short run must still yield at least one data
    # point, and a completed daemon has no /proc entry left to inspect.
    RSS=$(ps -o rss= -p "$PID" 2>/dev/null | tr -d ' ')
    if [ -n "$RSS" ]; then
        [ "$RSS" -gt "$PEAK" ] && PEAK=$RSS
        FDS=$(ls /proc/"$PID"/fd 2>/dev/null | wc -l)
        POLLS=$((POLLS + 1))
    fi
    sleep 0.2
done
wait "$PID"
RC=$?
PID=""
FAILED=0
if [ "$POLLS" -eq 0 ]; then
    # A run that measured no RSS/fd is a failed gate, not a warning: the
    # ceilings below would otherwise pass on "0 KB, fd 0" without evidence.
    echo "soak: daemon finished before a poll (RSS/fd not measured)" >&2
    FAILED=1
fi

fail() {
    echo "SOAK FAIL: $1" >&2
    FAILED=1
}

[ "$RC" -eq 0 ] || fail "daemon exited $RC"
grep -Fq "Stopped after $SAMPLES samples." "$TMP/daemon.log" || fail "daemon did not reach the sample target"
for file in state.json latest.json psu.prom; do
    [ -s "$TMP/$file" ] || fail "missing or empty state file $file"
done
ls "$TMP"/daily-*.log >/dev/null 2>&1 || fail "missing daily history file"
grep -Fq 'msi_psu_up 1' "$TMP/psu.prom" || fail "prometheus textfile does not report msi_psu_up 1"
[ "$PEAK" -le 262144 ] || fail "peak RSS $PEAK KB exceeds 256 MiB"
[ "$FDS" -le 64 ] || fail "file descriptor count $FDS exceeds 64"

if [ "$FAILED" -ne 0 ]; then
    echo "SOAK FAIL: $SAMPLES samples; log follows:" >&2
    tail -n 20 "$TMP/daemon.log" >&2
    exit 1
fi

SIZE=$(du -sh "$TMP" | cut -f1)
echo "SOAK PASS: $SAMPLES samples, peak RSS ${PEAK} KB, fd=$FDS, state dir $SIZE"
exit 0
