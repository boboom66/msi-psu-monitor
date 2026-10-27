# Documentation index

Use the documents below by topic. **Current product behavior** is described by
the project README and checked against code/tests; dated audits and development
records are snapshots, not a second source of current status.

## Start here

| Need | Document |
|---|---|
| Install, features, commands, and examples | [Project README](../README.md) |
| No-hardware checks and hardware acceptance checklist | [Verification guide](verify.md) |
| Current release verdict and evidence | [Release readiness](../bug-audit/RELEASE_READINESS.md) |
| Find support information | [Support policy](support.md) |

## Product and operation

| Topic | Document |
|---|---|
| HID protocol, registers, payload layouts | [Protocol reference](protocol.md) |
| Requirements mapped to implementation and tests | [Requirements traceability](requirements-traceability.md) |
| Machine setup and permissions | [Machine setup](machine-setup.md) |
| Hardware test procedure and evidence | [Hardware acceptance](hardware-acceptance.md) |
| Incident handling and recovery | [Incident response](incident-response.md) |
| Release builds and artifact contract | [Release guide](release.md) |
| Prometheus alert rules | [Prometheus rules](prometheus-rules.yml) |

## Quality, defects, and development records

| Topic | Canonical location |
|---|---|
| Open defects, fixes, and current release blockers | [`bug-audit/`](../bug-audit/README.md) |
| Test plans, test cases, and dated test reports | [`testing/`](testing/README.md) |
| Product v2 task status, decisions, approvals, and evidence | [`agent-progress/`](agent-progress/README.md) |
| Product review process and feature decisions | [Review playbook](agent-product-review-playbook.md) |
| Product v2 execution plan | [Master plan](AGENT_MASTER_PLAN.md) |
| Historical audit and development snapshots | [`archive/`](archive/README.md) |
| Historical command/output preview (not a current CLI reference) | [Feature preview](archive/新增功能指令与预览.md) |

## Source and research material

The workspace may also contain a separate `psu-file` reference archive with
source specifications, MSI Center reference code, screenshots, and original
requirements. That archive is not part of this Git repository or release
package. It is background evidence; current runtime behavior is defined by this
repository's code, tests, [protocol reference](protocol.md), and
[release-readiness record](../bug-audit/RELEASE_READINESS.md).

## Maintenance rules

Keep this small; a rule that is not followed is worse than no rule.

1. **Current facts have one home**: product behavior in `README.md`, protocol in
   `protocol.md`, gates/acceptance in `verify.md`, requirements mapping in
   `requirements-traceability.md`, release verdict in
   `bug-audit/RELEASE_READINESS.md`, live task state in `agent-progress/STATE.md`.
2. **New feature** → update `README.md` (usage) and `CHANGELOG.md`; add a row to
   `requirements-traceability.md` only when it maps to a requirement; update
   `verify.md` when a new check/entry point appears.
3. **Dated evidence** (test reports, phase reports, screenshots, previews) goes to
   `docs/archive/` (or `docs/testing/` for test records) and is never edited to
   look current; it carries a "historical snapshot" banner instead.
4. **Unresolved question** → `DECISIONS.md` (or an `OPEN` row in `BUG_TRACKER.md`),
   never silently written as fact in a current document.
5. **Delete only duplicates without independent value**, after checking links and
   scripts; anything with historical or design value is archived, not deleted.
