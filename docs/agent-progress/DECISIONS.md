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

- Context: current docs claimed 803 and 859 tests; `docs/archive/testing/` contains a
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

## D-008 — Freeze a test snapshot before improving

- Context: the user asked to fix the version, test the implemented features, and
  only then improve.
- Decision: create annotated tag `baseline-2026-10-26` and branch
  `baseline/pre-product-v2` on the freeze commit. Keep `pyproject.toml` at
  `1.0.1`; this is a test snapshot, not a release. Do not create a `v*` tag.
- Consequence: tests reference an immutable commit; improvements happen on
  `work/product-v2`; the release version is chosen after the test report.

## D-009 — Test before improve; red baseline blocks improvements

- Context: changing code before measuring the existing features would make
  failures ambiguous.
- Decision: run `BASELINE_TEST_PLAN.md` on the frozen snapshot. If the baseline
  is RED, fix baseline defects with regression tests first. If AMBER, record
  known blockers and proceed. Improvements start only after the baseline report.
- Consequence: every later improvement has a clean "before" reference.

## D-010 — CI path: push works, log reading needs auth

- Context: `git push --dry-run fork work/product-v2` succeeds even though
  `gh auth status` reports no login; the unauthenticated Actions API is rate
  limited.
- Decision: pushing the branch to `fork` is allowed for CI; do not extract
  tokens from Git Credential Manager. Reading full CI logs requires the human to
  run `gh auth login` (Gate G0/B). Until then, use the public badge/HTML status
  and record `UNKNOWN` for log-level evidence.
- Consequence: CI can be triggered now; debugging a failure may require one
  human auth step.

## D-011 — Use public CI annotations for failure diagnosis

- Context: full job logs require authentication, but public check-run
  annotations and the run HTML are readable.
- Decision: add `::error` annotations for `FAILED`/`ERROR` pytest lines and a
  job-summary tail; use the public annotations API for diagnosis. Do not
  exfiltrate logs or tokens.
- Consequence: the first baseline failure was identified without `gh auth`;
  this CI diagnostic remains useful after release.

## D-012 — Baseline r1 failed docs consistency; r2 is green

- Context: the first freeze candidate (`d0d8d91`) failed
  `test_quoted_test_counts_are_accurate` because the new plan quoted a
  historical 645-test count as current.
- Decision: fix the quote (`a21f971`), keep r1 as the failed candidate, and tag
  `baseline-2026-10-26-r2` at the green commit. No product code changed.
- Consequence: the green baseline is r2; r1 remains a transparent record of the
  docs-only failure.

## D-013 — Baseline verdict: green automated, amber full matrix

- Context: CI run `40290163974` passed pytest/ruff/format/mypy/shellcheck/
  coverage/smoke/soak/deb on 3.10/3.12/3.13 and the freeze job. TUI visuals,
  dashboard states, five-model matrix, promtool, root install, hardware, arm64,
  and 24h remain unexecuted.
- Decision: treat the baseline as **GREEN for automated gates** and **AMBER for
  the full feature matrix**. Start Phase 1 with the known gaps listed in
  `BASELINE_TEST_REPORT.md`; do not claim release readiness.
- Consequence: improvements may start, but every later claim must cite the
  remaining evidence gaps.

## D-014 — `--menu` rework: refactor in place (route A+), no menu library

- Context: the user asked for the menu to be rebuilt with the polish of mature
  GitHub projects. Candidate libraries were researched from their PyPI sdists
  with licence files read verbatim: simple-term-menu 1.6.6, console-menu 0.8.0,
  pick 2.6.0 and PyTermGUI 7.8.1 are MIT; prompt_toolkit is BSD-3 and urwid is
  LGPL-2.1 (excluded); console-menu's dependency chain also includes
  Apache-2.0 ansiwrap and textual needs BSD-2 pygments. Every candidate is a
  runtime dependency, and this project is stdlib-only by contract
  (`tests/test_stdlib_only.py`, self-contained release binaries).
- Decision: route A+ — refactor the in-house menu (stdlib-only) while adopting
  the candidates' verified interaction design: application-cursor arrow keys,
  Esc semantics, a key legend, a status line, alternate-screen lifecycle,
  `NO_COLOR`, and short-terminal scrolling. Documented in `menu.py`'s module
  docstring; the licence audit lives in this decision.
- Consequence: no dependency chain to audit downstream, and the zero-runtime
  promise is testable as before. A `tests/test_menu.py` extension (+15 tests)
  locks the new behaviour; PTY-based assertions only run on Linux CI.

## D-015 — Runtime environment is a clean Ubuntu VM, not WSL

- Context: the project imports `fcntl`/`termios` and needs hidraw, systemd and udev,
  so it cannot run on the Windows host. Earlier phase documents listed WSL2 as the
  recommended local Linux path because no distro was installed on the host.
- Decision (user, 2026-10-27): the authoritative runtime is a **clean Ubuntu virtual
  machine** (VMware/VirtualBox/KVM). WSL is explicitly **not** used or supported:
  its USB passthrough is unreliable for hidraw, and systemd/udev/root installs
  cannot be validated there. The Windows host keeps only editing duties
  (ruff/mypy plus the POSIX-free test subset); fork GitHub Actions stays the
  unattended Linux runner.
- Consequence: any `.venv` found inside this tree is a VM artifact that was synced
  back. It must be rebuilt inside the VM (`uv sync --group dev`) and never reused;
  `docs/machine-setup.md` now leads with the VM path, with physical installs as a
  side note.

## D-016 — Documentation consolidation: one home per fact, dated material archived

- Context: the tree carried a Phase 2 execution plan, a v1.0.0 command/output
  preview, Phase 5 audit snapshots in `bug-audit/`, a historical `docs/testing/`
  folder and live ledgers side by side, with several cross-references to each
  other and two duplicate fix/release records. Readers could not tell which
  document was current, and the docs-consistency gate only scans `docs/*.md`,
  so stale snapshots inside scanned files were a recurring failure source.
- Decision: keep current facts in one place each (README = behavior,
  protocol.md = registers, verify.md = gates, requirements-traceability.md =
  requirement mapping, bug-audit/RELEASE_READINESS.md = verdict,
  agent-progress/STATE.md = live status). Move pure snapshots
  (`新增功能指令与预览.md`, Phase 5 `CODE_AUDIT.md`/`TEST_REPORT.md`) into
  `docs/archive/` with banners and fixed relative links. Keep `docs/testing/`
  as the labelled historical test record, and mark its `fix-log.md` /
  `release-readiness.md` as superseded by the `bug-audit/` ledgers instead of
  deleting content that still has Phase 3 evidence. `docs/README.md` gains the
  short maintenance rules; `AGENT_MASTER_PLAN.md` gains a status banner pointing
  at STATE/LEDGER so its startup-phase sections are not read as current.
- Consequence: no document is both historical and untagged; nothing was deleted
  without a duplicate/archive record; links were re-checked with a local
  markdown link scan (0 dangling). Future snapshots have a defined home.

## D-017 — Archive the whole dated test-record folder

- Context: D-016 kept `docs/testing/` in place as a labelled historical folder.
  The owner asked for the cleanest possible tree, and the same repository's
  `master` line already archived its test records. Live references (verify.md,
  bug-audit, BASELINE) pointed into that folder, so the move had to be
  link-complete rather than a rename.
- Decision: move `docs/testing/` to `docs/archive/testing/` wholesale, keep its
  own README as the historical index, and update every path in current documents
  (verify.md, bug-audit README/BUG_TRACKER/FIX_LOG, docs/README, BASELINE,
  DECISIONS, review playbook). No test evidence was deleted.
- Consequence: `docs/` now contains only current product/operations documents
  plus the process folder `agent-progress/`; every dated snapshot lives under
  `docs/archive/`. A local markdown link scan reports zero dangling links.
- Addendum (same pass): the two process documents that sat next to product docs
  (`AGENT_MASTER_PLAN.md`, `agent-product-review-playbook.md`) moved into
  `docs/agent-progress/`, so `docs/` now holds only product/operations documents,
  process state lives in `agent-progress/`, and dated snapshots live in
  `archive/`. Both remain referenced (README index, APPROVALS gates, plan read
  order) with their new paths.
