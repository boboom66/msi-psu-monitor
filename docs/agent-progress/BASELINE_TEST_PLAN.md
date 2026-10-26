# BASELINE TEST PLAN — implemented features

Target: tag `baseline-2026-10-26` (`baseline/pre-product-v2`).
Environment: Linux (Ubuntu 22.04/24.04), Python 3.10/3.12/3.13, demo mode for
all non-hardware tests.

Status values: `NOT RUN`, `PASS`, `FAIL`, `BLOCKED`, `UNKNOWN`.
`UNKNOWN` is not `PASS`.

## A. Automated gates

| ID | Gate | Command | Expected | Status |
|---|---|---|---|---|
| B-01 | Full test suite | `uv run --group dev pytest -q` | exit 0; record count | NOT RUN |
| B-02 | Lint | `uv run --group dev ruff check .` | exit 0 | NOT RUN |
| B-03 | Format | `uv run --group dev ruff format --check .` | exit 0 | NOT RUN |
| B-04 | Types | `uv run --group dev mypy msi_psu_monitor/` | exit 0 | NOT RUN |
| B-05 | Coverage | `coverage run --branch -m pytest -q && coverage report --fail-under=90` | ≥90% | NOT RUN |
| B-06 | Smoke | `bash scripts/smoke.sh` | all checks pass | NOT RUN |
| B-07 | Soak 5k | `bash scripts/soak.sh 5000` | exit 0; RSS/fd limits | NOT RUN |
| B-08 | Shellcheck | `shellcheck -S warning scripts/*.sh scripts/hardware/*.sh` | exit 0 | NOT RUN |
| B-09 | Docs consistency | `uv run --group dev pytest -q tests/test_docs_consistency.py` | exit 0 | NOT RUN |

## B. CLI acquisition

| ID | Feature | Command | Expected | Status |
|---|---|---|---|---|
| B-10 | One-shot text | `MSI_PSU_DEMO=1 msi-psu-monitor --once` | model, voltages, current, power, temp, fan, status | NOT RUN |
| B-11 | Default run | `MSI_PSU_DEMO=1 msi-psu-monitor` | same as `--once` | NOT RUN |
| B-12 | JSON | `MSI_PSU_DEMO=1 msi-psu-monitor --once -f json` | valid JSON; numbers finite | NOT RUN |
| B-13 | Prometheus stdout/file | `... -f prometheus -O /tmp/psu.prom` | canonical textfile; `msi_psu_up 1` | NOT RUN |
| B-14 | Watch pipe | `... --watch 0.2 \| head` | frames flushed; exits cleanly | NOT RUN |
| B-15 | Watch TTY redraw | `... --watch 1` in a PTY | redraw, no scroll spam, Ctrl-C restores cursor | NOT RUN |
| B-16 | Version/help | `--version`, `--help` | version matches pyproject; all flags documented | NOT RUN |

## C. Interactive views

| ID | Feature | Command | Expected | Status |
|---|---|---|---|---|
| B-20 | Terminal dashboard | `MSI_PSU_DEMO=1 msi-psu-monitor --dashboard-text` | readable 80x24 and 120x40; `q`/Ctrl-C clean | NOT RUN |
| B-21 | Menu TTY | `MSI_PSU_DEMO=1 msi-psu-monitor --menu` | arrow/number selection; back/quit | NOT RUN |
| B-22 | Menu non-TTY | `... --menu </dev/null` | numbered fallback; no crash | NOT RUN |
| B-23 | Web dashboard | `... --dashboard --port 8899` | `/` 200; charts; `/api/live` 200 | NOT RUN |
| B-24 | Dashboard stale | stop daemon, reload | 503 or visible stale banner, not frozen | NOT RUN |
| B-25 | Dashboard HEAD/Host | `curl -I`; `Host: evil.example` | HEAD matches GET; non-loopback 421 | NOT RUN |

## D. History/export/alerts

| ID | Feature | Command | Expected | Status |
|---|---|---|---|---|
| B-30 | Export CSV | `... --export --from 2h --columns all` | stable header/rows | NOT RUN |
| B-31 | Export stdout | `... --export --from 2h -O -` | CSV on stdout | NOT RUN |
| B-32 | Export edge | empty window, bad column | header only / actionable error | NOT RUN |
| B-33 | Alert log viewer | `... --show-alert-log` | local logs; missing dir graceful | NOT RUN |
| B-34 | Local thresholds | set `[alerts] power_w=1`; run daemon | `threshold_alerts` + exit 2 + log | NOT RUN |
| B-35 | Hardware alerts | E1h demo trigger | severity/status/exit 2 | NOT RUN |

## E. OCP / black box

| ID | Feature | Command | Expected | Status |
|---|---|---|---|---|
| B-40 | OCP read | `... --ocp` (TS demo) | thresholds + per-pin state | NOT RUN |
| B-41 | OCP on MEG | `MSI_PSU_DEMO_MODEL=ai1300p ... --ocp` | explanation; exit 0 | NOT RUN |
| B-42 | Dump thresholds text | `... --dump-thresholds` | 5 values/units | NOT RUN |
| B-43 | Dump thresholds JSON | `... --dump-thresholds -f json` | valid JSON | NOT RUN |
| B-44 | OCP set validation | `... --ocp-set 9,4,5,5,30` | rejected, no clamp | NOT RUN |
| B-45 | OCP set no-op | current values | no write / clear message | NOT RUN |
| B-46 | Load thresholds | dump JSON → `--load-thresholds` | read-back verified | NOT RUN |
| B-47 | Black box | `... --show-log` | newest-first slots; empty graceful | NOT RUN |

## F. Control writes (demo/mock only)

| ID | Feature | Command | Expected | Status |
|---|---|---|---|---|
| B-50 | Fan mode | `... --fan-mode customized --fan-duty 50` | read-back verified | NOT RUN |
| B-51 | Fan duty bounds | `--fan-duty 101` | rejected | NOT RUN |
| B-52 | Zero Fan | `... --zero-fan on` | 43h + F1h + 42h read-back | NOT RUN |
| B-53 | Buzzer | `... --buzzer-off` | acknowledged; never “silenced” | NOT RUN |
| B-54 | Rail mode | `MSI_PSU_DEMO_MODEL=ai1300p ... --set-rail multi` | read-back verified | NOT RUN |
| B-55 | Unsupported write | zero fan on MEG / rail on TS | clear model-gate error | NOT RUN |

## G. Daemon / Prometheus

| ID | Feature | Command | Expected | Status |
|---|---|---|---|---|
| B-60 | Daemon start | `MSI_PSU_DEMO=1 msi-psu-monitor-daemon` | samples; state/latest/daily/prom written | NOT RUN |
| B-61 | Daemon stop | SIGTERM | clean exit; no traceback | NOT RUN |
| B-62 | Failed read | stop demo / inject failure | `msi_psu_up 0` + reason | NOT RUN |
| B-63 | Rescan | 5 failures then recover | reconnects | NOT RUN |
| B-64 | Promtool | `promtool check metrics` / `check rules` | no syntax errors; warnings recorded | NOT RUN |

## H. Demo/model matrix

| ID | Model | Command | Expected | Status |
|---|---|---|---|---|
| B-70 | mpg_ai1600ts | `MSI_PSU_DEMO_MODEL=mpg_ai1600ts ... --once` | per-pin + OCP | NOT RUN |
| B-71 | mpg_ai1300ts | `... mpg_ai1300ts ...` | per-pin + OCP | NOT RUN |
| B-72 | meg_ai1600 | `... meg_ai1600 ...` | 20B payload; no per-pin | NOT RUN |
| B-73 | ai1300p | `... ai1300p ...` | multirail; VIN | NOT RUN |
| B-74 | ai1000p | `... ai1000p ...` | multirail; VIN | NOT RUN |

## I. Error paths / security

| ID | Case | Command | Expected | Status |
|---|---|---|---|---|
| B-80 | No PSU | unset demo | actionable error; exit 1 | NOT RUN |
| B-81 | Permission denied | non-root on hidraw | actionable udev/sudo next step | NOT RUN |
| B-82 | Usage conflicts | `--once --export` | exit 2; usage message | NOT RUN |
| B-83 | Bad config | invalid INI value | one clear error; exit 1 | NOT RUN |
| B-84 | Stale/corrupt state | corrupt `state.json` | no crash; recover/ignore | NOT RUN |
| B-85 | Dashboard security | Host/CSP/HEAD/XSS | 421, headers, no injection | NOT RUN |
| B-86 | Untrusted serial | CRLF in demo serial | sanitized log/export | NOT RUN |

## J. Packaging / install

| ID | Case | Command | Expected | Status |
|---|---|---|---|---|
| B-90 | Source deb | `bash scripts/build_deb.sh` | installable; modes 644 | NOT RUN |
| B-91 | Binary tar/deb | `bash scripts/build_binary.sh && build_deb_binary.sh` | no Python dependency; `--once` clean env | NOT RUN |
| B-92 | Hardware kit | `bash scripts/build_hardware_kit.sh` | kit self-test | NOT RUN |
| B-93 | Install/uninstall | `sudo ./scripts/install.sh` then uninstall | service/udev/config; no residue | BLOCKED (root host) |
| B-94 | Upgrade | install 1.0.0 → 1.0.1 | config/state preserved | BLOCKED (root host) |

## K. Long-run / hardware

| ID | Case | Command | Expected | Status |
|---|---|---|---|---|
| B-95 | 24h soak | daemon on a real host | RSS/fd/disk bounds; no restart loop | BLOCKED (human) |
| B-96 | 5-model hardware | hardware kit | E4 evidence | BLOCKED (human) |
| B-97 | OCP write bench | dump → write → read-back → power-cycle → restore | E4 evidence | BLOCKED (human) |
| B-98 | arm64 | release artifact on arm64 | `--once` + smoke | BLOCKED (human/CI) |

## Execution order

1. A-01..A-09 (fail fast).
2. B-10..B-16 (acquisition).
3. D-30..D-35 (history/alerts).
4. E-40..E-47 (OCP/black box).
5. F-50..F-55 (writes, demo only).
6. C-20..C-25 (views).
7. G-60..G-64 (daemon/Prometheus).
8. H-70..H-74 (model matrix).
9. I-80..I-86 (errors/security).
10. J-90..J-94 (packaging; root gates human).
11. K-95..K-98 (human/hardware).

## Reporting

Write `BASELINE_TEST_REPORT.md` with:

- tag + commit + environment + Python + date
- each ID: PASS/FAIL/BLOCKED/UNKNOWN + evidence path
- failures: file:line, repro, expected vs actual, severity
- a summary: pass/fail/blocked counts
- a verdict: BASELINE GREEN / BASELINE AMBER / BASELINE RED

Do not mark hardware/arm64/24h as PASS without evidence.
