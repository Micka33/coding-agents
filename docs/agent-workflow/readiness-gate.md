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
- Architecture decisions DEC-0003 through DEC-0006 are now approved; DEC-0004/DEC-0005 enforcement is implemented pending validation, and DEC-0006 compatibility review remains unimplemented.
- Human approval for broad implementation mode has not been recorded.
- Human authorization for limited DEC-0004/DEC-0005 governance implementation was recorded on 2026-05-24.
- Machine-readable readiness artifact and runtime guard are now implemented; the gate remains unapproved by default.
- Implementation-mode write permissions now require task-scoped allowlists; broad repository writes remain blocked by default.

## Current Assessment

| Criterion | Status | Evidence / Notes | Required Action |
| --- | --- | --- | --- |
| Product problem is clear | Partial / draft | `product-brief.md` now documents the problem and current state, but human validation is still pending. | Human review and approve or revise. |
| Target user or usage context is defined | Partial / draft | `product-brief.md` now identifies human decision makers, engineering-manager operators, and specialist contributors. | Human review and approve or revise. |
| MVP is defined | Partial / draft | `product-brief.md` and `prioritization.md` now describe the V0 MVP cut. | Human review and approve or revise MVP boundaries. |
| Non-goals are documented | Partial / draft | `product-brief.md` now documents non-goals including no production-ready claim, no unapproved gate, and no multi-feature-stream MVP. | Human review and approve or revise. |
| Core acceptance criteria are documented | Partial / draft | `requirements.md` now captures documentation-alignment acceptance criteria; implementation-task acceptance criteria remain proposed in `task-breakdown.md`. | Validate acceptance criteria against desired V0 scope. |
| Major architecture choices are made | Partial | DEC-0001 through DEC-0006 are approved; DEC-0004/DEC-0005 enforcement is implemented pending validation, and DEC-0006 requires compatibility review before release readiness. | Validate enforcement and plan runtime-review follow-up work. |
| Major technical risks are identified | Partial | Remaining risks include unapproved broad implementation gate, limited test/CI coverage, gate artifact integrity, and unresolved Python `>=3.14` runtime support. | Confirm severity and mitigation ownership. |
| Open questions are answered or explicitly deferred | Partial | Coded readiness enforcement and write-scope tightening are implemented pending validation; Python runtime floor is explicitly deferred to DEC-0006 compatibility review before release readiness. | Track follow-up implementation/review tasks. |
| Task breakdown is clear enough for developer agents | Partial | `task-breakdown.md` now lists shaping tasks and proposed implementation tasks. | Validate task order after product requirements are complete. |
| Each implementation task has acceptance criteria | Partial | Proposed technical tasks have acceptance criteria; product-driven implementation tasks cannot be final until requirements are validated. | Validate requirements, then refine task briefs. |
| Human approved the move to implementation mode | Limited / blocked | Human approved limited DEC-0004/DEC-0005 governance implementation only; broad implementation mode is not approved. | Complete/verify governance implementation, then request any broader approval separately. |

## Additional Release and Safety Checks

These items may not all block entry into implementation mode, but they block
claiming V0 is delivery-ready unless explicitly accepted as risks.

| Check | Status | Risk |
| --- | --- | --- |
| Machine-enforced readiness gate | Implemented / unapproved default | `readiness-gate.yaml` exists and implementation mode fails closed unless it records full implementation approval with approver/date metadata. |
| Task-scoped implementation write permissions | Implemented | Implementation mode uses explicit write allowlists and denies writes when no scope is configured. |
| Automated tests | Partial | Focused tests cover readiness parsing/guarding, permission allowlists, team gating, and CLI write-path parsing; broader coverage and CI remain missing. |
| CI | Missing | No repeatable validation before merge/release. |
| Python runtime support decision | Approved review / unresolved runtime | DEC-0006 requires compatibility review before release readiness; Python `>=3.14` is not final. |
| Scout-backed code/docs gap check | Completed | PLAN-001 completed in `code-docs-gap-check.md`; final readiness should rerun if code changes before approval. |

## Minimum Required Before Gate Approval

1. Human review of `product-brief.md`, `requirements.md`, `prioritization.md`,
   and `task-breakdown.md`; approve, revise, or explicitly defer open items.
2. Validate the completed DEC-0004/DEC-0005 enforcement work, and track DEC-0006 compatibility review before release readiness.
3. Use the completed PLAN-001 scout-backed gap check as the current baseline; rerun it if code changes before approval.
4. Confirm whether missing tests/CI are blockers for implementation entry or
   only for release readiness.
5. Record explicit human approval if the gate is accepted.

## Approval

Approved by: Not approved

Date: N/A

Notes: Gate remains in draft for broad implementation. Shaping-mode documentation
updates are allowed under `docs/agent-workflow/`. Limited DEC-0004/DEC-0005
governance implementation was authorized separately and does not approve broader
work.
