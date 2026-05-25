# Readiness Gate

Status: draft — not approved

Implementation mode requires explicit human approval. The current full gate result is
**not passed**; broad implementation mode remains blocked.

A limited governance implementation is authorized for DEC-0004 and DEC-0005 only.
This authorization permits the minimum code and test changes needed to implement
the machine-readable readiness guard and task-scoped write-scope enforcement. It
does not approve broader feature implementation.

During shaping mode, allowed documentation updates are limited to
`/docs/agent-workflow/`. During the limited governance implementation, writes are
limited to the scoped files required for DEV-001 and DEV-002 plus related tests
and workflow artifacts.

## Gate Decision

Result: **FAIL / not ready for broad implementation mode**

Limited authorization: **APPROVED for DEC-0004/DEC-0005 governance implementation only**

Primary blockers:

- Product, requirements, prioritization, and task breakdown artifacts are draft and need human validation.
- Architecture decisions DEC-0003 through DEC-0007 are now approved; DEC-0004/DEC-0005/DEC-0007 enforcement is implemented, statically inspected, and tested locally; DEC-0006 compatibility review remains unimplemented.
- Human approval for broad implementation mode has not been recorded.
- Human authorization for limited DEC-0004/DEC-0005 governance implementation was recorded on 2026-05-24.
- Machine-readable readiness artifact and runtime guard are now implemented, statically inspected, and tested locally; the gate remains unapproved by default.
- Implementation-mode write permissions now require task-scoped allowlists; broad repository writes remain blocked by default.

## Current Assessment

| Criterion | Status | Evidence / Notes | Required Action |
| --- | --- | --- | --- |
| Product problem is clear | Partial / draft | `product-brief.md` now documents the problem and current state, but human validation is still pending. | Human review and approve or revise. |
| Target user or usage context is defined | Partial / draft | `product-brief.md` now identifies human decision makers, engineering-manager operators, and specialist contributors. | Human review and approve or revise. |
| MVP is defined | Partial / draft | `product-brief.md` and `prioritization.md` now describe the V0 MVP cut. | Human review and approve or revise MVP boundaries. |
| Non-goals are documented | Partial / draft | `product-brief.md` now documents non-goals including no production-ready claim, no unapproved gate, and no multi-feature-stream MVP. | Human review and approve or revise. |
| Core acceptance criteria are documented | Partial / draft | `requirements.md` now captures documentation-alignment acceptance criteria; implementation-task acceptance criteria remain proposed in `task-breakdown.md`. | Validate acceptance criteria against desired V0 scope. |
| Major architecture choices are made | Partial | DEC-0001 through DEC-0007 are approved; DEC-0004/DEC-0005/DEC-0007 enforcement is implemented, statically inspected, and tested locally; DEC-0006 requires compatibility review before release readiness. | Decide whether DEC-0006 is an implementation-entry blocker or release-readiness follow-up. |
| Major technical risks are identified | Partial | Remaining risks include unapproved broad implementation gate, missing CI, gate artifact integrity, and unresolved Python `>=3.14` runtime support. | Confirm whether CI and DEC-0006 block implementation entry or only release readiness. |
| Open questions are answered or explicitly deferred | Partial | Coded readiness enforcement, write-scope tightening, and execution-profile controls are implemented, statically inspected, and tested locally; Python runtime floor is explicitly deferred to DEC-0006 compatibility review before release readiness. | Decide whether to approve broad implementation for bounded tasks. |
| Task breakdown is clear enough for developer agents | Partial | `task-breakdown.md` now lists shaping tasks and proposed implementation tasks. | Validate task order after product requirements are complete. |
| Each implementation task has acceptance criteria | Partial | Proposed technical tasks have acceptance criteria; product-driven implementation tasks cannot be final until requirements are validated. | Validate requirements, then refine task briefs. |
| Human approved the move to implementation mode | Limited / blocked | Human approved limited DEC-0004/DEC-0005 governance implementation only; broad implementation mode is not approved. Governance implementation is now locally tested. | Request explicit broad implementation approval separately if the remaining risks are accepted. |

## Additional Release and Safety Checks

These items may not all block entry into implementation mode, but they block
claiming V0 is delivery-ready unless explicitly accepted as risks.

| Check | Status | Risk |
| --- | --- | --- |
| Machine-enforced readiness gate | Implemented / statically inspected and tested | `readiness-gate.yaml` exists with `approved: false`; scout reports implementation mode fails closed unless it records full implementation approval with approver/date metadata; local unittest suite passed on 2026-05-25. |
| Task-scoped implementation write permissions | Implemented / statically inspected and tested | Scout reports implementation mode uses explicit write allowlists and denies writes when no scope is configured; local unittest suite passed on 2026-05-25. |
| Automated tests | Passing locally | `uv run --project / python -m unittest discover -s tests` exited 0 with `Ran 64 tests in 0.297s`, `OK`; CI remains missing. |
| CI | Missing | No repeatable validation before merge/release. |
| Python runtime support decision | Approved review / unresolved runtime | DEC-0006 requires compatibility review before release readiness; Python `>=3.14` is not final. |
| Official code/docs baseline | Completed | PLAN-001 reconciled observed code facts into `architecture-brief.md`, `decision-log.md`, `readiness-gate.md`, and `task-breakdown.md`; final readiness should refresh those artifacts if code changes before approval. |

## Minimum Required Before Gate Approval

1. Human review of `product-brief.md`, `requirements.md`, `prioritization.md`,
   and `task-breakdown.md`; approve, revise, or explicitly defer open items.
2. Use the completed DEC-0004/DEC-0005/DEC-0007 local validation evidence as the governance baseline.
3. Use the official code/docs baseline in `architecture-brief.md`, `decision-log.md`, `readiness-gate.md`, and `task-breakdown.md`; refresh it if code changes before approval.
4. Confirm whether missing CI and the DEC-0006 runtime review are blockers for implementation entry or only for release readiness.
5. Record explicit human approval if the gate is accepted.

## Next Readiness Decision Prepared

Recommended next decision: **human go/no-go for broad implementation mode**. The
governance controls now have static inspection evidence and a passing local
unittest run. Broad implementation mode is still not approved because explicit
human approval has not been recorded.

Decision to request from the human: approve broad implementation mode for bounded,
task-scoped work now, while treating missing CI and DEC-0006 runtime review as
release-readiness blockers; or require CI and/or DEC-0006 completion before broad
implementation entry.

Keep `readiness-gate.yaml` at `approved: false` until explicit human approval for
broad implementation mode is recorded.

## Approval

Approved by: Not approved

Date: N/A

Notes: Gate remains in draft for broad implementation. Shaping-mode documentation
updates are allowed under `docs/agent-workflow/`. Limited DEC-0004/DEC-0005
governance implementation was authorized separately and does not approve broader
work.
