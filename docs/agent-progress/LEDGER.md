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

## Next (G1)

- Human approves/edits `FEATURE_PORTFOLIO.md`.
- Then Phase 2 design cards for the approved P0/P1 items.
- Then Phase 3 implementation, one feature per ticket.
