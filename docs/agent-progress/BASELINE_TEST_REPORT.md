# BASELINE TEST REPORT — 2026-10-26

## Identity

| Item | Value |
|---|---|
| Green tag | `baseline-2026-10-26-r2` |
| Green branch | `baseline/pre-product-v2-r2` |
| Green commit | `a21f971a40772516ab538a600a1906f1ff0ba090` |
| Candidate tag (failed docs check) | `baseline-2026-10-26` @ `d0d8d91` |
| Package version | `1.0.1` (not bumped; test snapshot) |
| CI run | [`40290163974`](https://github.com/boboom66/msi-psu-monitor/actions/runs/40290163974) |
| Environment | GitHub Actions `ubuntu-latest` × Python 3.10/3.12/3.13; `ubuntu-22.04` freeze job |

## Why there are two tags

The first candidate (`d0d8d91`, tag `baseline-2026-10-26`) failed
`tests/test_docs_consistency.py::test_quoted_test_counts_are_accurate`:

```text
docs/AGENT_MASTER_PLAN.md: says 645, actual 859
```

The new planning document quoted a historical 645-test count as if it were
current. The fix (`a21f971`) removes that quote; **no product code changed**.
The r1 tag is kept as the failed candidate; `r2` is the green baseline.

## CI result — all jobs green

| Job | Result | Key steps |
|---|---|---|
| `check (3.10)` | **SUCCESS** | 19 steps, 0 non-success |
| `check (3.12)` | **SUCCESS** | 19 steps, 0 non-success |
| `check (3.13)` | **SUCCESS** | 19 steps, 0 non-success |
| `freeze` | **SUCCESS** | 13 steps, 0 non-success |

Every `check` job passed, in order:

1. `Shell script modes and line endings` (new T-005 guard)
2. `Ruff (lint)`
3. `Ruff (format)`
4. `Mypy`
5. `Shellcheck`
6. `Pytest` — **PASS**; docs-consistency collected **859** tests
7. `Coverage (branch)` — **PASS** (≥90%)
8. `Smoke test (no hardware)` — **PASS** (58 checks)
9. `Soak (5k accelerated samples)` — **PASS**
10. `Build the .deb` — **PASS**

The `freeze` job passed:

- Build self-contained binaries (PyInstaller onefile).
- Build zero-Python `.deb`.
- Prove the binary needs no `python3`/`pip`.
- Clean-env `--once`.
- Upload release artifacts.

## Feature coverage at this baseline

The automated suite and `scripts/smoke.sh` cover the following feature groups.
Status is deliberately conservative.

| Test-plan group | Status | Evidence |
|---|---|---|
| B-01..B-09 automated gates | **PASS** | CI run: pytest/ruff/format/mypy/shellcheck/coverage/smoke/soak |
| B-10..B-16 acquisition (text/JSON/prometheus/watch) | **PASS (automated)** / **PARTIAL (TTY)** | smoke + pytest; interactive TTY redraw not captured |
| B-20..B-22 terminal dashboard/menu | **PARTIAL** | unit tests pass; no 80x24/120x40 PTY capture yet |
| B-23..B-25 web dashboard/stale/security | **PARTIAL** | HTTP smoke + unit tests; visual states not captured |
| B-30..B-35 export/alerts/alert log | **PASS (automated)** | smoke + pytest; alert-log UX not manually walked |
| B-40..B-47 OCP/black box | **PASS (automated)** | smoke covers TS/MEG/Ai1600T OCP and black box |
| B-50..B-55 control writes | **PASS (demo)** | smoke covers fan, Zero Fan, buzzer; rail path needs a dedicated check |
| B-60..B-64 daemon/Prometheus | **PASS (automated)** / **PARTIAL (promtool)** | daemon+prom+history in smoke; strict parser in pytest; official promtool not run in CI |
| B-70..B-74 five-model demo matrix | **PARTIAL** | smoke covers TS, MEG P, Ai1600T; ai1000p/ai1300ts need explicit runs |
| B-80..B-86 errors/security | **PARTIAL** | usage conflicts and alert paths in smoke; Host/CSP/HEAD need dedicated assertions |
| B-90..B-92 packaging | **PASS** | smoke `.deb` modes; freeze binaries/deb/no-Python |
| B-93..B-94 install/upgrade (root) | **BLOCKED** | no root host in this baseline |
| B-95..B-98 24h/hardware/OCP bench/arm64 | **BLOCKED** | human/hardware evidence required |

## Verdict

**BASELINE GREEN for automated gates**, **AMBER for the full feature matrix**.

What is proven:

- The frozen commit builds, lints, type-checks, tests, smokes, soaks, and
  packages on Python 3.10/3.12/3.13.
- The user-added features are in the tested tree: `--dashboard-text`,
  `--menu`, watch redraw, local thresholds, OCP write, live dashboard
  aliases, and the new tests.
- The script executable-bit guard works on Linux.
- The binary/deb path has no Python dependency.

What is not proven:

- TUI/menu visual behavior at 80x24/120x40 (unit tests only).
- Dashboard visual empty/stale/error states and responsive layout.
- Full five-model demo matrix (some models covered by smoke, not all explicitly).
- Official `promtool` on the current textfile (strict parser passes).
- Real root install, systemd/udev, upgrade/uninstall.
- Real hardware, OCP bench write, arm64 execution, 24h soak.

These become the known gaps for Phase 1/4/7/9. They are **not** failures of the
baseline; they are unexecuted evidence.

## Next

1. Freeze remains `baseline-2026-10-26-r2`.
2. Start Phase 1: feature inventory, journey friction, reference survey, UI
   evidence pack (PTY + dashboard screenshots).
3. Do not change product code until the Phase 1 review identifies what to
   improve; baseline defects found later get a regression test first.
