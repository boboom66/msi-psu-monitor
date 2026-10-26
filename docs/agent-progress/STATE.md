# STATE

- Phase: **Baseline freeze / feature test**
- Task: **T-010 — Baseline test matrix**
- Branch: `work/product-v2`
- HEAD: `git log -1` on `work/product-v2` (Phase 0 work: `209a135`)
- Baseline tag: `baseline-2026-10-26`
- Baseline branch: `baseline/pre-product-v2`
- Package version: `1.0.1` (not bumped before testing)
- Master: `ca8a6d5` (clean; original worktree)
- Preserved work: `wip/pre-agent-2026-10-26` @ `6a0191f`
- Environment: Windows host; **no WSL distro, no Docker, no `uv`**;
  `gh` installed but not authenticated; Python 3.12.10 available for
  `compileall` only. Linux gates are **BLOCKED**.
- Last gates: `python -m compileall -q msi_psu_monitor tests` → exit 0;
  `git diff --check` → exit 0. Full pytest/ruff/mypy/smoke/soak → **not run**.
- Q escalations: **0/3 this phase, 0/10 total**
- Next: run `BASELINE_TEST_PLAN.md` B-01..B-09 in Linux, then the feature
  matrix; write `BASELINE_TEST_REPORT.md`.
- Blockers:
  - B-101: no Linux runtime → cannot run the real test suite or build artifacts.
  - B-102: `gh` unauthenticated → `git push` works, but CI logs cannot be read
    with `gh run view`; only badge/HTML until auth.
  - B-103: hardware evidence (5 models, OCP write, root install, arm64, 24h)
    remains with the human at G3/G5.
- Updated: 2026-10-26
