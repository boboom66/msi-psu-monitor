# Test report — Phase 5 deep audit

> **历史快照（Phase 5）**。当前门禁为 **803 tests / 94% 分支覆盖率 / smoke 58 / soak 5000**；当前事实见 `FIX_LOG.md` 与 `RELEASE_READINESS.md`。

All commands were executed in `/home/timzhang/projects/project/msi-psu-monitor` (WSL Linux,
x86_64, Python 3.12.3 in `.venv`). Nothing below is inferred from reading code.

## 1. Baseline before changes

| Command | Result |
|---|---|
| `git status --short` | clean at `fdfc97d` |
| `.venv/bin/python -m pytest -q` | **645 passed** in 17.98 s |
| `ruff check .` / `ruff format --check .` / `mypy msi_psu_monitor/` | clean / 53 formatted / no issues |

## 2. Targeted reproduction before each fix

| Bug | Reproduction command (scratch script) | Observed before fix |
|---|---|---|
| DEF-022 | `monitor.emit('NEW', link)` for `link -> real`; `run_export(..., output=link)` | `link.is_symlink()` False afterwards, `real` unchanged; export same |
| DEF-023 | write a real daemon `latest.json`, GET `/api/live`, compare chart keys parsed from `dashboard.PAGE` | only `temp` was both a chart key and a latest.json key |
| DEF-024 | fake clock 3601 s ahead + `stats.prune_history = raise PermissionError` | `daemon.tick()` raised `PermissionError` |
| DEF-025 | TS stub: pins 20 A → alert fires; remove `iout_pins`; poll again | status dropped to Normal; `take_cleared()` contained `ocp_pin1`; `pin_imbalance` vanished without a recovery entry |
| DEF-026 | compare `scripts/smoke.sh` / `tests/test_e2e_cli.py` version literals with `pyproject.toml` | literal `1.0.0` in the .deb path and the version assertion |
| DEF-027 | inspect generated `START-HERE.md` template | literal "glibc 2.39" while `BUILD-INFO` uses the host `ldd` |
| DEF-031 | `make_server(state_dir=<missing>)`; GET `/api/typo` | 503 "no state directory" instead of 404 |

## 3. After the fixes

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest -q` | **735 passed** in 18.84 s |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 53 files already formatted |
| `mypy msi_psu_monitor/` | Success: no issues found in 10 source files |
| `coverage run --branch -m pytest -q` + `coverage report --fail-under=90` | **92%** total (2586 stmts, 188 missed; 874 branches, 67 partial) |
| `bash scripts/smoke.sh` | **58 passed, 0 failed** |
| `shellcheck -S warning scripts/*.sh scripts/hardware/*.sh` | clean |
| `systemd-analyze verify systemd/msi-psu-monitor.service` | clean (only unrelated host-unit warnings) |
| `udevadm verify systemd/99-msi-psu.rules` | Success: 1, Fail: 0 |
| Node harness executing the shipped page JS | 3 live rows → every chart series has 3 points (before fix: 1) |

## 4. Exploratory / adversarial runs

| Probe | Result |
|---|---|
| 270 unique CLI flag combinations under `MSI_PSU_DEMO=1` (invalid/empty paths, `/dev/full`, export windows, watch/dashboard timeouts) | 0 tracebacks / 0 unexpected exit codes |
| 200 random INI files through `load_config` | 0 unexpected exceptions (typos warned as designed) |
| 19 malformed/edge HTTP requests (unbalanced brackets, `%ZZ`, negative/NaN windows, bad/missing Host, unknown methods) | 0 server-side errors; expected 200/400/404/421/503 only |
| daemon (300 samples, 10 ms cadence) + dashboard hammered (120 iterations × 5 endpoints) + CLI export every 20 iterations | 0 errors, daemon exit 0, no traceback |
| `msi-psu-monitor-daemon --help` | now says "sample-loop passes (failed reads still count)" |

## 5. Not executed (do not count as PASS)

| Item | Status | Reason |
|---|---|---|
| Real MSI PSU read/write/alerts/VIN/black box/OCP/multirail | **BLOCKED** | no `/dev/hidraw*` in this environment |
| arm64 execution of the frozen binary | **BLOCKED** | CI builds `ubuntu-22.04-arm`; no arm64 machine/qemu here |
| root/systemd/udev install/start/uninstall on a real host | **BLOCKED** | no passwordless root; fake-tool namespace tests only |
| Desktop Chrome/Firefox dashboard run | **BLOCKED** | Playwright browser cache exists but the headless shell fails to start: `libnspr4.so` not installed. JS was executed under Node with a DOM stub instead (see §3). |
| 24 h / 72 h soak | **NOT RUN** | time budget; the 20 000-sample accelerated soak from Phase 3 remains the longest run |
| `promtool check metrics` (NR-001) | **NOT RUN** | `promtool` not installed and no package network access |
## 6. psu-file 对比轮（2026-10-19）

| Command | Result |
|---|---|
| `pytest -q` | **735 passed** (19.0 s) |
| `ruff check .` / `ruff format --check .` / `mypy msi_psu_monitor/` | clean / 58 formatted / clean |
| `bash scripts/smoke.sh` | **58 passed, 0 failed** (buzzer needle updated for DEF-032) |
| `coverage run --branch ...` + report | **92%** (2597 stmts, 190 missed; 882 branches) |
| browser execution | still BLOCKED (headless shell missing `libnspr4.so`); Node DOM harness covers the page JS |

Reference comparison itself is documented in
[docs/testing/psu-file-gap-analysis.md](../docs/testing/psu-file-gap-analysis.md).
## 7. Threshold/alert completion (2026-10-19)

| Command | Result |
|---|---|
| `pytest -q` | **735 passed** |
| `ruff check .` / `ruff format --check .` / `mypy msi_psu_monitor/` | clean |
| `coverage run --branch ...` + report | **92%** |
| `bash scripts/smoke.sh` | **58 passed, 0 failed** (demo values stay under the default limits) |
| threshold CLI demo (`[alerts] power_w = 50`) | exit 2, `ALERT [warning] power_high`, `Thresholds    : power_high` |
| daemon threshold sample | `msi_psu_threshold_alert`/`msi_psu_threshold_limit` in the textfile, edge logged in `alerts-*.log`, failed payload does not clear it |

Not executed: real-hardware threshold tuning (70 C/1200 W are REQ-14 initial values),
Prometheus rule file/promtool self-check (U-04), OCP write/dump-load (frozen), desktop
notification (explicitly not needed).
## 8. Ops/CLI polish (2026-10-19)

| Command | Result |
|---|---|
| `pytest -q` | **735 passed** |
| `ruff check .` / `ruff format --check .` / `mypy msi_psu_monitor/` | clean |
| `coverage run --branch ...` + report | **92%** |
| `bash scripts/smoke.sh` | **58 passed, 0 failed** |
| `msi-psu-monitor --dump-config` / `... -f json` | effective thresholds printed, no PSU access, no side effects |
| `-f prometheus` | canonical `metric{} value`; both energy counter names |
| `docs/prometheus-rules.yml` | syntax/structure checked statically; `promtool check metrics/rules` still NOT RUN (no binary/network) |

Hardware-kit self-test after the polish round: `acceptance.sh --demo` with
`MSI_PSU_MONITOR`/`MSI_PSU_DAEMON` pointing at the venv =
**30 PASS / 0 FAIL / 3 MANUAL / 2 SKIP** (was 26 PASS), including the new local-threshold
check (`power_w = 1` → exit 2 / `power_high` / `Thresholds`) and
`--dump-config`. DEMO is a harness self-test, not real hardware.
## 9. Hardware OCP threshold write + handshake retry (2026-10-19)

| Command | Result |
|---|---|
| `pytest -q` | **735 passed** |
| `ruff check .` / `ruff format --check .` / `mypy msi_psu_monitor/` | clean |
| `coverage run --branch ...` + report | **93%** (2957 stmts, 195 missed, 1084 branches) |
| `bash scripts/smoke.sh` | **58 passed, 0 failed** |
| `MSI_PSU_DEMO=1 ... --dump-thresholds -f json` / `--ocp-set` / `--load-thresholds` | demo path writes/reads back; idempotent re-apply; unsupported model exit 1 |
| 50k-sample accelerated soak (demo, 5 ms) | exit 0; peak RSS 16.4 MB; fd=3 at end; state dir 28 KB |
| real-PSU OCP write + power-cycle persistence | NOT RUN -- requires hardware (bench acceptance) |
| `promtool check metrics/rules` | NOT RUN -- replaced by the strict exposition test, not claimed as promtool |

## 10. Reliability/release close-out (2026-10-19)

| Command | Result |
|---|---|
| `pytest -q` (venv Python 3.12.3) | **735 passed** |
| `pytest -q` (bare Python 3.13.15, uv-managed, pytest only) | **735 passed** |
| `bash scripts/soak.sh 5000` | SOAK PASS: 5000 samples, peak RSS 16440 KB, fd=3, state dir 32K |
| 50k local accelerated soak | exit 0, peak RSS 16.4 MB, fd=3, no state corruption |
| `coverage report --fail-under=90` | **93%** (2957 stmts, 195 missed, 1084 branches) |
| `bash scripts/smoke.sh` | **58 passed, 0 failed** |
| frozen-binary local rebuild (ALLOW_NEWER_GLIBC=1) + binary .deb + hardware kit | CLI/daemon build + smoke, binary .deb Depends = libc6/zlib1g, kit demo **30 PASS** |
| real PSU / arm64 / root-systemd / browser / 24h | NOT RUN / BLOCKED |
