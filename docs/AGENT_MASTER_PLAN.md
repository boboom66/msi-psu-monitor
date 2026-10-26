# AGENT MASTER PLAN — msi-psu-monitor Product v2

> **READ THIS ENTIRE FILE BEFORE DOING ANYTHING.**
> You are the **orchestrator** (GLM-5.3-Flash). The human is the **supervisor**.
> Your job is to **execute**, not to ask permission for every step.
> If this file conflicts with `AGENTS.md` or `msi_psu_monitor/AGENTS.md`, the
> AGENTS.md invariants win. Stop and record the conflict in `DECISIONS.md`.

---

## 0. Read order and first actions

### 0.1 Read order (do not skip)

1. This file.
2. `AGENTS.md`
3. `msi_psu_monitor/AGENTS.md`
4. `docs/agent-product-review-playbook.md`
5. `README.md`
6. `docs/verify.md`
7. `docs/protocol.md`
8. `docs/requirements-traceability.md`
9. `pyproject.toml`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`
10. The files for the current task only.

Do **not** dump the whole repository into one context. Read by slice.

### 0.2 First 15 actions (in order)

1. `git status --short`, `git branch --show-current`, `git log -1 --format='%H %ad %s' --date=short`.
2. `git remote -v` — confirm `origin` is upstream and `fork` is `boboom66/msi-psu-monitor`.
3. `gh auth status` — if not logged in, this is a **Gate G0** prerequisite.
4. `wsl.exe -l -v`, `docker --version`, `uv --version` — determine the Linux execution path.
5. Create `docs/agent-progress/` with `STATE.md`, `LEDGER.md`, `DECISIONS.md`, `APPROVALS.md`, `EVIDENCE/`.
6. Save the current dirty-tree evidence: `git status --porcelain`, `git diff --stat`, `git diff > docs/agent-progress/baseline.patch`.
7. Preserve the user's uncommitted work exactly as described in §4.2. Do not discard it.
8. Create the integration branch/worktree (`work/product-v2`) as described in §4.2.
9. Fix the shell-script executable-bit issue and add a CI check (T-001/T-005).
10. Run the baseline gates in a Linux environment (§4.3). Record the real test count.
11. Write `docs/agent-progress/STATE.md` and the first `LEDGER.md` rows.
12. Start **Phase 0**. Do not stop after planning.
13. At the end of Phase 0, write the Phase Report and stop at **Gate G0** only.
14. After human approval, continue through Phases 1–8 without asking “shall I continue?”.
15. Stop only at a human gate (§9) or a STOP condition (§3.8).

### 0.3 Autonomy contract

- **Proceed automatically** through reversible code, test, docs, and CI changes that pass all gates.
- **Do not ask** “should I do X?” for reversible, in-scope work. Decide, record the decision in `DECISIONS.md`, and continue.
- **Stop and request approval** only for the gates in §9 and the conditions in §3.8.
- **Never** claim a gate passed if you did not run it. `UNKNOWN` is not `PASS`.
- **Never** mark hardware, arm64, root/systemd/udev, or 24h soak as `PASS` without evidence.
- **Never** stop after producing a plan. The next action after planning is execution.
- **Update the ledger before ending any turn.** If context runs out, the next session must be able to resume from `STATE.md`.

---

## 1. Mission and definition of done

### 1.1 Product goal

A Linux userspace package for MSI PSUs that:

- a **new user** can install and use in **5 minutes**;
- a **sysadmin** can run **24/7** with systemd and Prometheus;
- a **hardware reviewer** can trust for **OCP / fan / rail writes**;
- a **support engineer** can diagnose from `--doctor` and a diagnostics bundle;
- a **maintainer** can extend without a rewrite.

### 1.2 Personas

| ID | Persona | Primary jobs |
|---|---|---|
| A | New homelab user | Install, see readings, understand alerts, try without hardware |
| B | Sysadmin (20 machines) | Daemon, Prometheus, upgrade, rollback, remote diagnosis |
| C | Hardware reviewer | Validate 12V-2x6 OCP, write/restore thresholds, capture evidence |
| D | Maintainer/support | Reproduce bugs, add models, keep docs/CI green |

### 1.3 Product Definition of Done

A release is **SHIP** only when all are true:

- [ ] 0 open P0/P1 defects and 0 open P0/P1 UX problems.
- [ ] Journeys J1–J6 (§1.4) pass on a clean Ubuntu 22.04/24.04 install.
- [ ] First reading ≤ 5 minutes from README, without reading source.
- [ ] Every error message answers: what happened / why / next command.
- [ ] Every write has dry-run, confirmation (or `--yes`), read-back, and a recovery path.
- [ ] OCP threshold write is bench-validated with dump → write → read-back → power-cycle → restore.
- [ ] All 5 models have real-hardware acceptance evidence.
- [ ] 24h soak on a real host (or a documented, approved substitute).
- [ ] Clean install, upgrade, downgrade (if supported), uninstall, purge leave no residue.
- [ ] `promtool` passes; naming warnings are fixed or recorded as accepted debt.
- [ ] Docs, `--help`, screenshots, and version match the release commit.
- [ ] Release artifacts are checksummed, SBOM'd, and the binary `.deb` has no Python dependency.
- [ ] Human supervisor signs the hardware evidence and approves the tag.

### 1.4 User journeys

| ID | Journey | Success condition |
|---|---|---|
| J1 | Install → first reading | ≤5 min; one clear next step at each failure |
| J2 | Daily monitoring | TUI/Web/Prometheus show fresh data; stale state is obvious |
| J3 | Alert → diagnose → recover | Message includes measured vs limit and next command |
| J4 | Change setting → verify → undo | Dry-run, diff, read-back, restore |
| J5 | Export/report | CSV/JSON with stable headers, units, timezone |
| J6 | Upgrade/uninstall | Config/state preserved; no residue |

### 1.5 Non-goals

- No rewrite of the working protocol/state/daemon core.
- No new runtime dependencies; stdlib only.
- No kernel-module work (`kernel/` is out of scope).
- No GUI framework, no browser framework, no CDN assets.
- No cloud, telemetry, accounts, or auto-update.
- No Windows support.
- No automatic PSU writes from the daemon.
- No feature that exists only to increase the flag count.

### 1.6 Quality attributes

Correctness, safety, usability, reliability, security, compatibility, maintainability, supportability.

---

## 2. Current baseline (verify; do not trust blindly)

### 2.1 Repository facts (as of 2026-10-26)

| Item | Value |
|---|---|
| Repo | `C:\Users\timzhang\Desktop\project\msi-psu-monitor` |
| Branch / commit | `master` @ `ca8a6d5` |
| Version | `1.0.1` (`pyproject.toml`) |
| Remotes | `origin` = upstream `HesiPullupTimbo/msi-psu-monitor`; `fork` = `boboom66/msi-psu-monitor` |
| CI | Python 3.10/3.12/3.13; smoke; soak; `.deb`; 22.04 freeze; arm64 release matrix |
| Package policy | stdlib-only runtime; `Development Status :: 4 - Beta` |
| Lint/type baseline | ruff `select = ["E","F"]`; mypy `strict = false` |
| Windows host | No WSL distro, no Docker, no `uv`; `.venv` is a Linux venv (broken on Windows) |
| GitHub CLI | `gh` 2.99.0 installed, **not authenticated** |

### 2.2 Known issues to fix first

| ID | Issue | Impact | Priority |
|---|---|---|---|
| B-001 | 32 files dirty, +501/−62 | Audit baseline is not reproducible | P0 |
| B-002 | 11 `scripts/*.sh` show `100755 → 100644`; `core.filemode=true` | A careless `git add -A` ships non-executable installers | P0 |
| B-003 | Docs quote conflicting test counts | Agent may quote stale facts | P1 |
| B-004 | OCP threshold write never touched real hardware | Safety-critical evidence missing | P0 (human) |
| B-005 | Root/systemd/udev install not run on a real host | Install path unproven | P0 (human) |
| B-006 | arm64 built in CI, not executed | Runtime unproven | P1 (human) |
| B-007 | 24h/72h soak not run | Long-run reliability unproven | P1 (human) |
| B-008 | Prometheus naming-policy warnings | Compatibility debt undecided | P2 |
| B-009 | `Development Status :: 4 - Beta`; ruff/mypy relaxed | “Product-level” not encoded | P2 |
| B-010 | Flat 25+ flag CLI | Discoverability risk | P1 |

### 2.3 Starting hypotheses (verify, do not assume)

Full list in `docs/agent-product-review-playbook.md` §8. Top 10:

1. Flat flags make `--help` hard to scan.
2. `--buzzer-off` is a toggle; the name misleads.
3. `--fan-mode performance` is an alias for `auto`; concept duplication.
4. No `--list`/`--device`; multi-PSU discovery is guesswork.
5. No `--doctor`; permission/udev/state failures produce tracebacks.
6. `--ocp-set` lacks dry-run/backup/restore guidance.
7. `--menu` / `--dashboard-text` / `--watch` overlap.
8. Dashboard empty/stale/daemon-stopped states may be unclear.
9. Alert copy may lack measured vs limit / next action.
10. Exit code `2` means both alert and usage error.

### 2.4 What not to assume

- Docs are not current truth; code and tests are.
- Demo/mock is not hardware evidence.
- 94% coverage is not test strength.
- CI green is not product-ready.
- A green unit test is not a completed user journey.

---

## 3. Operating model

### 3.1 Roles

| Role | Who | Owns |
|---|---|---|
| Orchestrator | GLM-5.3-Flash (main session) | Plan, design, triage, final judgment, ledger |
| Implementer | DeepSeek V4.1 Flash (subagent) | Bounded code/tests/docs tasks |
| Independent reviewer | GLM-5.3-Flash (fresh subagent) | PASS/FAIL/UNKNOWN on a diff |
| Escalation reviewer | Qwen3.8 Flash (fresh subagent, ≤3/phase) | Blocked P0 / tie-breaker |
| Human supervisor | User | Gates G0–G5, hardware evidence, release approval |

### 3.2 Model routing

Use the `subagent` tool with exact model IDs:

| Task class | Model ID | Session |
|---|---|---|
| Orchestration, product/UX decisions, protocol/security design | `opencode-go/glm-5.3-flash` | main |
| Independent review / usability acceptance | `opencode-go/glm-5.3-flash` | fresh subagent |
| Implementation, tests, docs, inventories, screenshots | `opencode-go/deepseek-v4.1-flash` | subagent |
| Read-only exploration | `opencode-go/deepseek-v4.1-flash` (`explore`) | subagent |
| High-risk implementation (OCP write, daemon lifecycle) | GLM-5.3-Flash implements or line-reviews; human approves | main |
| Escalation / tie-breaker (sparingly; see §3.2.1) | `opencode-go/qwen3.8-flash` | fresh subagent |

Shorthand used in the phase/feature tables: **G** = `opencode-go/glm-5.3-flash`;
**F** = `opencode-go/deepseek-v4.1-flash`; **Q** = `opencode-go/qwen3.8-flash`
(escalation only, §3.2.1).

Rules:

- The implementer **never** approves its own work.
- The reviewer gets only the task card, diff, and evidence — not the author’s reasoning.
- If model selection fails, record `MODEL UNAVAILABLE` and use a fresh session; do not silently substitute.
- One subagent = one task. Do not let a subagent “also fix” adjacent issues.
- The orchestrator must inspect the diff and run gates; never trust a subagent’s self-report.

### 3.2.1 Escalation policy — Qwen3.8 Flash (Q)

Q is an **exception**, not a default. Use it only when at least one is true:

1. G or F has failed the same task twice, with evidence.
2. A P0 protocol/safety/security decision is blocked by conflicting G/F conclusions.
3. A cross-module synthesis or refactor exceeds G’s context or capability.
4. An independent tie-breaker is required at a release gate.

Budget and rules:

- **≤3 Q calls per phase; ≤10 total** for the whole plan.
- Record every call in `DECISIONS.md`: reason, task, prompt, output summary,
  why G/F was insufficient, and the result.
- Q never approves its own work; if Q implements, G reviews.
- Q cannot override `AGENTS.md` invariants, human gates, or the non-goals.
- Do not use Q for routine implementation, docs, formatting, inventories, or screenshots.
- If Q also fails, STOP and escalate to the human; do not loop.

### 3.3 Session and task rules

- One task per session/subagent; max **400 changed lines or 5 files** before splitting.
- Design sessions: no code. Implementation sessions: no design changes.
- Fresh context for review and usability acceptance.
- Keep prompts self-contained: role, task ID, scope, inputs, acceptance, evidence rules, output format, stop conditions.
- If a subagent fails twice, the orchestrator takes over, then escalates to Q (§3.2.1), then to the human.

### 3.4 Git, worktree, branch, commit

- Do **not** work directly on `master`.
- Integration branch: `work/product-v2`; worktree: sibling directory.
- One commit per task; conventional commits (`fix:`, `feat:`, `docs:`, `test:`, `chore:`).
- No force-push, no history rewrite, no tag without approval.
- Push only to `fork` (`boboom66/msi-psu-monitor`); never push to `origin`.
- Keep `master` clean and releasable.
- Before every commit: `git diff --check`, `git status --short`, ensure no secrets/artifacts.

### 3.5 Progress ledgers

Create and maintain:

```
docs/agent-progress/
  STATE.md          # current phase/task/branch/commit/next/blockers
  LEDGER.md         # append-only task table
  DECISIONS.md      # ADR-style decisions
  APPROVALS.md      # human gate requests and responses
  EVIDENCE/         # per-task logs, screenshots, command output
```

`STATE.md` fields: phase, task, branch, HEAD, environment, gates last run, next task, blockers.

`LEDGER.md` columns: task, title, model, status, commit, files, tests, evidence, review, notes.

### 3.6 Evidence rules

| Level | Meaning |
|---|---|
| E0 | Claimed in docs |
| E1 | Code path exists |
| E2 | Automated test passes |
| E3 | Fault injection / clean environment / soak passes |
| E4 | Real hardware or real root host evidence |

- Every finding: `file:line` or command + output.
- Every fix: failing test → passing test, plus the gate command.
- Every UX claim: actual output or screenshot.
- `UNKNOWN` ≠ `PASS`.
- Do not fabricate output. If not run, say “not run”.

### 3.7 Anti-cheating rules

- Do not delete, skip, xfail, or weaken tests to make a gate pass.
- Do not edit CI to ignore a failure.
- Do not mock the function under test.
- Do not change expected values without a spec citation.
- Do not add runtime dependencies.
- Do not hide errors behind bare `except Exception: pass`.
- Do not treat demo/mock as hardware evidence.
- Do not claim arm64/24h/root/hardware without evidence.
- Do not rewrite the working core to avoid understanding it.

### 3.8 STOP and escalation conditions

Stop, write an `APPROVAL REQUEST` (§9.2), and wait when:

1. Protocol/spec ambiguity affects behavior.
2. A real PSU write is required.
3. A breaking change to CLI/JSON/CSV/exit codes/Prometheus names is proposed.
4. A runtime dependency or non-stdlib import is proposed.
5. Security/privacy impact is unclear.
6. The task needs hardware, arm64, root, or 24h evidence.
7. The diff exceeds 400 lines / 5 files.
8. Two consecutive attempts fail.
9. The worktree contains unexpected changes.
10. Instructions conflict.

### 3.9 Human gates

| Gate | When | Human decides |
|---|---|---|
| G0 | End of Phase 0 | Baseline/worktree/environment acceptable |
| G1 | End of Phase 1 | Feature portfolio: Keep/Improve/Replace/Remove |
| G2 | End of Phase 2 | UX contracts, breaking changes, scope |
| G3 | Before any real PSU write | Write commands, backup, rollback |
| G4 | Before release tag | Artifacts, evidence, release notes |
| G5 | After hardware acceptance | Sign hardware evidence |

Everything else is autonomous.

### 3.10 Autonomy loop

```
read STATE.md / LEDGER.md / DECISIONS.md
verify git status and HEAD
while not release_done:
    task = first task not DONE/BLOCKED
    if task.gate: write APPROVAL REQUEST; stop
    if task.model == F:
        spawn DeepSeek subagent with task card; wait
    else:
        execute as GLM-5.3-Flash (or spawn fresh GLM-5.3-Flash reviewer)
    run task gates
    if fail: fix or split; retry max 2; else STOP
    independent review (author != reviewer)
    commit
    update LEDGER/STATE
    if phase complete: write PHASE REPORT; continue unless gate
```

Do not ask “shall I continue?” after each task.

---

## 4. Environment bootstrap

### 4.1 Windows host reality

The current host has:

- no WSL distro, no Docker, no `uv`;
- a Linux `.venv` that cannot run on Windows;
- `gh` installed but not authenticated.

The project imports `fcntl`/`termios`; it will not run natively on Windows. Choose one:

| Option | When | Setup |
|---|---|---|
| A. WSL2 + Ubuntu | Best local loop, TUI captures | `wsl --install -d Ubuntu-22.04`, then `uv sync --group dev` |
| B. GitHub Actions on fork | No local Linux; fully automatable | `gh auth login`; push branches to `fork`; `gh run watch` |
| C. SSH Linux host | You already have one | configure `~/.ssh/config`; run commands remotely |

If none is available, stop at **G0**. Static edits are allowed; gates are `BLOCKED`; no claims of pass.

### 4.2 Preserve current work (do this first)

```bash
git config core.filemode false          # Windows only: stop mode-noise
git update-index --chmod=+x scripts/*.sh scripts/hardware/*.sh
git status --porcelain > docs/agent-progress/baseline-status.txt
git diff > docs/agent-progress/baseline.patch
git diff --stat > docs/agent-progress/baseline-stat.txt
git switch -c wip/pre-agent-2026-10-26
git add -A
git commit -m "wip: preserve user changes before product v2"
git worktree add ../msi-psu-product-v2 -b work/product-v2 wip/pre-agent-2026-10-26
```

- The integration branch is based on `wip/pre-agent-2026-10-26`, **not** `master`,
  so the user's uncommitted features (`--dashboard-text`, `--menu`, etc.) are included.
- Keep `master` clean; merge `work/product-v2` only after G4 approval.
- Do not discard `.omo/`, `.opencode/`, `dist/`, `build/`, or `.venv/`.
- Verify `git ls-files -s scripts/*.sh` shows `100755`.
- Work only in the new worktree.

### 4.3 Baseline gates (Linux)

```bash
uv sync --group dev
uv run --group dev ruff check .
uv run --group dev ruff format --check .
uv run --group dev mypy msi_psu_monitor/
uv run --group dev pytest -q
uv run --group dev coverage run --branch -m pytest -q
uv run --group dev coverage report --fail-under=90
bash scripts/smoke.sh
bash scripts/soak.sh 5000
shellcheck -S warning scripts/*.sh scripts/hardware/*.sh
```

Record the real test count, coverage, HEAD, OS, Python, and timestamp in `STATE.md`.

If using GitHub Actions:

```bash
git push fork work/product-v2
gh run list --repo boboom66/msi-psu-monitor --branch work/product-v2
gh run watch <run-id> --repo boboom66/msi-psu-monitor
gh run view <run-id> --repo boboom66/msi-psu-monitor --log
```

Batch commits per task group; push once per group to conserve CI minutes.

### 4.4 Screenshots and TUI captures

- Web: headless Chromium/Playwright at 320/768/1920; normal, empty, stale, daemon-stopped, deleted `latest.json`.
- TUI: PTY capture at 80x24 and 120x40; `script`/`tmux`/`asciinema`.
- Store under `docs/agent-progress/EVIDENCE/<task>/` and reference in the ledger.
- Never let a model design UI from imagination; feed it the actual capture.

### 4.5 Hardware lab

- The agent prepares the kit, commands, and evidence template.
- The human runs it on a Linux machine with the PSU.
- The agent analyzes the returned tarball; no PASS without it.
- Never run OCP/fan/rail writes on real hardware without G3.

---

## 5. Phase plan and task backlog

### Phase 0 — Baseline stabilization

| Task | Title | Model | Acceptance |
|---|---|---|---|
| T-001 | Preserve work, fix exec bits, create worktree | F | `git status` clean; scripts `100755` |
| T-002 | Run baseline gates in Linux; record truth | F | Gates output saved; count/coverage recorded |
| T-003 | Create progress ledgers and templates | F | Files exist; STATE filled |
| T-004 | Fix docs baseline drift (conflicting counts) | F | No hard-coded test counts; release doc current |
| T-005 | CI check for exec bits and LF | F | CI fails on `100644` scripts / CRLF |
| T-006 | Add `docs/agent-progress` to docs index | F | Linked from README/AGENTS |
| T-007 | Inventory current uncommitted features | F | List of user-added features and docs |
| T-008 | Phase 0 report | G | Report + G0 approval request |

**Gate G0** after T-008.

### Phase 1 — Discovery

| Task | Title | Model | Acceptance |
|---|---|---|---|
| T-101 | Feature inventory (P0 prompt) | G | Feature Cards for F-01..F-30 |
| T-102 | Journey friction (3 personas × 6 journeys) | G | Friction table with evidence |
| T-103 | Reference survey | G/F | 5+ references per major feature; license notes |
| T-104 | UI evidence pack | F | Screenshots/terminal captures stored |
| T-105 | Error message inventory | F | All errors classified actionable/cryptic |
| T-106 | Naming/units matrix | F | text/JSON/CSV/Prometheus/TUI/Web compared |
| T-107 | Help/docs consistency | F | Hidden/undocumented/mismatched flags |
| T-108 | Phase 1 report | G | Report + G1 approval request |

**Gate G1** after T-108: approve Keep/Improve/Replace/Remove.

### Phase 2 — Design

| Task | Title | Model | Acceptance |
|---|---|---|---|
| T-201 | CLI grammar and grouped help | G | Design card; backward compatibility |
| T-202 | Error message and exit-code contract | G | Format + table + migration |
| T-203 | Write-safety UX (OCP/fan/rail) | G | Dry-run/confirm/read-back/restore |
| T-204 | TUI/menu/dashboard roles | G | One primary live view; no duplication |
| T-205 | Naming/units/JSON schema | G | Matrix + compatibility rules |
| T-206 | Install/onboarding design | G | 5-minute journey |
| T-207 | Feature specs F-01..F-30 | G | Each with acceptance tasks |
| T-208 | Phase 2 report | G | Report + G2 approval request |

**Gate G2** after T-208: approve contracts and breaking changes.

### Phase 3 — Core UX implementation

| Task | Title | Model | Acceptance |
|---|---|---|---|
| T-301 | Grouped `--help` + examples (no flag removal) | F | 30-second find test; all flags documented |
| T-302 | Error message overhaul (top 20) | F | What/why/next for each |
| T-303 | `--list` / `--device` discovery | F | Table; `--serial` still works |
| T-304 | `--doctor` | F | PASS/WARN/FAIL + next steps |
| T-305 | `--once` output polish + JSON schema version | F | Golden tests; backward compatible |
| T-306 | `--watch` JSONL + cursor restore | F | Pipe test; SIGINT test |
| T-307 | `--export --to`, stdout, timezone, columns | F | Golden CSV; old files load |
| T-308 | `--show-alert-log` / `--show-log` filters | F | `--since`, `--limit`, `--json` |
| T-309 | Alert message format | F | measured/limit/source/next |
| T-310 | Tests for T-301..T-309 | F | New tests fail before, pass after |
| T-311 | Independent review | G | PASS/FAIL/UNKNOWN |
| T-312 | Phase 3 report | G | Evidence + continue |

### Phase 4 — Safety and control UX

| Task | Title | Model | Acceptance |
|---|---|---|---|
| T-401 | `--buzzer-toggle` + alias + wording | F | Deprecation warning; never “off” |
| T-402 | Fan mode/duty consistency + dry-run | F | Read-back; idempotence |
| T-403 | Zero Fan UX + dry-run | F | Model gate; read-back |
| T-404 | Rail mode UX + dry-run | F | Model gate; read-back |
| T-405 | OCP dry-run/diff | G/F | Current vs proposed; no write |
| T-406 | OCP backup/restore | G/F | Restore file; read-back |
| T-407 | OCP confirmation/`--yes`/non-TTY | G/F | No accidental write |
| T-408 | OCP bench checklist + kit | G | Human-runnable; evidence template |
| T-409 | Tests for T-401..T-407 | F | Mock + safety paths |
| T-410 | Independent review | G | PASS/FAIL/UNKNOWN |
| T-411 | Phase 4 report | G | G3 approval request |

**Gate G3** before any real PSU write.

### Phase 5 — Observability and UI

| Task | Title | Model | Acceptance |
|---|---|---|---|
| T-501 | Dashboard states/banner/time range/responsive | F | Empty/stale/error screenshots |
| T-502 | `/api/live` 503 JSON + tests | F | No frozen chart |
| T-503 | TUI layout/keybindings/pause/help/resize | F | 80x24/120x40 captures |
| T-504 | Menu role/breadcrumb/non-TTY | F | Scripted session |
| T-505 | Prometheus naming/`info`/`up`/rules | G/F | promtool; decisions |
| T-506 | UI evidence pack | F | All states captured |
| T-507 | Tests for T-501..T-505 | F | New tests |
| T-508 | Independent review | G | PASS/FAIL/UNKNOWN |
| T-509 | Phase 5 report | G | Continue |

### Phase 6 — Reliability and security

| Task | Title | Model | Acceptance |
|---|---|---|---|
| T-601 | Fault injection: unplug/short read/NAK/clock/disk/permissions | F | Tests + fixes |
| T-602 | Daemon lifecycle/signal/flock/rescan | F | Tests + soak |
| T-603 | Dashboard security (Host/CSP/HEAD/DoS) | F | Tests |
| T-604 | Untrusted string/fuzz tests | F | No injection/NaN |
| T-605 | 24h soak plan/script | F/L | Script + evidence template |
| T-606 | Threat model update | G | Document |
| T-607 | Fix findings | F | Tests |
| T-608 | Independent review | G | PASS/FAIL/UNKNOWN |
| T-609 | Phase 6 report | G | Continue |

### Phase 7 — Packaging, docs, support

| Task | Title | Model | Acceptance |
|---|---|---|---|
| T-701 | README rewrite/quick start/screenshots | G/F | 5-minute test |
| T-702 | Install/uninstall dry-run/upgrade | F | Clean Ubuntu 22.04/24.04 |
| T-703 | Man page / shell completions (optional) | F | Packaged if added |
| T-704 | `--diagnostics` bundle | F | Redacted; support-ready |
| T-705 | Issue template/troubleshooting | F | `--doctor` output requested |
| T-706 | Docs consistency/link check | F | No drift |
| T-707 | Clean install test | F | Evidence |
| T-708 | Independent review | G | PASS/FAIL/UNKNOWN |
| T-709 | Phase 7 report | G | Continue |

### Phase 8 — Release gate

| Task | Title | Model | Acceptance |
|---|---|---|---|
| T-801 | Full gate matrix | F/L | Evidence table |
| T-802 | Artifacts/checksums/SBOM/no Python | F | Verified |
| T-803 | Release notes/CHANGELOG/version | F | Tag matches pyproject |
| T-804 | Final review | G | SHIP / NOT READY |
| T-805 | Phase 8 report | G | G4 approval request |

**Gate G4** before tag/release.

### Phase 9 — Hardware acceptance

| Task | Title | Model | Acceptance |
|---|---|---|---|
| T-901 | Prepare kit/checklist | G | Human-runnable |
| T-902 | Human runs 5 models | Human | Evidence tarball |
| T-903 | Analyze evidence, file bugs | G | Bug list |
| T-904 | Re-test after fixes | F | Evidence |
| T-905 | Update readiness | G | E4 evidence |
| T-906 | Final sign-off | Human | G5 |

**Gate G5** after hardware evidence.

---

## 6. Feature backlog

Priorities: P0 safety/release, P1 core UX, P2 polish, P3 optional. Model: G design/review, F implement.

| ID | Feature | Current problem | Target | Acceptance | Priority | Model |
|---|---|---|---|---|---|---|
| F-01 | CLI entry/help | Flat 25+ flags | Grouped help, examples, `--list`, `--doctor` | 30s find test | P1 | G/F |
| F-02 | Device discovery | `--serial` only | `--list` table, `--device`, safe default | Multi-device tests | P1 | G/F |
| F-03 | One-shot text | Dense, inconsistent labels | Stable labels/units, clear status | Golden output | P1 | F |
| F-04 | JSON output | No schema version | Add `schema_version`, keep fields | Schema test | P2 | F |
| F-05 | Watch/live text | Text only; cursor risk | JSONL option; restore cursor | PTY/SIGINT tests | P1 | F |
| F-06 | TUI `--dashboard-text` | Overlap; unclear keys | Header/footer, pause/help, resize | 80x24/120x40 captures | P1 | G/F |
| F-07 | Menu `--menu` | Duplicates dashboard | Launcher role, breadcrumbs, non-TTY | Scripted session | P2 | F |
| F-08 | Web dashboard | Empty/stale states unclear | Banner, time range, responsive | State screenshots | P1 | G/F |
| F-09 | History/export | No `--to`; timezone unclear | `--to`, stdout, stable CSV | Golden CSV | P1 | F |
| F-10 | Alert engine | Good core | Actionable copy, recovery | State tests | P1 | F |
| F-11 | Local thresholds | Units/defaults unclear | Document + validate + export | Config tests | P1 | F |
| F-12 | Alert log viewer | No filters | `--since`, `--limit`, `--json` | CLI tests | P2 | F |
| F-13 | Fan control | Flat flags | Consistent verbs, dry-run | Read-back tests | P1 | F |
| F-14 | Zero Fan | Model gate unclear | Explain, dry-run, read-back | Tests | P1 | F |
| F-15 | Buzzer | `--buzzer-off` toggles | Rename `--buzzer-toggle`; alias | Tests + docs | P1 | F |
| F-16 | Multirail | Flat flag | Show current, dry-run | Tests | P1 | F |
| F-17 | OCP read/dump | Good | Clear table/units/JSON | Tests | P1 | F |
| F-18 | OCP write/restore | No dry-run/backup UX | Dry-run, backup, restore, confirm | Bench + tests | P0 | G/F |
| F-19 | Black box | No filters | `--limit`, `--json`, empty state | Tests | P2 | F |
| F-20 | Daemon lifecycle | Good core | `--doctor`, startup log, graceful stop | Fault tests | P1 | F |
| F-21 | Prometheus | Naming warnings | Decide/fix; `info`/`up`; rules | promtool | P1 | G/F |
| F-22 | Config | Unknown keys silent | Validate, `--doctor`, source in dump | Config tests | P1 | F |
| F-23 | systemd/udev/install | Root path unproven | Dry-run, post-install check, uninstall | Clean host | P1 | F |
| F-24 | Packaging | Good | Man page/completions optional; checksums | Packaging tests | P1 | F |
| F-25 | Demo | Env var only | `--demo` alias; clear labeling | Tests | P2 | F |
| F-26 | Diagnostics | Missing | `--doctor`, `--diagnostics` bundle | Tests | P1 | F |
| F-27 | Version/rollback | Basic | Build info, rollback docs | Docs | P2 | F |
| F-28 | README/quick start | 24KB, long | 5-minute quick start, screenshots | Timed test | P1 | G/F |
| F-29 | Accessibility | Partial | NO_COLOR, 80x24, 320px, no color-only | Checks | P2 | F |
| F-30 | Support | Basic | Issue template, troubleshooting, bundle | Docs | P2 | F |

MoSCoW:

- **Must**: F-01, F-02, F-03, F-05, F-06, F-08, F-09, F-10, F-11, F-13..F-18, F-20..F-24, F-26, F-28.
- **Should**: F-04, F-07, F-12, F-19, F-25, F-27, F-29, F-30.
- **Could**: man page, completions, localization, themes, Grafana dashboard.
- **Won't**: kernel module, GUI framework, cloud/telemetry, auto-update, Windows, automatic writes.

---

## 7. UX contracts

These are **targets**. Phase 2 design cards may adjust them with evidence; record the decision.

### 7.1 CLI grammar

- Keep existing flags as aliases; do not remove them in v2.
- Group `--help` into: Monitor, Watch/TUI, Export/History, Alerts, Control, OCP, Service, Diagnostics, Config/Output.
- Add `--list`, `--device`, `--doctor`, `--dry-run`, `--yes`, `--to`, `--json` alias.
- Do **not** introduce subcommands in v2; revisit in v3 with migration.
- Examples section with 8 copy-paste commands.

### 7.2 Help layout

```
usage: ...
MSI PSU Monitor — read sensors from MSI PSUs via USB HID

Monitor:      --once, --watch, --format, --output, --serial, --device, --list
Watch/TUI:    --dashboard-text, --menu
Export:       --export, --from, --to, --columns
Alerts:       --no-alerts, --show-alert-log
Control:      --fan-mode, --fan-duty, --zero-fan, --buzzer-toggle, --set-rail
OCP:          --ocp, --dump-thresholds, --ocp-set, --load-thresholds, --show-log
Service:      --config, --dump-config, --doctor
Diagnostics:  --verbose, --quiet, --version

Examples:
  ...
Notes:
  ...
```

### 7.3 Naming and units

- Build the matrix from code; keep existing JSON/CSV/Prometheus keys and add aliases if renaming.
- Text labels may be human-friendly; machine keys are stable.
- Units: V, A, W, %, °C, RPM, kWh, s.
- Decimal places: V/A 3, W 1, % 2, RPM integer.
- Timestamps: ISO 8601 with timezone in JSON/CSV; local time in TTY with offset.

### 7.4 Error message format

```
<what failed>
  Cause: <why>
  Next: <command>
```

- CLI errors → stderr, exit 1.
- Usage errors → argparse usage + exit 2 (v2; document ambiguity).
- `--verbose` may add traceback; default no traceback.
- Never leak secrets or raw serials in logs.

### 7.5 Exit codes

- 0 OK, 1 error, 2 alert **or** usage (v2 compatibility).
- Document the ambiguity in README and `--help`.
- Do not change without G2 approval and a migration plan.
- JSON errors include `{"ok": false, "error": "...", "next": "..."}` where applicable.

### 7.6 Write safety pattern

Every write (`fan`, `zero-fan`, `buzzer`, `rail`, `ocp-set`):

1. Validate model/range.
2. `--dry-run`: show current vs proposed, registers/bytes, and the restore command; no write.
3. On TTY: confirmation prompt; `--yes` for non-interactive.
4. OCP: write a backup file before writing.
5. Write + F1h save.
6. Read back up to 3 attempts.
7. Print verified diff; on mismatch exit 1 and keep the backup.
8. Never write automatically from the daemon.
9. Audit log: mode/duty, verified, model, firmware; never serial.

### 7.7 TUI layout

- Header: model, serial, time, interval, daemon/demo marker.
- Body: voltages, currents, power, efficiency, temp, fan; per-pin table if width ≥100.
- Bars: width-based, not block-height glyphs.
- Footer: `q quit  p pause  ? help  r reset  +/- interval`.
- Colors + symbols; `NO_COLOR`, `TERM=dumb`, non-TTY fallback.
- Restore cursor/terminal on exit and signals.
- 80x24 minimum; resize redraw.

### 7.8 Web dashboard states

- Header: model, serial (or redacted), last update, daemon status.
- Banner:
  - No data: “No history yet. Start the daemon…”
  - Stale: “Daemon not updating (last sample …). Showing history.”
  - Error: “Cannot read latest.json: …”
- Time range 1h/6h/24h/7d; auto-refresh toggle.
- Chart legend: current/min/max; units.
- Responsive: 320/768/1920; one column at 320.
- Keyboard focus; color not sole signal.
- `/api/live` 503 with JSON reason.
- CSP/Permissions-Policy; Host 421; no CDN.

### 7.9 Alert format

```
ALERT [critical] ocp_pin3: Conn1 Pin3 current 9.8 A >= 8.0 A (hardware OCP)
  Next: reduce GPU load; run `msi-psu-monitor --ocp`; check `--show-alert-log`.
```

Recovery:

```
RECOVERED [critical] ocp_pin3: current back to 4.2 A.
```

JSON alert: `name`, `severity`, `source`, `measured`, `limit`, `unit`, `message`, `next`.

### 7.10 Config

- Precedence: CLI > file > defaults.
- `--dump-config` shows effective values and source.
- Unknown keys warn; invalid values error with key/line.
- `--doctor` validates config/state/permissions.
- UTF-8 (`utf-8-sig` read, `utf-8` write).

### 7.11 Accessibility

- `NO_COLOR`; `TERM=dumb`; non-TTY.
- 80x24; 320px.
- Color + label/symbol.
- Keyboard-only.
- No flashing.
- Locale-independent decimal points.

### 7.12 Onboarding

- README: 3-command quick start; supported hardware table; screenshot/GIF.
- “No PSU? Try demo.”
- `--doctor` first troubleshooting step.
- `--list` first device step.
- Docs link to detailed `docs/verify.md`.

---

## 8. Quality gates

### 8.1 Static

```bash
uv run --group dev ruff check .
uv run --group dev ruff format --check .
uv run --group dev mypy msi_psu_monitor/
shellcheck -S warning scripts/*.sh scripts/hardware/*.sh
```

### 8.2 Tests

```bash
uv run --group dev pytest -q
uv run --group dev coverage run --branch -m pytest -q
uv run --group dev coverage report --fail-under=90
```

Added requirements:

- New code: happy + empty + error + model-difference paths.
- Every fix: failing test first.
- No test deletion/skip/weakening.
- Critical constants: manual mutation check (`0xFE`, 250, 1000, 44, E1h bit order).

### 8.3 Dynamic

```bash
bash scripts/smoke.sh
bash scripts/soak.sh 5000
```

Plus:

- Fault injection: unplug, short read, NAK, clock jump, disk full, permission change, double daemon.
- Dashboard HTTP: 200/503/421/HEAD/CSP.
- TUI PTY: 80x24, 120x40, SIGINT, NO_COLOR.
- Export: old 9-column files, empty window, `--to`, stdout.

### 8.4 Security

- `systemd-analyze verify`; `systemd-analyze security`.
- `udevadm verify`.
- Dashboard Host/CSP/HEAD/XSS/path traversal.
- Untrusted device strings/log injection.
- No secrets; redacted diagnostics.
- SBOM; checksums; no Python in binary `.deb`.

### 8.5 Packaging

```bash
bash scripts/build_deb.sh
bash scripts/build_binary.sh
bash scripts/build_deb_binary.sh
bash scripts/build_hardware_kit.sh
```

- Clean-env `--once`.
- `dpkg-deb -c` modes; no `python3`/`pip` dependency.
- Install → start → sample → upgrade → uninstall → purge; no residue.
- Version single source; tag matches `pyproject.toml`.

### 8.6 Hardware

- 5 models × ident/sensors/alerts/VIN/black box.
- Fan/Zero Fan/buzzer/rail/OCP read.
- OCP write: dump → dry-run → write → read-back → power-cycle → restore.
- Unplug/replug; 24h soak.
- Evidence tarball; human signature.

### 8.7 Evidence table

| Gate | Command | Exit | Key output | HEAD | Env | Verdict |
|---|---|---|---|---|---|---|

`UNKNOWN` is not `PASS`. Any `FAIL`/`UNKNOWN` → `NOT READY`.

---

## 9. Human gates and approvals

### 9.1 Gate list

- **G0** baseline/worktree/environment.
- **G1** feature portfolio.
- **G2** UX contracts/breaking changes.
- **G3** real PSU write plan.
- **G4** release tag/artifacts.
- **G5** hardware evidence.

### 9.2 Approval request format

```
## APPROVAL REQUEST — G<N>
- Task/phase:
- Decision needed:
- Options (A/B/C):
- Recommendation:
- Risk:
- Rollback:
- Evidence:
- If approved, I will run:
```

Wait for the human. Do not proceed.

### 9.3 Do not ask

- “Should I fix this bug?” — fix it.
- “Should I add a test?” — add it.
- “Should I update docs?” — update them.
- “Should I continue?” — continue.
- “Which file?” — find it.

---

## 10. Reporting, ledger, resume

### 10.1 Task report

```
### TASK <id> — <title>
Status: DONE / BLOCKED / APPROVAL
Model: G/F
Commit:
Files:
Tests:
Evidence:
Review:
Notes:
```

### 10.2 Phase report

```
## PHASE REPORT — Phase <N>
- Branch/commit:
- Tasks completed:
- Gates:
- Evidence:
- Decisions:
- Q escalations:
- Open risks:
- Next:
```

### 10.3 STATE.md

```markdown
# STATE
- Phase:
- Task:
- Branch:
- HEAD:
- Environment:
- Last gates:
- Q escalations: <n>/3 this phase, <n>/10 total
- Next:
- Blockers:
- Updated:
```

### 10.4 Resume protocol

1. Read `STATE.md`, `LEDGER.md`, `DECISIONS.md`, `AGENTS.md`, this file.
2. `git status`, `git branch`, `git log -1`.
3. If dirty unexpectedly: stop and inspect.
4. Run the gate for the current task.
5. Continue from the first non-DONE task.
6. Do not redo DONE tasks.

---

## 11. Prompt library

Detailed P0–P6 prompts: `docs/agent-product-review-playbook.md`. Use these wrappers.

### 11.1 Orchestrator system prompt

```
You are the orchestrator for msi-psu-monitor Product v2.
Read AGENTS.md, msi_psu_monitor/AGENTS.md, docs/AGENT_MASTER_PLAN.md,
docs/agent-product-review-playbook.md, and the current task card.
Execute the next task. Do not stop after planning.
Use DeepSeek subagents for bounded implementation; use fresh GLM-5.3-Flash reviewers.
Use Qwen3.8 Flash only as a documented escalation (max 3/phase, §3.2.1).
Never claim a gate without evidence. Stop only at a human gate or STOP condition.
Update STATE/LEDGER before ending.
```

### 11.2 DeepSeek implementation prompt

```
You are implementing <TASK-ID> in <repo>, branch <branch>.
Read: AGENTS.md, this task card, and only these files: <list>.
Scope: only <files>. Non-goals: <list>.
Acceptance:
- <user task / expected output>
- <error states>
- <compatibility>
Process:
1. Add/update a test that fails on current HEAD; paste the failure.
2. Minimal implementation.
3. Do not delete/skip/weaken tests; no runtime deps; no PSU writes.
4. Run: <commands>; paste results.
5. Update --help/README/CHANGELOG if behavior changes.
If the root cause differs or the diff exceeds 400 lines/5 files, stop and report.
Output: root cause, diff summary, failing→passing output, risks, uncovered edges.
```

### 11.3 GLM-5.3-Flash design prompt

```
You are the product/UX designer. Do not write code.
Inputs: Feature Cards, Journey friction, reference survey, actual outputs/screenshots.
For each P0/P1 issue, produce a design card:
- current (evidence), target user/job
- option A (minimal, compatible) / option B (ideal, migration)
- before→after command/output examples
- interaction/keys/confirmation/error copy
- compatibility and deprecation
- acceptance tasks (3–5)
- effort/risk/dependencies
- decision: Keep/Improve/Replace/Remove
Prioritize now/next/later. Reduce concepts; allow deletion.
```

### 11.4 GLM-5.3-Flash reviewer prompt

```
You are the independent reviewer. You did not write this.
Inputs: task card, diff, test output, evidence.
Judge PASS/FAIL/UNKNOWN per acceptance. UNKNOWN is not PASS.
Check: test would fail without the fix; no mock-only assertions;
error/empty/model paths; compatibility; docs; security; diff scope.
Output: verdict, evidence, counterexample, required tests, merge yes/no.
Do not modify code.
```

### 11.5 Usability acceptance prompt

```
Run the 15 usability tasks from the playbook §P5 on <build>.
For each: expected, actual, PASS/FAIL/UNKNOWN, severity, fix.
Include: 5-minute install, no PSU, permission denied, unsupported model,
daemon stopped, stale dashboard, alert copy, fan/rail/OCP write safety,
export, upgrade, uninstall, TUI 80x24, Web 320/768/1920, --help findability,
copy-paste docs.
Verdict: SHIP / SHIP WITH KNOWN ISSUES / NOT READY.
```

### 11.6 Release gate prompt

```
Run the full matrix in §8. Record command/exit/output/HEAD/env.
Any FAIL/UNKNOWN -> NOT READY.
Check exec bits, LF, version single source, no Python in binary deb,
systemd/udev verify, promtool, SHA256SUMS/SBOM, install/upgrade/uninstall,
24h soak, hardware evidence.
Output: evidence table + verdict.
```

### 11.7 Red-team prompt

```
Assume the daemon fails within 24h. List 20 scenarios, P0–P3.
Each: injection, current behavior (file:line), expected, test gap, minimal fix.
Cover unplug during write, short read, NAK 0xFE payload, clock jump, disk full,
permission change, double daemon, dashboard slowloris, CRLF/BOM config,
serial with newline, 0xC0 model swap, state corruption, SIGTERM during atomic write,
fd exhaustion, huge history, LC_ALL=C, read-only FS, suspend/resume, USB reset,
firmware differences.
```

### 11.8 Reference survey prompt

```
For <feature>, compare 5 references. Output: project, license, 3 patterns,
how to adapt, risk. Clean-room only; no code copying; GPL projects patterns only.
```

---

## 12. Reference projects and licenses

| Project | What to learn | License |
|---|---|---|
| upstream `HesiPullupTimbo/msi-psu-monitor` | Behavior diff, protocol history | MIT (verify) |
| `liquidctl` | CLI grammar, device list, udev, install, tests | GPL-3.0 (verify) |
| `btop` | TUI layout, keys, responsive, color | Apache-2.0 (verify) |
| `nvtop` | GPU/实时 TUI, per-device view | GPL-3.0 (verify) |
| `s-tui` | Simple TUI, sensors | GPL-3.0 (verify) |
| `nmtui` / `raspi-config` | Menu grouping, breadcrumbs | GPL/LGPL (verify) |
| `netdata` | Web onboarding, stale banners, charts | GPL-3.0 (verify) |
| `Cockpit` | Web admin UX, empty/error states | LGPL-2.1 (verify) |
| `Glances` | Web/CLI monitoring, responsive | LGPL-3.0 (verify) |
| `node_exporter` | Prometheus naming, textfile, `up` | Apache-2.0 |
| `smartctl_exporter` | Disk metrics, labels | Apache-2.0 (verify) |
| `smartd` | Daemon, alerts, config, support | GPL-2.0 (verify) |
| `coolercontrol` | udev/systemd, hardware daemon, packaging | GPL-3.0 (verify) |
| `OpenRGB` | udev, device discovery, packaging | GPL-2.0 (verify) |
| `sar` / `vnstat` | History/export conventions | GPL (verify) |
| Debian Policy / lintian | Packaging correctness | — |
| systemd/udev docs | Sandboxing, device access | — |

**License rule:** this project is MIT. Only borrow patterns and UX ideas; never copy GPL code. Verify each LICENSE before use.

---

## 13. Appendix

### 13.1 Command cheat sheet

```bash
# Baseline
git status --short
git ls-files -s scripts/*.sh
uv sync --group dev
uv run --group dev pytest -q
uv run --group dev ruff check .
uv run --group dev ruff format --check .
uv run --group dev mypy msi_psu_monitor/
uv run --group dev coverage run --branch -m pytest -q
uv run --group dev coverage report --fail-under=90
bash scripts/smoke.sh
bash scripts/soak.sh 5000

# Demo UX
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --once
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --help
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --dashboard --port 8899
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --dashboard-text
MSI_PSU_DEMO=1 .venv/bin/msi-psu-monitor --menu

# GitHub Actions
gh auth login
git push fork work/product-v2
gh run list --repo boboom66/msi-psu-monitor --branch work/product-v2
gh run watch <run-id> --repo boboom66/msi-psu-monitor
gh run view <run-id> --repo boboom66/msi-psu-monitor --log
```

### 13.2 File map

| Path | Role |
|---|---|
| `msi_psu_monitor/protocol.py` | HID framing, registers, variants, writes, reads |
| `msi_psu_monitor/monitor.py` | CLI, validation, formatters, writes, export, dashboard |
| `msi_psu_monitor/state.py` | State, energy, history, alert log, export |
| `msi_psu_monitor/daemon.py` | Sample loop, Prometheus, rescan, prune |
| `msi_psu_monitor/dashboard.py` | Loopback HTTP dashboard |
| `msi_psu_monitor/termdash.py` | ANSI terminal dashboard |
| `msi_psu_monitor/menu.py` | Interactive menu |
| `msi_psu_monitor/alerts.py` | Alert engine, thresholds |
| `msi_psu_monitor/config.py` | INI config, precedence, limits |
| `msi_psu_monitor/demo.py` | Synthetic PSU |
| `tests/` | 30+ test modules |
| `scripts/` | Build, install, smoke, soak, hardware |
| `systemd/` | Unit + udev rule |
| `docs/` | Protocol, verify, support, release, testing |

### 13.3 Glossary

- **JTBD**: job to be done.
- **P0–P3**: severity/priority.
- **E0–E4**: evidence level.
- **DoD**: definition of done.
- **ADR**: architecture decision record.
- **HITL**: human in the loop.
- **G0–G5**: human gates.
- **G/F/Q**: GLM-5.3-Flash / DeepSeek V4.1 Flash / Qwen3.8 Flash (escalation only).

---

## 14. Final instruction to the orchestrator

Start now. Read the files in §0.1, execute §0.2, and continue until Gate G0.
Do not ask “shall I start?”. Do not stop after a plan. Update the ledger.
