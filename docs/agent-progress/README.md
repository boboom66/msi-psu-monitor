# Agent progress and evidence

This directory is the durable memory for the Product v2 work. It is written for
both the human supervisor and the next agent session.

| File | Purpose |
|---|---|
| `STATE.md` | Current phase/task/branch/HEAD/blockers. Read this first when resuming. |
| `LEDGER.md` | Append-only task table: status, model, commit, tests, evidence, review. |
| `DECISIONS.md` | ADR-style decisions: context, decision, consequences. |
| `APPROVALS.md` | Human gate requests (G0–G5) and their responses. |
| `BASELINE.md` | What the tree looked like before Product v2, including user-added features. |
| `EVIDENCE/` | Per-task command output, screenshots, logs. |
| `PHASE_0_REPORT.md` | Phase 0 summary and G0 approval request. |

Rules:

- Update `STATE.md` after every task.
- Append to `LEDGER.md`; do not rewrite history.
- Record every `Q` (Qwen3.8 Flash) escalation in `DECISIONS.md`.
- `UNKNOWN` is not `PASS`.
- Never claim hardware, arm64, root/systemd/udev, or 24h soak without evidence.
