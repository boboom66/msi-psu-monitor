# Agent progress and evidence

This directory is the durable memory for the Product v2 work. It is written for
both the human supervisor and the next agent session.

## Current

| File | Purpose |
|---|---|
| `STATE.md` | Current phase/task/branch/HEAD/blockers. Read this first when resuming. |
| `LEDGER.md` | Append-only task table: status, model, commit, tests, evidence, review. |
| `DECISIONS.md` | ADR-style decisions: context, decision, consequences. |
| `APPROVALS.md` | Human gate requests (G0–G5) and their responses. |
| `AUDIT_2026-10-27.md` | Independent audit: module inventory, verification matrix, residue. |
| `NAMING_MATRIX.md` | Naming/units reference for text/JSON/CSV/Prometheus/TUI/web. |
| `AGENT_MASTER_PLAN.md` | Execution plan and the G0–G5 gate definitions (status banner points at STATE/LEDGER). |
| `agent-product-review-playbook.md` | Review method and feature-decision checklist. |
| `EVIDENCE/` | Per-task command output, screenshots, logs. |

## Historical (frozen at the date in each file)

| File | Purpose |
|---|---|
| `BASELINE.md` | What the tree looked like before Product v2, including user-added features. |
| `PHASE_0_REPORT.md` | Phase 0 summary and G0 approval request. |
| `BASELINE_FREEZE.md`, `BASELINE_TEST_PLAN.md`, `BASELINE_TEST_REPORT.md` | Baseline freeze record, test matrix and its first execution. |
| `FEATURE_PORTFOLIO.md` | G1 feature portfolio proposal. |

Rules:

- Update `STATE.md` after every task.
- Append to `LEDGER.md`; do not rewrite history.
- Record every `Q` (Qwen3.8 Flash) escalation in `DECISIONS.md`.
- `UNKNOWN` is not `PASS`.
- Never claim hardware, arm64, root/systemd/udev, or 24h soak without evidence.
