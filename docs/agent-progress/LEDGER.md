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

## Next (blocked on G0)

- T-101 Feature inventory (G)
- T-102 Journey friction (G)
- T-103 Reference survey (G/F)
- T-104 UI evidence pack (F)
- T-105 Error message inventory (F)
- T-106 Naming/units matrix (F)
- T-107 Help/docs consistency (F)
- T-108 Phase 1 report / G1 (G)
