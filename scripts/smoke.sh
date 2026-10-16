#!/bin/bash
# End-to-end smoke test on the synthetic PSU (no hardware, no network egress).
#
# Everything here is what docs/verify.md walks through by hand: the three output
# formats, the alert path, the black box, OCP, the fan write, the daemon chain
# (prometheus textfile + history + dashboard HTTP) and the P-series multi-rail
# model. It exists so "does the whole thing still work?" is one command.
#
# Usage:  bash scripts/smoke.sh [--keep]
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1

PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
MONITOR="$PY -m msi_psu_monitor"
DAEMON="$PY -m msi_psu_monitor.daemon"

WORK=$(mktemp -d)
PORT=${PORT:-8907}
DASH_PID=""
# `--keep` keeps $WORK so a failure can be looked at; the trap has to carry it,
# because `cleanup` is called with no arguments on exit (`$1` was always empty,
# so the flag was documented, accepted, and silently ignored).
KEEP=${1:-}

cleanup() {
    [ -n "$DASH_PID" ] && kill "$DASH_PID" 2>/dev/null
    if [ "$KEEP" = "--keep" ]; then
        printf '\033[0;33m[KEEP]\033[0m %s\n' "$WORK"
    else
        rm -rf "$WORK"
    fi
}
trap 'cleanup' EXIT

PASS=0
FAIL=0
# Keep in sync with the count quoted in docs/verify.md: a check that quietly
# disappears from this script is a gap nobody notices.
EXPECTED_TOTAL=56

ok()   { PASS=$((PASS + 1)); printf '\033[0;32m  ok\033[0m   %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '\033[0;31m  FAIL\033[0m %s\n' "$1"; [ $# -gt 1 ] && printf '       %s\n' "$2"; }

# assert_line <label> <exact line> <haystack>
# Whole-line match: a substring match on a metric name is worthless here, because
# the "# HELP <name> ..." line above it contains the name too. `msi_psu_up 1` was
# "found" in a file whose sample read `msi_psu_up 0` (the HELP text is
# "# HELP msi_psu_up 1 when the last sample carried sensor readings").
# The haystack is padded with newlines so both the first and the last line match,
# even though command substitution strips the file's trailing newline.
assert_line() {
    case "
$3
" in
        *"
$2
"*) ok "$1" ;;
        *) bad "$1" "expected the line: $2" ;;
    esac
}

# assert_contains <label> <needle> <haystack>
assert_contains() {
    case "$3" in
        *"$2"*) ok "$1" ;;
        *) bad "$1" "expected to find: $2" ;;
    esac
}

# assert_not_contains <label> <needle> <haystack>
assert_not_contains() {
    case "$3" in
        *"$2"*) bad "$1" "unexpected: $2" ;;
        *) ok "$1" ;;
    esac
}

# assert_exit <label> <expected> <actual>
assert_exit() {
    if [ "$2" = "$3" ]; then ok "$1 (exit $3)"; else bad "$1" "want exit $2, got $3"; fi
}

export MSI_PSU_DEMO=1
export MSI_PSU_STATE_DIR="$WORK/state"
mkdir -p "$MSI_PSU_STATE_DIR"

printf '\n\033[1m[1] 三种输出格式\033[0m\n'
OUT=$($MONITOR --once 2>/dev/null)
assert_contains "--once text 有版本与机型" "MSI PSU: MPG Ai1600TS (demo)" "$OUT"
assert_contains "text 有 12V-2x6 状态行" "Status: Normal" "$OUT"
assert_contains "text 有 per-pin 明细" "Per-pin currents (12V-2x6 GPU Safeguard+)" "$OUT"

OUT=$($MONITOR -f json 2>/dev/null)
assert_contains "json 带 unit 元组" '"vout_12v"' "$OUT"
case "$OUT" in
    '{'*'}'*) ok "json 是合法对象" ;;
    *) bad "json 是合法对象" ;;
esac

OUT=$($MONITOR -f prometheus 2>/dev/null)
assert_contains "prom 前缀正确" "msi_psu_" "$OUT"
assert_contains "prom per-pin 标签" 'msi_psu_pin_current{connector="1",pin="1"}' "$OUT"

$MONITOR --once -O "$WORK/out.txt" >/dev/null 2>&1
[ -s "$WORK/out.txt" ] && ok "-O 写出文件" || bad "-O 写出文件"

printf '\n\033[1m[2] 告警路径\033[0m\n'
OUT=$(MSI_PSU_DEMO_ALERT=fan $MONITOR --once 2>"$WORK/err.txt"); RC=$?
assert_exit "告警退出码为 2" 2 "$RC"
assert_contains "告警写到 stderr" "ALERT [critical] fan" "$(cat "$WORK/err.txt")"

# E1h byte order is per model (CPSU.cs names each bit with a per-PID array), so
# the same alert on a MEG PSU must still come out with the MEG name.
OUT=$(MSI_PSU_DEMO_MODEL=ai1300p MSI_PSU_DEMO_ALERT=ovp_12v $MONITOR --once 2>"$WORK/err.txt"); RC=$?
assert_exit "MEG 系告警退出码为 2" 2 "$RC"
assert_contains "MEG 告警用 MEG 的名字" "ALERT [warning] ovp_12v" "$(cat "$WORK/err.txt")"
assert_not_contains "MEG 不报 TS 的针脚名" "ocp_pin1" "$(cat "$WORK/err.txt")"

printf '\n\033[1m[3] 黑盒与 OCP\033[0m\n'
OUT=$($MONITOR --show-log 2>/dev/null)
assert_contains "--show-log 出黑盒" "alert log (black box, last 10, newest first)" "$OUT"

OUT=$($MONITOR --ocp 2>/dev/null)
assert_contains "--ocp 出 0xC0 阈值" "Pin OCP point" "$OUT"
assert_contains "--ocp 出 0xC1 状态" "Conn1" "$OUT"

OUT=$(MSI_PSU_DEMO_MODEL=ai1300p $MONITOR --ocp 2>/dev/null); RC=$?
assert_contains "MEG P 系 --ocp 出单多轨" "Multirail OCP" "$OUT"
assert_exit "MEG P 系 --ocp 退出码 0" 0 "$RC"

OUT=$(MSI_PSU_DEMO_MODEL=meg_ai1600 $MONITOR --ocp 2>/dev/null); RC=$?
assert_contains "Ai1600T --ocp 解释原因" "not available" "$OUT"
assert_exit "Ai1600T --ocp 退出码 0" 0 "$RC"
# The unsupported model writes two lines to -O; two emit() calls kept only the last.
OCP_FILE="$WORK/ocp.txt"
MSI_PSU_DEMO_MODEL=meg_ai1600 $MONITOR --ocp -O "$OCP_FILE" >/dev/null 2>&1
assert_contains "-O 保留首行表头" "MSI PSU: MEG Ai1600" "$(cat "$OCP_FILE" 2>/dev/null)"
assert_contains "-O 保留原因行" "not available" "$(cat "$OCP_FILE" 2>/dev/null)"

printf '\n\033[1m[4] 风扇写入\033[0m\n'
OUT=$($MONITOR --fan-mode customized --fan-duty 55 2>/dev/null)
assert_contains "风扇写 + 读回校验" "Fan mode: customized   Duty: 55%" "$OUT"

printf '\n\033[1m[5] 参数互斥（应为 2 = 用法错误）\033[0m\n'
$MONITOR --ocp --watch 1 >/dev/null 2>&1
assert_exit "--ocp 与 --watch 互斥" 2 "$?"
$MONITOR --port 9000 >/dev/null 2>&1
assert_exit "--port 需配 --dashboard" 2 "$?"
$MONITOR --watch 0 >/dev/null 2>&1
assert_exit "--watch 0 不是忙循环" 2 "$?"
$MONITOR --watch 1 -i nan >/dev/null 2>&1
assert_exit "间隔 nan 被拒" 2 "$?"
$MONITOR --dashboard --export --from 2h >/dev/null 2>&1
assert_exit "--dashboard 不与动作混用" 2 "$?"
# -O must mean "file instead of screen" in watch mode too (it used to print
# to stdout and never create the file).
WATCH_LOG="$WORK/watch.log"
timeout 3 $MONITOR --watch 1 -i 0.05 -O "$WATCH_LOG" >"$WORK/watch.out" 2>/dev/null
assert_contains "--watch -O 写文件" "MSI PSU:" "$(cat "$WATCH_LOG" 2>/dev/null)"
# `if` rather than `[ ... ] && bad ... || ok ...`: bad() returns non-zero when it
# gets no detail argument, which would then also run the ok branch.
if [ -s "$WORK/watch.out" ]; then
    bad "--watch -O 不打屏" "stdout 仍有输出"
else
    ok "--watch -O 不打屏"
fi

printf '\n\033[1m[6] daemon 链路（prometheus + 历史 + 状态）\033[0m\n'
cat > "$WORK/daemon.conf" <<EOF
[daemon]
state_dir = $MSI_PSU_STATE_DIR
prom_path = $WORK/psu.prom
sample_interval = 0.05
prom_interval = 0.05
history_interval = 0.05

[fan]
mode = customized
duty = 40
EOF
$DAEMON --config "$WORK/daemon.conf" --iterations 3 >"$WORK/daemon.log" 2>&1
assert_exit "daemon 跑完 3 个采样" 0 "$?"
grep -q "Restored the configured fan profile" "$WORK/daemon.log" \
    && ok "daemon 恢复 [fan] Profile" || bad "daemon 恢复 [fan] Profile"

PROM=$(cat "$WORK/psu.prom" 2>/dev/null)
assert_contains "prom 有机型标签" 'msi_psu_info{product="MPG Ai1600TS' "$PROM"
assert_line "prom 有 up 指标" 'msi_psu_up 1' "$PROM"
assert_contains "prom 有状态指标" 'msi_psu_status_12v_2x6{status="Normal"}' "$PROM"
assert_line "prom 有 OCP 块" 'msi_psu_ocp_available 1' "$PROM"
assert_line "prom 有 OCP 阈值" 'msi_psu_ocp_pin_point_a{} 12.0' "$PROM"
[ -f "$MSI_PSU_STATE_DIR/state.json" ] && ok "state.json 落盘" || bad "state.json 落盘"
HIST=$(cat "$MSI_PSU_STATE_DIR"/daily-*.log 2>/dev/null | head -1)
case "$HIST" in
    time,*) ok "历史 CSV 有表头" ;;
    *) bad "历史 CSV 有表头" "$HIST" ;;
esac
assert_contains "历史表头含全部 11 列" "time,12v,5v,3v3,total_a,temp,fan,power,eff,cpu_w,gpu_w" "$HIST"

printf '\n\033[1m[7] 多轨机型（P 系）\033[0m\n'
export MSI_PSU_DEMO_MODEL=ai1300p
rm -f "$WORK/psu.prom"
MSI_PSU_STATE_DIR="$WORK/state-p" $DAEMON --config <(sed "s|$MSI_PSU_STATE_DIR|$WORK/state-p|" "$WORK/daemon.conf") \
    --iterations 2 >/dev/null 2>&1
PROM=$(cat "$WORK/psu.prom" 2>/dev/null)
assert_contains "P 系 prom 出五条轨道" 'msi_psu_rail_current{rail="12V5"}' "$PROM"
assert_contains "P 系 prom 出 CPU 瓦特" "msi_psu_cpu_watts" "$PROM"
assert_line "P 系 prom 出多轨标志" 'msi_psu_multirail_ocp{} 1' "$PROM"
assert_line "P 系 prom 不出 OCP 阈值" 'msi_psu_ocp_available 0' "$PROM"
CSV=$(MSI_PSU_STATE_DIR="$WORK/state-p" $MONITOR --export --from 30m --columns cpu,gpu 2>/dev/null)
assert_contains "P 系导出含 cpu,gpu 列" "time,cpu,gpu" "$CSV"
unset MSI_PSU_DEMO_MODEL

printf '\n\033[1m[8] dashboard HTTP\033[0m\n'
$MONITOR --dashboard --port "$PORT" >/dev/null 2>"$WORK/dashboard.err" &
DASH_PID=$!
for _ in $(seq 20); do
    curl -sf -o /dev/null "http://127.0.0.1:$PORT/" && break
    sleep 0.3
done
# The four checks below cannot tell whose server answered: a stale or foreign
# dashboard on $PORT makes this run pass while the process under test died with
# "cannot serve on 127.0.0.1:$PORT". It has to be our own child that serves.
# `kill -0` alone is not enough -- an exited child stays a zombie until reaped
# and still passes it -- so an empty stderr is checked too (a failed bind reports
# there). The grace period covers Python's start-up: the curl above can be
# answered by the foreign listener before our child has even reached bind().
sleep 1
if kill -0 "$DASH_PID" 2>/dev/null && [ ! -s "$WORK/dashboard.err" ]; then
    ok "dashboard 子进程是本进程（无启动错误）"
else
    bad "dashboard 子进程是本进程（无启动错误）" "$(head -1 "$WORK/dashboard.err")"
fi
PAGE=$(curl -sf "http://127.0.0.1:$PORT/" 2>/dev/null)
assert_contains "首页可访问" "<title>MSI PSU Monitor</title>" "$PAGE"
assert_contains "首页无占位符残留" "setInterval(load, 30000)" "$PAGE"
STATE=$(curl -sf "http://127.0.0.1:$PORT/api/state" 2>/dev/null)
assert_contains "/api/state 返回 JSON" '"count"' "$STATE"
CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/nope")
[ "$CODE" = "404" ] && ok "未知路由 404" || bad "未知路由 404" "got $CODE"
CODE=$(curl -s -I -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/nope")
[ "$CODE" = "404" ] && ok "HEAD 未知路由也是 404" || bad "HEAD 未知路由也是 404" "got $CODE"

printf '\n\033[1m[9] Python 3.10 语法与零依赖\033[0m\n'
$PY - "$ROOT" <<'EOF'
import ast, pathlib, sys
root = pathlib.Path(sys.argv[1])
for path in sorted(root.glob('msi_psu_monitor/*.py')) + sorted((root / 'tests').glob('*.py')):
    ast.parse(path.read_text(), filename=str(path), feature_version=(3, 10))
print('  3.10 syntax ok')
EOF
[ $? -eq 0 ] && ok "全部 .py 通过 3.10 语法校验" || bad "全部 .py 通过 3.10 语法校验"

printf '\n\033[1m[10] systemd unit 与 udev 规则\033[0m\n'
# Packaging artifacts that CI never installs: verify them with the tools that
# would reject them at install time. A missing tool still counts as a check so
# the total stays deterministic.
if command -v systemd-analyze >/dev/null 2>&1; then
    if systemd-analyze verify "$ROOT/systemd/msi-psu-monitor.service" 2>"$WORK/systemd.err"; then
        ok "unit 通过 systemd-analyze verify"
    else
        bad "unit 通过 systemd-analyze verify" "$(tail -1 "$WORK/systemd.err")"
    fi
else
    ok "systemd-analyze 不存在，跳过 unit 校验"
fi
if udevadm verify --help >/dev/null 2>&1; then
    if udevadm verify "$ROOT/systemd/99-msi-psu.rules" >/dev/null 2>&1; then
        ok "udev 规则通过 udevadm verify"
    else
        bad "udev 规则通过 udevadm verify"
    fi
else
    ok "udevadm verify 不存在，跳过规则校验"
fi

# The .deb is what users install, so build it the way a hardened machine would
# (umask 077) and read the modes dpkg actually recorded: `cp` without -m shipped
# root-only modules, which breaks the non-root uaccess use case the udev rule
# exists for, and nothing inspected the archive's contents before. Two checks in
# every branch, so the total stays deterministic.
DEB="$ROOT/dist/msi-psu-monitor_1.0.0_all.deb"
if command -v dpkg-deb >/dev/null 2>&1; then
    listing='(build_deb.sh failed)'
    if (umask 077; bash "$ROOT/scripts/build_deb.sh" >/dev/null 2>&1); then
        listing=$(dpkg-deb -c "$DEB" 2>/dev/null)
    fi
    assert_contains "deb 里带 /etc/配置（conffile）" "./etc/msi-psu-monitor.conf" "$listing"
    case "$listing" in
        *"-rw-r--r-- root/root"*"msi_psu_monitor/protocol.py"*)
            ok "deb 里的模块是 0644（不继承构建者 umask）" ;;
        *)
            bad "deb 里的模块是 0644（不继承构建者 umask）" "限制性 umask 下会变成 root-only" ;;
    esac
else
    ok "dpkg-deb 不存在，跳过 .deb 内容校验（conffile）"
    ok "dpkg-deb 不存在，跳过 .deb 内容校验（模块权限）"
fi

if [ "$PASS" -ne "$EXPECTED_TOTAL" ]; then
    bad "检查项数量应为 $EXPECTED_TOTAL" "实际 $PASS（有检查被删掉或没加进计数？）"
fi
printf '\n\033[1m结果: %d passed, %d failed\033[0m\n\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
