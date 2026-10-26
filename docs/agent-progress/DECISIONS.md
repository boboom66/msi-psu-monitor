# DECISIONS

ADR-style log. Context → Decision → Consequence.

## D-001 — Preserve user work before Product v2

- Context: `master` had 32 modified files, 7 untracked feature files, and 11
  shell scripts showing a working-tree mode change. A product review must not
  discard or silently "clean" this work.
- Decision: commit the current tree on `wip/pre-agent-2026-10-26` (`6a0191f`),
  keep `master` clean at `ca8a6d5`, and create `work/product-v2` from the
  preserved commit in a sibling worktree.
- Consequence: the user's work is recoverable; all Product v2 changes happen on
  `work/product-v2`; `master` stays releasable.

## D-002 — Fix shell-script executable bits

- Context: the working tree showed `100755 → 100644` for 11 scripts because the
  repo was checked out on Windows with `core.filemode=true`. Separately,
  `scripts/install.sh` was `100644` in the index, so a Linux checkout would not
  make it executable even though the docs say `sudo ./scripts/install.sh`.
- Decision: set `core.filemode=false` locally; mark every tracked
  `scripts/*.sh` and `scripts/hardware/*.sh` as `100755` in the index; add a CI
  guard for modes and LF.
- Consequence: `scripts/install.sh` is now executable; CI will catch a future
  Windows checkout that strips the bit.

## D-003 — Baseline gates are BLOCKED, not passed

- Context: this host has no WSL distro, no Docker, no `uv`, and `gh` is not
  authenticated. The package imports `fcntl`/`termios`, so it cannot run its
  test suite natively on Windows. The checked-in `.venv` is a Linux venv and
  cannot run here.
- Decision: do **not** claim pytest/ruff/mypy/smoke/soak pass. Record them as
  `BLOCKED`; run only `python -m compileall` and `git diff --check` as partial
  static checks.
- Consequence: Phase 0 stops at G0 until the human enables one Linux execution
  path (WSL2, fork GitHub Actions, or an SSH host).

## D-004 — Docs counts: current docs avoid hard-coding, history stays history

- Context: current docs claimed 803 and 859 tests; `docs/testing/` contains a
  645-test historical snapshot. The real count cannot be measured until G0.
- Decision: current verification instructions say "run `pytest -q` for the
  current count"; the 2026-10-22 release-readiness snapshot keeps 803 with an
  explicit "snapshot" note; historical files keep their dated numbers.
- Consequence: no false current claim; after G0, `BASELINE.md` and `STATE.md`
  record the measured count.

## D-005 — CI guard for script modes and line endings

- Context: the executable-bit loss is invisible in a diff and broke the
  user-facing install path.
- Decision: add a `Shell script modes and line endings` step to the `check` job
  in `.github/workflows/ci.yml`, before dependency installation.
- Consequence: a bad mode or CRLF fails fast on every push/PR.

## D-006 — Model routing: G/F, with Q only as escalation

- Context: the user requested GLM-5.3-Flash as the main model, DeepSeek V4.1
  Flash for implementation, and Qwen3.8 Flash only when capability is
  insufficient.
- Decision: `G = opencode-go/glm-5.3-flash` (orchestrator/design/review),
  `F = opencode-go/deepseek-v4.1-flash` (implementation/tests/docs),
  `Q = opencode-go/qwen3.8-flash` (escalation only; ≤3/phase, ≤10 total,
  recorded in this file).
- Consequence: Q cannot become a default; every escalation is auditable.

## D-007 — Session works in the integration worktree

- Context: switching the original worktree back to `master` changed the loaded
  AGENTS.md to the older pre-feature version.
- Decision: move the session to
  `C:\Users\timzhang\Desktop\project\msi-psu-product-v2`, which carries the
  preserved feature work and the newer AGENTS.md.
- Consequence: subsequent reads/edits use the Product v2 tree; the original
  repository remains on `master`.
