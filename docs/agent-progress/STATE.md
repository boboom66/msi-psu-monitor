# STATE

- Phase: **Baseline tested — automated gates green**
- Task: **T-011 — Baseline test report**
- Branch: `work/product-v2`
- HEAD: `git log -1` on `work/product-v2` (green baseline: `a21f971`)
- Baseline tag: `baseline-2026-10-26-r2`
- Baseline branch: `baseline/pre-product-v2-r2`
- Candidate tag (failed docs check): `baseline-2026-10-26` @ `d0d8d91`
- Package version: `1.0.1` (not bumped before testing)
- Master: `ca8a6d5` (clean; original worktree)
- Preserved work: `wip/pre-agent-2026-10-26` @ `6a0191f`
- Environment: GitHub Actions Linux for gates; Windows host for editing.
- Last gates: CI run `40290163974` — **PASS** on Python 3.10/3.12/3.13
  (ruff/format/mypy/shellcheck/pytest/coverage/smoke/soak/deb) and freeze
  (binaries/deb/no-Python/clean-env). `compileall` + `diff --check` local PASS.
- Q escalations: **0/3 this phase, 0/10 total**
- Next: Phase 1 — feature inventory, journey friction, reference survey,
  UI evidence pack (PTY + dashboard screenshots); stop at G1.
- Blockers:
  - B-101: no local Linux runtime; CI is the gate runner.
  - B-102: `gh` unauthenticated; public API/HTML used for CI evidence, full
    logs still require auth for deep debugging.
  - B-103: hardware evidence (5 models, OCP write, root install, arm64, 24h)
    remains with the human at G3/G5.
- Updated: 2026-10-26
