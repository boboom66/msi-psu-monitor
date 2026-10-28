# STATE

- Phase: **Phase 2 — user-added feature polish (TUI/menu/dashboard/watch)**
- Task: **Menu UX/width/stability pass done; G2 review next**
- Branch: `work/product-v2`
- HEAD: `78d6730` on `work/product-v2` (CI run #64 green)
- Baseline tag: `baseline-2026-10-26-r2`
- Package version: `1.0.1`
- Tests: **980 tests / 34 test modules**, per the latest recorded CI run
- Last code gates: CI run `40618427581` (#64) on `78d6730` — **PASS**
  (980 collected; ruff/format/mypy/shellcheck/pytest/coverage 91%/smoke/soak/
  deb/freeze on 3.10/3.12/3.13). Linux VM deep re-run: 972 ok, 2 environment
  skips (dashboard JS needed Node, install namespace needs root; both passed
  after installing Node / running as root). Coverage 91%.
  Earlier green: ci#63 `40617596738` (978-case baseline).
- Documentation checks: relative links checked in 22 changed Markdown files; `git diff --check` clean
- Local test limitation: Windows cannot collect the full Linux suite (`fcntl`, `termios`,
  and `os.geteuid` are unavailable); this is not counted as a project test failure
- Environment: clean Ubuntu VM (not WSL) is the authoritative runtime; the Windows
  host is for editing only; fork GitHub Actions runs the unattended gates
- Master: kept unchanged; Product v2 work remains on `work/product-v2`
- Preserved work: `wip/pre-agent-2026-10-26` @ `6a0191f`
- Next: hardware acceptance using `docs/hardware-acceptance.md` and `docs/verify.md`
  §8 (0x2C/0x11/fallback included); then G2 review
- Blockers: hardware acceptance, real OCP write, arm64 execution, real root/systemd/udev,
  real desktop-browser verification, and 24 h / 72 h soak remain unverified
- Updated: 2026-10-27
