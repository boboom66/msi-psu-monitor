#!/bin/bash
# Hardware acceptance harness: read-only by default, writes only with --writes.
# Run on the test machine after setup.sh; no hardware = use --demo to self-test.
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
if [ -x "$HERE/bin/msi-psu-monitor" ] || [ -d "$HERE/source" ]; then
    KIT_DIR=$HERE
elif [ -x "$HERE/../bin/msi-psu-monitor" ] || [ -d "$HERE/../source" ]; then
    KIT_DIR=$(cd "$HERE/.." && pwd)
else
    KIT_DIR=$(cd "$HERE/../.." && pwd)
fi
DEMO=0
WRITES=0
YES=0
PORT=8899
OUT=""
PASS=0
FAIL=0
SKIP=0
MANUAL=0
FAIL_NAMES=()
DASH_PID=""

info() { printf "[INFO] %s\n" "$*"; }
warn() { printf "[WARN] %s\n" "$*" >&2; }

usage() {
    cat <<EOF
Usage: sudo ./acceptance.sh [--demo] [--writes] [--yes] [--port N] [--out DIR]
  --demo     use the synthetic PSU (proves the harness itself; NOT hardware)
  --writes   test the fan write (asks first); Zero Fan/buzzer/rail stay manual
  --yes      non-interactive confirmation for the write tests
  --port N   dashboard port (default 8899)
  --out DIR  evidence directory (default /var/log/msi-psu-acceptance/<stamp>)
EOF
}
while [ $# -gt 0 ]; do
    case "$1" in
        --demo) DEMO=1 ;;
        --writes) WRITES=1 ;;
        --yes) YES=1 ;;
        --port) shift; PORT=${1:?--port needs a value} ;;
        --out) shift; OUT=${1:?--out needs a value} ;;
        -h|--help) usage; exit 0 ;;
        *) printf "unknown argument: %s\n" "$1" >&2; exit 2 ;;
    esac
    shift
done

STAMP=$(date +%Y%m%d-%H%M%S)
if [ -n "$OUT" ]; then
    EVIDENCE=$OUT
elif [ "$(id -u)" -eq 0 ]; then
    EVIDENCE=/var/log/msi-psu-acceptance/$STAMP
else
    EVIDENCE=$PWD/acceptance-$STAMP
fi
install -d "$EVIDENCE" || { printf "cannot create evidence dir %s\n" "$EVIDENCE" >&2; exit 1; }

cleanup() {
    if [ -n "$DASH_PID" ]; then
        kill "$DASH_PID" 2>/dev/null || true
        wait "$DASH_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

pass() { PASS=$((PASS + 1)); printf "  PASS  %s\n" "$1"; RESULTS+=("PASS|$1|$2"); }
fail() { FAIL=$((FAIL + 1)); FAIL_NAMES+=("$1"); printf "  FAIL  %s\n" "$1"; RESULTS+=("FAIL|$1|$2"); }
skip() { SKIP=$((SKIP + 1)); printf "  SKIP  %s (%s)\n" "$1" "$2"; RESULTS+=("SKIP|$1|$2"); }
manual() { MANUAL=$((MANUAL + 1)); printf "  MANUAL %s (%s)\n" "$1" "${2:-}"; RESULTS+=("MANUAL|$1|${2:-}"); }
RESULTS=()

choose_command() {
    if [ -n "${MSI_PSU_MONITOR:-}" ]; then
        MONITOR=("$MSI_PSU_MONITOR")
    elif command -v msi-psu-monitor >/dev/null 2>&1; then
        MONITOR=(msi-psu-monitor)
    elif [ -x "$KIT_DIR/bin/msi-psu-monitor" ] && "$KIT_DIR/bin/msi-psu-monitor" --version >/dev/null 2>&1; then
        MONITOR=("$KIT_DIR/bin/msi-psu-monitor")
    elif [ -d "$KIT_DIR/source/msi_psu_monitor" ] && command -v python3 >/dev/null 2>&1; then
        MONITOR=(env PYTHONPATH="$KIT_DIR/source" python3 -m msi_psu_monitor)
    else
        printf "no usable msi-psu-monitor command; run setup.sh first\n" >&2
        exit 1
    fi
    if [ -n "${MSI_PSU_DAEMON:-}" ]; then
        DAEMON=("$MSI_PSU_DAEMON")
    elif command -v msi-psu-monitor-daemon >/dev/null 2>&1; then
        DAEMON=(msi-psu-monitor-daemon)
    elif [ -x "$KIT_DIR/bin/msi-psu-monitor-daemon" ] && "$KIT_DIR/bin/msi-psu-monitor-daemon" --version >/dev/null 2>&1; then
        DAEMON=("$KIT_DIR/bin/msi-psu-monitor-daemon")
    elif [ -d "$KIT_DIR/source/msi_psu_monitor" ] && command -v python3 >/dev/null 2>&1; then
        DAEMON=(env PYTHONPATH="$KIT_DIR/source" python3 -m msi_psu_monitor.daemon)
    else
        printf "no usable daemon command; run setup.sh first\n" >&2
        exit 1
    fi
}
choose_command
[ "$DEMO" -eq 1 ] && export MSI_PSU_DEMO=1

run_capture() {
    local name=$1
    shift
    if "$@" >"$EVIDENCE/$name.out" 2>"$EVIDENCE/$name.err"; then
        pass "$name" "exit 0"
        return 0
    fi
    fail "$name" "nonzero exit; see $name.err"
    return 1
}
check_contains() {
    local name=$1 needle=$2
    if grep -Fq "$needle" "$EVIDENCE/$name.out"; then
        pass "$name contains $needle" ""
    else
        fail "$name missing $needle" "see $name.out"
    fi
}
confirm() {
    [ "$YES" -eq 1 ] && return 0
    local answer
    printf "%s [y/N] " "$1"
    read -r answer || return 1
    case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

printf "\n=== msi-psu-monitor hardware acceptance ===\n"
printf "evidence: %s\n" "$EVIDENCE"
if [ "$DEMO" -eq 1 ]; then
    printf "MODE: DEMO (synthetic PSU; this is not hardware evidence)\n"
else
    printf "MODE: REAL HARDWARE\n"
fi

{
    date -Is
    id
    uname -a
    cat /etc/os-release 2>/dev/null || true
    ldd --version 2>/dev/null | awk 'NR==1' || true
    printf "kit: %s\n" "$KIT_DIR"
    printf "monitor: %s\n" "${MONITOR[*]}"
    printf "daemon: %s\n" "${DAEMON[*]}"
    command -v lsusb >/dev/null 2>&1 && lsusb || true
    ls -l /dev/hidraw* 2>/dev/null || true
    command -v dmesg >/dev/null 2>&1 && dmesg | tail -40 || true
} > "$EVIDENCE/environment.txt" 2>&1

if [ "$DEMO" -eq 0 ] && ! compgen -G "/dev/hidraw*" >/dev/null; then
    printf "\nBLOCKED: no /dev/hidraw* device. Connect the PSU USB data cable and rerun;\n"
    printf "for a harness self-test without hardware use: %s --demo\n" "$KIT_DIR/acceptance.sh"
    fail "hardware-present" "no /dev/hidraw*"
    printf "\nResult: %d pass, %d fail, %d manual, BLOCKED\n" "$PASS" "$FAIL" "$MANUAL"
    exit 2
fi

printf "\n[1] version / identity / formats\n"
run_capture 01-version "${MONITOR[@]}" --version || true
run_capture 02-once "${MONITOR[@]}" --once || true
check_contains 02-once "MSI PSU:"
check_contains 02-once "FAN"
run_capture 03-json "${MONITOR[@]}" -f json || true
if command -v jq >/dev/null 2>&1; then
    if jq -e . "$EVIDENCE/03-json.out" >/dev/null 2>&1; then pass "json parses" ""; else fail "json parses" "jq failed"; fi
elif command -v python3 >/dev/null 2>&1; then
    if python3 -m json.tool "$EVIDENCE/03-json.out" >/dev/null 2>&1; then pass "json parses" ""; else fail "json parses" "python json.tool failed"; fi
else
    skip "json parses" "neither jq nor python3 installed"
fi
run_capture 04-prom "${MONITOR[@]}" -f prometheus || true
check_contains 04-prom "msi_psu_up 1"
check_contains 04-prom "msi_psu_info"
run_capture 05-output "${MONITOR[@]}" -f json -O "$EVIDENCE/05-output.json" || true
if [ -s "$EVIDENCE/05-output.json" ]; then pass "output file" ""; else fail "output file" "empty"; fi

printf "\n[2] queries (read-only)\n"
run_capture 06-ocp "${MONITOR[@]}" --ocp || true
run_capture 07-show-log "${MONITOR[@]}" --show-log || true
run_capture 08-show-alert-log "${MONITOR[@]}" --show-alert-log || true

# Local thresholds + effective-config query (read-only; no writes to the PSU).
printf '[alerts]\npower_w = 1\n' > "$EVIDENCE/08b-threshold.conf"
"${MONITOR[@]}" --once --config "$EVIDENCE/08b-threshold.conf" \
    >"$EVIDENCE/08b-threshold.out" 2>"$EVIDENCE/08b-threshold.err"
THRESHOLD_RC=$?
if [ "$THRESHOLD_RC" -eq 2 ] \
    && grep -Fq 'power_high' "$EVIDENCE/08b-threshold.err" \
    && grep -Fq 'Thresholds    :' "$EVIDENCE/08b-threshold.out"; then
    pass "threshold alert exit 2" ""
else
    fail "threshold alert" "expected exit 2 with power_high; got $THRESHOLD_RC"
fi
run_capture 08c-dump-config "${MONITOR[@]}" --dump-config || true
check_contains 08c-dump-config "[alerts]"
check_contains 08c-dump-config "power_w ="
timeout 3 "${MONITOR[@]}" --watch 1 >"$EVIDENCE/09-watch.out" 2>"$EVIDENCE/09-watch.err"
WATCH_RC=$?
if [ "$WATCH_RC" -ne 0 ] && [ "$WATCH_RC" -ne 124 ]; then
    fail "watch command" "exit $WATCH_RC; see 09-watch.err"
elif [ "$(grep -c "MSI PSU:" "$EVIDENCE/09-watch.out" 2>/dev/null || true)" -ge 2 ]; then
    pass "watch produced at least 2 frames" ""
else
    fail "watch frames" "expected >=2"
fi
printf "\n[3] daemon / prometheus / history / live / dashboard\n"
STATE=$EVIDENCE/state
install -d "$STATE"
if MSI_PSU_STATE_DIR="$STATE" "${DAEMON[@]}" --iterations 2 --state-dir "$STATE" --prom-path "$EVIDENCE/psu.prom" >"$EVIDENCE/10-daemon.out" 2>"$EVIDENCE/10-daemon.err"; then
    pass "daemon --iterations 2" ""
else
    fail "daemon --iterations 2" "see 10-daemon.err"
fi
for f in state.json latest.json psu.prom; do
    if [ -s "$STATE/$f" ] || [ -s "$EVIDENCE/$f" ]; then pass "daemon artifact $f" ""; else fail "daemon artifact $f" "missing"; fi
done
if compgen -G "$STATE/daily-*.log" >/dev/null; then pass "history daily log" ""; else fail "history daily log" "missing"; fi

if command -v curl >/dev/null 2>&1; then
    MSI_PSU_STATE_DIR="$STATE" "${MONITOR[@]}" --dashboard --port "$PORT" >"$EVIDENCE/11-dashboard.out" 2>"$EVIDENCE/11-dashboard.err" &
    DASH_PID=$!
    READY=0
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then READY=1; break; fi
        sleep 0.5
    done
    if [ "$READY" -eq 1 ]; then
        for path in / /api/state /api/live "/api/export?from=2h"; do
            safe=$(printf "%s" "$path" | tr "/?=&" "____")
            if curl -fsS --max-time 5 "http://127.0.0.1:$PORT$path" >"$EVIDENCE/11-dashboard$safe.out"; then
                pass "dashboard $path" ""
            else
                fail "dashboard $path" "curl failed"
            fi
        done
    else
        fail "dashboard starts" "see 11-dashboard.err"
    fi
    kill "$DASH_PID" 2>/dev/null || true
    wait "$DASH_PID" 2>/dev/null || true
    DASH_PID=""
else
    skip "dashboard HTTP" "curl not installed"
fi

if MSI_PSU_STATE_DIR="$STATE" "${MONITOR[@]}" --export --from 2h --columns temp,fan -O "$EVIDENCE/12-export.csv" >"$EVIDENCE/12-export.out" 2>"$EVIDENCE/12-export.err"; then
    pass "csv export" ""
    if head -1 "$EVIDENCE/12-export.csv" | grep -q "^time,"; then pass "csv header" ""; else fail "csv header" "unexpected"; fi
else
    fail "csv export" "see 12-export.err"
fi

if [ "$WRITES" -eq 1 ]; then
    printf "\n[4] fan write test (explicitly requested)\n"
    if ! command -v jq >/dev/null 2>&1; then
        skip "fan write test" "jq is required to read the current fan setting safely"
    elif confirm "This writes the fan setting. Continue?"; then
        CURRENT_JSON=$EVIDENCE/03-json.out
        FAN_MODE=$(jq -r '.fan_mode.value // .fan_mode // empty' "$CURRENT_JSON" 2>/dev/null || true)
        FAN_DUTY=$(jq -r '.fan_duty.value // .fan_duty // empty' "$CURRENT_JSON" 2>/dev/null || true)
        run_capture 20-fan-write "${MONITOR[@]}" --fan-duty 60 || true
        check_contains 20-fan-write "Fan mode: customized"
        case "$FAN_MODE" in
            auto|performance)
                run_capture 21-fan-restore "${MONITOR[@]}" --fan-mode "$FAN_MODE" || true ;;
            customized)
                if [ -n "$FAN_DUTY" ]; then
                    run_capture 21-fan-restore "${MONITOR[@]}" --fan-mode customized --fan-duty "$FAN_DUTY" || true
                else
                    run_capture 21-fan-restore "${MONITOR[@]}" --fan-mode customized || true
                fi ;;
            *) skip "fan restore" "current fan mode unavailable" ;;
        esac
        printf "\nAdvanced writes are intentionally manual (read the safety notes in docs/verify.md):\n"
        printf "  sudo msi-psu-monitor --zero-fan on/off     # TS only, read back\n"
        printf "  sudo msi-psu-monitor --buzzer-off          # TS only, no read-back\n"
        printf "  sudo msi-psu-monitor --set-rail multi      # MEG P only, then restore\n"
    else
        skip "fan write test" "declined"
    fi
else
    printf "\n[4] write tests skipped (default read-only; use --writes)\n"
    skip "write tests" "read-only run"
fi
printf "\n[5] manual checks (not PASS until you verify them)\n"
if grep -Fq "AC Input:" "$EVIDENCE/02-once.out"; then
    printf "  VIN: "; grep -F "AC Input:" "$EVIDENCE/02-once.out" | head -1
    manual "VIN reads 220-240 V" "compare with mains / MSI Center"
else
    skip "VIN" "model does not report AC Input (expected on TS)"
fi
manual "readings match MSI Center (voltage/current/power/efficiency/temp/fan)" "manual comparison"
manual "12V-2x6 pins and status look sane under load" "manual inspection"
manual "no false alert during idle; alert/recovery visible if triggered" "manual observation"

printf "\n=== report ===\n"
REPORT=$EVIDENCE/report.md
{
    printf "# MSI PSU hardware acceptance report\n\n"
    printf -- "- Time: %s\n" "$(date -Is)"
    printf -- "- Mode: %s\n" "$([ "$DEMO" -eq 1 ] && echo DEMO || echo REAL)"
    printf -- "- Host: %s / %s\n" "$(uname -n)" "$(uname -r)"
    printf -- "- Architecture: %s\n" "$(uname -m)"
    printf -- "- OS: %s\n" "$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2- | tr -d '"')"
    printf -- "- Command: %s\n" "${MONITOR[*]}"
    printf -- "- Evidence: %s\n\n" "$EVIDENCE"
    printf "| Status | Check | Note |\n|---|---|---|\n"
    for row in "${RESULTS[@]}"; do
        IFS="|" read -r st name note <<< "$row"
        printf "| %s | %s | %s |\n" "$st" "$name" "$note"
    done
    printf "\n## Totals\n\n- PASS: %d\n- FAIL: %d\n- SKIP: %d\n- MANUAL: %d\n" "$PASS" "$FAIL" "$SKIP" "$MANUAL"
    if [ "$DEMO" -eq 1 ]; then
        printf "\n> DEMO mode uses the synthetic PSU. It does NOT prove real hardware communication.\n"
    fi
} > "$REPORT"
cat "$REPORT"

TAR="${EVIDENCE}.tar.gz"
tar -czf "$TAR" -C "$(dirname "$EVIDENCE")" "$(basename "$EVIDENCE")" 2>/dev/null || warn "could not create $TAR"
printf "\nEvidence bundle: %s\n" "$TAR"
printf "Report: %s\n" "$REPORT"
if [ "$FAIL" -gt 0 ]; then
    printf "\nResult: FAIL (%d failures).\n" "$FAIL"
    exit 1
fi
printf "\nResult: no automated failures (%d pass, %d manual, %d skip).\n" "$PASS" "$MANUAL" "$SKIP"
printf "Manual checks are NOT PASS until you confirm them.\n"
exit 0