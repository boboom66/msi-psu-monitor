# LEDGER

Append-only task table. `UNKNOWN` is not `PASS`.

| Task | Title | Model | Status | Commit | Evidence | Review | Notes |
|---|---|---|---|---|---|---|---|
| T-001 | Preserve work, fix exec bits, create worktree | G/F | **DONE** | `6a0191f` | `EVIDENCE/T-001/commands.txt` | self-checked | 29 files preserved; `scripts/install.sh` 100644→100755; worktree at `../msi-psu-product-v2` |
| T-002 | Run baseline gates in Linux | F | **BLOCKED** | — | `EVIDENCE/T-002/blocked.md` | — | No WSL/Docker/`uv`; `gh` unauthenticated; only `compileall`/`diff --check` ran |
| T-003 | Create progress ledgers | F | **DONE** | 209a135 | this directory | self-checked | `STATE`/`LEDGER`/`DECISIONS`/`APPROVALS`/`BASELINE`/`EVIDENCE` |
| T-004 | Fix docs baseline drift | F | **DONE** | 209a135 | `git diff` | self-checked | Current docs no longer hard-code 859; historical 803/645 snapshots preserved with notes |
| T-005 | CI check for exec bits and LF | F | **DONE** | 209a135 | `EVIDENCE/T-005/ci-check.md` | self-checked | New step in `.github/workflows/ci.yml`; not executed yet (needs CI) |
| T-006 | Add `docs/agent-progress` to docs index | F | **DONE** | 209a135 | `AGENTS.md` link | self-checked | Agent progress path documented |
| T-007 | Inventory current user-added features | F | **DONE** | 209a135 | `BASELINE.md` | self-checked | `--dashboard-text`, `--menu`, watch redraw, tests, docs |
| T-008 | Phase 0 report / G0 request | G | **DONE** | 209a135 | `PHASE_0_REPORT.md`, `APPROVALS.md` | self-checked | Awaiting human G0 |
| T-009 | Freeze baseline tag/branch | G | **DONE** | freeze commit | `BASELINE_FREEZE.md` | self-checked | `baseline-2026-10-26` / `baseline/pre-product-v2`; not a release |
| T-010 | Baseline feature test matrix | G/F | **DONE** | freeze commit | `BASELINE_TEST_PLAN.md` | self-checked | 40+ cases; execution blocked on Linux |
| T-011 | Run baseline gates via fork CI | F | **PASS** | `a21f971` | `BASELINE_TEST_REPORT.md`; run `40290163974` | CI | 3.10/3.12/3.13 + freeze all green |
| T-012 | Create green baseline tag r2 | G | **DONE** | `a21f971` | `baseline-2026-10-26-r2` | self-checked | r1 failed docs consistency (stale 645 quote); r2 fixed docs only |
| T-013 | Feature portfolio / G1 proposal | G | **DONE** | pending | `FEATURE_PORTFOLIO.md` | self-checked | 30 features; 5 themes; 5 G1 questions |
| T-014 | Rename buzzer flag to `--buzzer-toggle` | F | **DONE** | `7f01604` | `monitor.py`, tests, README, CHANGELOG | CI | Primary name; `--buzzer-off` hidden alias; 2 new tests; docs count 861 |
| T-015 | Verify buzzer rename in CI | F | **PASS** | `7f01604` | run `40291862435` | CI | 3.10/3.12/3.13 + freeze all green |
| T-016 | termdash: colour-width box + safe truncation | F | **DONE** | `ffb158f` | `termdash.py`, 4 new tests | CI run `40294017182` PASS | Box aligned by visible width; header/rows cut without splitting escapes |
| T-017 | menu: `?` help, `0` quit, alert-log entry, dynamic footer | F | **DONE** | `ffb158f` | `menu.py`, 5 new tests | CI run `40294017182` PASS | `?` was decoded but ignored; alert log runs locally (no hidraw) |
| T-018 | Intermediate CI failures fixed | F | **DONE** | `41a31a3`→`ffb158f` | runs `40293264056`, `40293672414` | CI | ruff format + stale doc count 861→870 + wrong header-line assertion |
| T-019 | Web dashboard live badge | F | **DONE** | `ac33e89` | `dashboard.py` + harness test | CI run `40425289154` PASS | `● live` / `○ not updating` after 10 missed 1s polls; history keeps serving |
| T-020 | PTY evidence for `--watch`/`--dashboard-text` | F | **DONE** | `195c7d8` | `tests/test_pty_watch.py` | CI run `40425289154` PASS | 4 PTY tests on Linux; SIGTERM path; found+fixed a real cursor-restore gap (`e453c3f`) |
| T-021 | Naming/units matrix | G | **DONE** | `ac33e89` | `NAMING_MATRIX.md` | self-checked | No blocking inconsistency; 5 gaps recorded for G2 |
| T-022 | menu: grouped interactive rework | F | **DONE** | `5ecf8c3` | `menu.py`, `test_menu.py` (+15), README/verify/CHANGELOG/ledgers | self-checked | App-cursor arrows (ESC O), Esc/help semantics, header status line, alt-screen lifecycle, NO_COLOR, scroll+resize, thresholds entry, lazy device open. MIT audit: simple-term-menu/console-menu/pick/PyTermGUI licence files verified; prompt_toolkit (BSD-3) and urwid (LGPL-2.1) excluded; route A+ — stdlib-only refactor, no runtime dep. Windows gates green; Linux gates via fork CI |

## Next (user-feature polish, continuing)

- T-022 menu interactive rework — **done** (this commit); CI evidence pending.
- Design cards for OCP dry-run/backup/restore, `--doctor`, `--list`; then G2.

- Human approved the portfolio with “开始”; G1 is treated as approved.
- Next: design cards for OCP dry-run/backup/restore, `--doctor`, `--list`;
  then G2.
- Then implementation, one feature per ticket.
