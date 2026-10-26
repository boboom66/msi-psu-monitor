# PHASE 0 REPORT — Baseline stabilization

## Branch / commit

- Integration branch: `work/product-v2`
- Base: `wip/pre-agent-2026-10-26` @ `6a0191f`
- Phase 0 commit: the commit that adds this report (see `git log -1`)
- Original `master`: `ca8a6d5` (clean)

## Tasks completed

| Task | Status | Evidence |
|---|---|---|
| T-001 Preserve work, fix exec bits, create worktree | DONE | `EVIDENCE/T-001/commands.txt` |
| T-002 Baseline gates in Linux | **BLOCKED** | `EVIDENCE/T-002/blocked.md` |
| T-003 Progress ledgers | DONE | `STATE.md`, `LEDGER.md`, `DECISIONS.md`, `APPROVALS.md` |
| T-004 Docs baseline drift | DONE | `git diff`; current docs no longer hard-code 859 |
| T-005 CI guard for modes/LF | DONE (not executed) | `EVIDENCE/T-005/ci-check.md` |
| T-006 Docs index for agent progress | DONE | `AGENTS.md` link |
| T-007 User-added feature inventory | DONE | `BASELINE.md` |
| T-008 Phase 0 report / G0 | DONE | this file + `APPROVALS.md` |

## Gates

| Gate | Result | Note |
|---|---|---|
| `python -m compileall -q msi_psu_monitor tests` | PASS | Syntax only |
| `git diff --check` | PASS | Whitespace only |
| `pytest -q` | **NOT RUN** | No Linux runtime |
| `ruff check` / `format --check` | **NOT RUN** | No `uv`/ruff |
| `mypy` | **NOT RUN** | No mypy |
| coverage / smoke / soak | **NOT RUN** | No Linux runtime |
| packaging builds | **NOT RUN** | No Linux runtime |
| CI mode/LF step | **NOT RUN** | Requires CI |

No gate is claimed as passed beyond the two local static checks.

## Decisions

- D-001 preserve work on `wip/pre-agent-2026-10-26`.
- D-002 normalize shell-script modes; `scripts/install.sh` fixed.
- D-003 gates are BLOCKED, not passed.
- D-004 current docs avoid hard-coded test counts; history keeps dates.
- D-005 add CI mode/LF guard.
- D-006 model routing G/F/Q.
- D-007 session moved to the integration worktree.

## Blockers

1. **No Linux execution path.** No WSL distro, no Docker, no `uv`, and
   `gh` is unauthenticated. This blocks T-002 and all real gates.
2. Hardware evidence remains with the human: 5 models, OCP write, root
   install, arm64, 24h soak.

## What the human needs to do (G0)

Choose one:

- **A. WSL2 + Ubuntu 22.04** — best local loop.
  `wsl --install -d Ubuntu-22.04` (admin + reboot).
- **B. GitHub Actions** — `gh auth login`, then the agent pushes to `fork`.
- **C. SSH Linux host** — provide host/user.
- **D. Static-only** — gates stay BLOCKED; cannot release.

Reply `G0: A`, `G0: B`, `G0: C <host>`, or `G0: D`.

## Next after G0

1. Run the baseline gates and record the real test count/coverage.
2. Start Phase 1: feature inventory (F-01..F-30), journey friction, reference
   survey, UI evidence pack, error-message inventory, naming matrix.
3. Stop at G1 with the Keep/Improve/Replace/Remove proposal.

## Supervisor summary

The user's work is safe, the repository is cleanly split, and Phase 0 is
complete except for the Linux environment. The next action is a **human
environment choice**, not code. No production claim is made.
