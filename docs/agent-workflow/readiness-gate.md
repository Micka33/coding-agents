# Readiness Gate

Status: approved for broad implementation entry

Implementation mode has explicit human approval as of 2026-05-25 for bounded,
task-scoped work. CI and DEC-0006 Python runtime review remain release-readiness
blockers, not implementation-entry blockers.

The machine-readable `readiness-gate.yaml` records this approval with
`approval_scope: full_implementation`.

During implementation mode, each task still requires a bounded task brief with
explicit ownership, files or modules in scope, constraints, and acceptance
criteria. Implementation writes are repo-wide by default after gate approval,
except protected readiness/secret paths; optional `--write-path` restrictions
can be used for narrower runs.

## Gate Decision

Human decision: **GO / approved for broad implementation mode with bounded, task-scoped tasks**

Machine-readable gate status: **approved / recorded**

Release readiness: **not approved**

Conditions and remaining blockers:

- Broad implementation work is approved only when each task has bounded ownership, acceptance criteria, and review expectations.
- Architecture decisions DEC-0003 through DEC-0007 are approved; DEC-0004/DEC-0005/DEC-0007 enforcement is implemented, statically inspected, and tested locally.
- Human approval for broad implementation mode was recorded on 2026-05-25.
- CI is missing and remains a release-readiness blocker.
- DEC-0006 Python runtime compatibility review remains a release-readiness blocker.
- Runtime implementation mode may start under the approved gate.

## Current Assessment

| Criterion | Status | Evidence / Notes | Required Action |
| --- | --- | --- | --- |
| Product problem is clear | Approved for implementation entry | `product-brief.md` documents the problem and current state; human approved broad implementation entry on 2026-05-25. | Keep scope bounded per task. |
| Target user or usage context is defined | Approved for implementation entry | `product-brief.md` identifies human decision makers, engineering-manager operators, and specialist contributors. | Keep scope bounded per task. |
| MVP is defined | Approved for implementation entry | `product-brief.md` and `prioritization.md` describe the V0 MVP cut. | Do not expand beyond task-scoped implementation without a new decision. |
| Non-goals are documented | Approved for implementation entry | Non-goals include no production-ready claim, no multi-feature-stream MVP, and no external distribution before release-readiness blockers are cleared. | Preserve non-goals during implementation. |
| Core acceptance criteria are documented | Approved for implementation entry | `requirements.md` captures V0 governance acceptance criteria; `task-breakdown.md` lists candidate implementation/quality tasks. | Create a bounded task brief before each assignment. |
| Major architecture choices are made | Approved for implementation entry | DEC-0001 through DEC-0007 are approved; DEC-0004/DEC-0005/DEC-0007 enforcement is implemented, statically inspected, and tested locally; DEC-0006 remains release-readiness work. | Track DEC-0006 before release readiness. |
| Major technical risks are identified | Accepted for implementation entry | Remaining risks include missing CI, gate artifact integrity, repo-wide implementation write power after approval, and unresolved Python `>=3.14` runtime support. | Treat CI and DEC-0006 as release-readiness blockers and keep implementation tasks bounded. |
| Open questions are answered or explicitly deferred | Accepted for implementation entry | CI and DEC-0006 are explicitly deferred to release-readiness; bounded implementation may proceed under the recorded machine-readable gate. | Keep deferred blockers visible. |
| Task breakdown is clear enough for developer agents | Approved for implementation entry | `task-breakdown.md` lists implementation and quality tasks with dependencies and acceptance criteria. | Produce scoped task briefs before assignment. |
| Each implementation task has acceptance criteria | Approved for implementation entry | Candidate tasks have acceptance criteria; each execution still requires a concrete bounded brief. | Produce scoped task briefs before assignment. |
| Human approved the move to implementation mode | Approved / recorded | Human approved broad implementation mode for bounded, task-scoped tasks on 2026-05-25 and `readiness-gate.yaml` records the approval. | Proceed with bounded implementation tasks while preserving release-readiness blockers. |

## Additional Release and Safety Checks

These items may not all block entry into implementation mode, but they block
claiming V0 is delivery-ready unless explicitly accepted as risks.

| Check | Status | Risk |
| --- | --- | --- |
| Machine-enforced readiness gate | Implemented / statically inspected and tested; approved | `readiness-gate.yaml` records `approved: true`, `approval_scope: full_implementation`, approver, date, and release-readiness caveats. |
| Implementation write protections | Implemented / statically inspected and tested | Implementation mode allows repo-wide writes by default after gate approval while denying protected readiness/secret paths; optional literal `--write-path` restrictions are tested. |
| Automated tests | Passing locally | `uv run --project / python -m unittest discover -s tests` exited 0 with `Ran 64 tests in 0.297s`, `OK`; CI remains missing. |
| CI | Missing / release blocker | No repeatable validation before merge/release; not an implementation-entry blocker by human decision on 2026-05-25. |
| Python runtime support decision | Release blocker / unresolved runtime | DEC-0006 requires compatibility review before release readiness; not an implementation-entry blocker by human decision on 2026-05-25. |
| Official code/docs baseline | Completed | PLAN-001 reconciled observed code facts into `architecture-brief.md`, `decision-log.md`, `readiness-gate.md`, and `task-breakdown.md`; refresh those artifacts when code changes. |

## Required During Runtime Implementation Use

1. Use the completed DEC-0004/DEC-0005/DEC-0007 local validation evidence as the governance baseline.
2. Use the official code/docs baseline in `architecture-brief.md`, `decision-log.md`, `readiness-gate.md`, and `task-breakdown.md`; refresh it when code changes.
3. Treat missing CI and the DEC-0006 runtime review as release-readiness blockers, not implementation-entry blockers.
4. Require a bounded task brief before each implementation assignment.

## Readiness Decision Recorded

Human decision: **approved broad implementation mode for bounded, task-scoped
work** on 2026-05-25.

Accepted release-readiness blockers: missing CI and DEC-0006 runtime review.
These do not block implementation entry, but they do block delivery-ready,
release-ready, production-ready, or external distribution claims.

Machine-readable gate values:

```yaml
approved: true
approval_scope: full_implementation
approved_by: "Mickael"
approved_date: "2026-05-25"
notes: "Broad implementation mode approved for bounded, task-scoped tasks. CI and DEC-0006 runtime review remain release-readiness blockers, not implementation-entry blockers."
```

## Approval

Approved by: Human decision maker

Date: 2026-05-25

Notes: Broad implementation mode is approved for bounded, task-scoped tasks. CI
and DEC-0006 runtime review remain release-readiness blockers only.
