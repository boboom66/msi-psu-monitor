# APPROVALS

Human gates from `docs/AGENT_MASTER_PLAN.md` §9.

## G0 — Baseline and environment — **SATISFIED for automated gates via CI**

### Result (2026-10-26)

- Green baseline: `baseline-2026-10-26-r2` @ `a21f971`.
- CI run `40290163974`: all jobs green (Python 3.10/3.12/3.13 + freeze).
- Automated gates: pytest, ruff, format, mypy, shellcheck, coverage, smoke,
  soak, `.deb`, binaries, no-Python proof, clean-env `--once`.
- Full feature matrix is **AMBER**: TUI visuals, dashboard states, five-model
  matrix, root install, hardware, arm64, 24h remain unexecuted.
- The CI path is usable without `gh auth` for pass/fail and annotations; full
  job logs still need `gh auth login` for deep debugging.
- WSL is now optional (for local TUI/PTY captures), not required for the
  automated gates.

### Original decision (kept for history)

### What is already done

- User work preserved on `wip/pre-agent-2026-10-26` (`6a0191f`).
- Clean `master` at `ca8a6d5`.
- Integration worktree: `C:\Users\timzhang\Desktop\project\msi-psu-product-v2`
  on `work/product-v2`.
- Shell scripts marked `100755`; `scripts/install.sh` fixed from `100644`.
- Progress ledgers created.
- Current docs no longer hard-code a test count; historical snapshots marked.
- CI guard added for script modes/LF.
- Partial static checks: `compileall` and `git diff --check` pass.

### Baseline freeze and test matrix (added after G0 draft)

- Baseline tag: `baseline-2026-10-26`
- Baseline branch: `baseline/pre-product-v2`
- Package version: `1.0.1` (not bumped; test snapshot, not a release)
- Test plan: `BASELINE_TEST_PLAN.md` (40+ cases)
- `git push --dry-run fork work/product-v2` **succeeds** even though
  `gh auth status` reports no login. CI can be triggered; reading full logs
  still needs `gh auth login`.

### What is blocked

Full Linux gates cannot run on this host:

- `wsl.exe -l -v` → no distribution installed.
- `docker --version` → not found.
- `uv --version` → not found.
- `gh auth status` → not logged in.
- The checked-in `.venv` is a Linux venv; the package imports `fcntl`/`termios`.

### Decision needed

Choose **one** Linux execution path:

| Option | Command / action | Best for | Trade-off |
|---|---|---|---|
| **A. WSL2 + Ubuntu 22.04** (recommended) | `wsl --install -d Ubuntu-22.04` (admin + reboot), then `uv sync --group dev` | Fast local loop; TUI captures | One-time install/reboot |
| **B. GitHub Actions on the fork** | `gh auth login`, then push `work/product-v2` to `fork` | Fully unattended gates/packaging | Needs auth; TUI capture is extra work |
| **C. SSH Linux host** | provide host/user/key | Real systemd/udev testing | Requires a machine |
| **D. Static-only** | no action | Docs/design work only | Gates stay BLOCKED; cannot release |

**Recommendation:** A for interactive UX work, or B if you want the agent to run
unattended. A and B can be combined.

### If approved, the agent will

1. Run the baseline gates in the chosen environment and record the real test
   count/coverage.
2. Start Phase 1: feature inventory, journey friction, reference survey, UI
   evidence pack.
3. Stop at G1 with the Keep/Improve/Replace/Remove proposal.

### Reply format

```text
G0: A
```
or
```text
G0: B
```
or
```text
G0: C <host>
```
or
```text
G0: D (static only; gates stay BLOCKED)
```
