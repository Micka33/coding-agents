# Task Breakdown

Status: draft

## Current Position

No developer tasks should be assigned until the readiness gate is approved.

The codebase already contains a broad V0 implementation as a Python package and
CLI under `coding_agents/`, but workflow artifacts previously contained placeholders.
This task breakdown therefore separates:

- documentation reconciliation allowed in shaping mode; and
- proposed implementation/quality tasks that require readiness approval before
  code changes.

## Status Legend

- `completed`: done as a docs-only shaping update.
- `pending`: still needed in shaping artifacts.
- `proposed`: recommended implementation work, not yet authorized.
- `blocked`: cannot start until a dependency or approval is complete.

## Component Implementation Status

| Area | Status | Notes |
| --- | --- | --- |
| Reusable Python package under `coding_agents/` | Implemented | Existing V0 module boundary. |
| Minimal CLI | Implemented | Local interactive entrypoint exists. |
| Engineering-manager Deep Agent | Implemented | Main coordinator exists. |
| Resident product analyst/software architect tools | Implemented | Manager-only resident collaborator tools exist. |
| SQLite/Postgres/memory checkpointers | Implemented | Local, shared/production, and disposable/test options exist. |
| Stable resident thread IDs | Implemented | Product and architecture residents have stable derived thread IDs. |
| Scout subagent | Implemented | Reconnaissance role exists. |
| Implementation subagent prompts/wiring | Implemented / gated | Implementation subagents are registered only after implementation-mode readiness approval. |
| Tavily tools | Implemented | Web search/fetch tools exist. |
| Workflow artifacts | Partial | Files exist and now contain draft content; human validation and gate approval are still pending. |
| Permissions by mode | Implemented / gated | Shaping mode remains docs-only for writes; implementation writes require explicit task-scoped allowlists. |
| Readiness gate enforcement | Implemented / unapproved default | `readiness-gate.yaml` is machine-readable and implementation mode fails closed until full approval is recorded. |
| Tests and CI | Partial / CI missing | Focused governance tests were added; broad automated validation and CI remain missing. |
| Python runtime support | Risk / partial | Python `>=3.14` needs ratification or adjustment. |

## Shaping Tasks

| ID | Task | Owner Role | Dependencies | Acceptance Criteria | Status |
| --- | --- | --- | --- | --- | --- |
| DOC-001 | Reconcile architecture, decision, task, and readiness artifacts with observed V0 implementation | software-architect | Observed implementation summary from engineering manager | `architecture-brief.md`, `decision-log.md`, `task-breakdown.md`, and `readiness-gate.md` reflect implemented/partial/missing status, risks, decisions, and proposed tasks | completed |
| SHAPE-001 | Replace product placeholders with real product context | product-analyst | Human/product input or existing validated context | `product-brief.md` documents problem, target users, goals, non-goals, MVP scope, and open questions | completed |
| SHAPE-002 | Replace requirements placeholders with acceptance criteria | product-analyst | SHAPE-001 | `requirements.md` documents functional requirements, non-functional requirements, edge cases, and core acceptance criteria | completed |
| SHAPE-003 | Prioritize MVP and deferred work | product-analyst + engineering-manager | SHAPE-001, SHAPE-002 | `prioritization.md` identifies candidate scope, MVP cut, deferred work, and rationale | completed |
| ARCH-001 | Ratify or revise proposed architecture decisions | software-architect + engineering-manager + human | Updated `decision-log.md` | DEC-0003 through DEC-0006 are approved, revised, or explicitly deferred | completed |
| PLAN-001 | Run a scout-backed code/docs gap check before readiness approval | engineering-manager + scout | Updated artifacts | `code-docs-gap-check.md` separates codebase facts from documentation claims and updates artifacts for material mismatches | completed |
| PLAN-002 | Prepare readiness approval packet | engineering-manager | SHAPE-001 through SHAPE-003, ARCH-001, PLAN-001 | Human can review clear go/no-go status, unresolved questions, risks, and proposed implementation tasks | pending |

## Proposed Implementation and Quality Tasks

Except for the limited DEC-0004/DEC-0005 governance work authorized on
2026-05-24, these tasks are not authorized while the project remains in shaping
mode. They become eligible only after the readiness gate is approved by the
human.

| ID | Task | Owner Role | Dependencies | Acceptance Criteria | Status |
| --- | --- | --- | --- | --- | --- |
| DEV-001 | Implement machine-enforced readiness gate | developer + engineering-manager | DEC-0004 approved; limited governance implementation authorized by human on 2026-05-24 | Implementation mode fails closed when readiness is not approved; gate state is machine-readable or otherwise checkable by the manager; denial messages identify missing gate items; tests cover approved, unapproved, missing, and invalid states | implemented / validation pending |
| DEV-002 | Tighten implementation-mode write permissions | developer + security-reviewer | DEC-0005 approved; DEV-001 or equivalent guard; limited governance implementation authorized by human on 2026-05-24 | Developer tasks require explicit write scopes; out-of-scope writes are rejected or require manager-mediated escalation; access expansion requests include requested paths, rationale, risk, and alternatives; manager may consult product and architecture before approving, denying, splitting, or redirecting the task; mode permissions distinguish shaping docs-only access from implementation task scopes; tests cover allowed, denied, and escalation paths | implemented / validation pending |
| QA-001 | Add automated tests for agent-team wiring | qa-engineer + developer | Stable package APIs; DEC-0001 and DEC-0002 retained | Tests cover manager construction, resident product/architecture tools, stable thread IDs, SQLite/memory checkpointers, scout wiring, Tavily tool registration, artifact templates, and mode permissions | proposed / blocked |
| DEVOPS-001 | Add CI for tests and packaging checks | devops-engineer | QA-001 test command defined | CI runs on pull requests or equivalent checks; package installs in a clean environment; CLI smoke test runs; failures block release readiness | proposed / blocked |
| ARCH-002 | Run Python runtime compatibility review | software-architect + devops-engineer | DEC-0006 approved; implementation/release-readiness work authorized | Compatibility review documents dependency and environment support; package metadata, `.python-version`, docs, and CI match the ratified Python version or range; CI tests the ratified version or range | proposed / blocked |
| QA-002 | Validate CLI smoke path | qa-engineer + developer | CLI entrypoint stable; QA-001/DEVOPS-001 as appropriate | CLI starts in a clean environment, initializes the selected checkpointer, and reaches a safe interactive prompt without requiring implementation-mode approval | proposed / blocked |
| SEC-001 | Review tool and permission boundaries | security-reviewer | DEV-002 design available | Review covers scout read-only behavior, Tavily tools, filesystem write scopes, destructive operation protections, and secret handling; findings are triaged before release readiness | proposed / blocked |
| WRITER-001 | Update user-facing usage docs after gate decisions | technical-writer | SHAPE-001 through SHAPE-003; ARCH-001; relevant implementation tasks complete | README or equivalent docs describe installation, CLI use, checkpointer configuration, mode rules, and limitations consistent with code and decisions | proposed / blocked |

## DEC-0004/DEC-0005 Corrective Security Pass

The corrective security pass has been implemented and is pending test execution /
final validation. It:

- removed `scout.execute` instead of attempting broad shell command validation;
- closed case-variant bypasses for readiness and secret deny paths;
- rejects symlink components and verifies resolved containment for artifact dirs
  and write scopes;
- validates `artifacts_dir` after resolution, not by string checks alone;
- redacts secrets from startup/runtime exception output.

This pass did not introduce new dependencies, change runtime metadata, broaden
implementation mode, or add new scout command capabilities.

## Implementation Ordering Recommendation

1. Review and validate the draft product, requirements, and prioritization artifacts.
2. Use the completed scout-backed gap analysis in `code-docs-gap-check.md` as the current code/docs baseline.
3. Run the focused test suite and complete final validation for DEC-0004/DEC-0005 enforcement.
4. Seek explicit human authorization before any broader implementation mode or feature work.
5. Rerun the scout-backed gap check if code changes before readiness approval.
6. Add tests and CI before release readiness.
7. Run the DEC-0006 Python runtime compatibility review before release readiness.
8. Update user-facing documentation after behavior and runtime support are stable.
