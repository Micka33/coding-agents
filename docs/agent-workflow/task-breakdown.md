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
| Implementation subagent prompts/wiring | Partial | Wiring exists; activation should wait for gate approval and tighter scopes. |
| Tavily tools | Implemented | Web search/fetch tools exist. |
| Workflow artifacts | Partial | Files exist and now contain draft content; human validation and gate approval are still pending. |
| Permissions by mode | Partial | Shaping mode docs-only rule exists; implementation writes need task scoping. |
| Readiness gate enforcement | Missing | Gate is documented but not machine-enforced. |
| Tests and CI | Missing | No observed automated validation. |
| Python runtime support | Risk / partial | Python `>=3.14` needs ratification or adjustment. |

## Shaping Tasks

| ID | Task | Owner Role | Dependencies | Acceptance Criteria | Status |
| --- | --- | --- | --- | --- | --- |
| DOC-001 | Reconcile architecture, decision, task, and readiness artifacts with observed V0 implementation | software-architect | Observed implementation summary from engineering manager | `architecture-brief.md`, `decision-log.md`, `task-breakdown.md`, and `readiness-gate.md` reflect implemented/partial/missing status, risks, decisions, and proposed tasks | completed |
| SHAPE-001 | Replace product placeholders with real product context | product-analyst | Human/product input or existing validated context | `product-brief.md` documents problem, target users, goals, non-goals, MVP scope, and open questions | completed |
| SHAPE-002 | Replace requirements placeholders with acceptance criteria | product-analyst | SHAPE-001 | `requirements.md` documents functional requirements, non-functional requirements, edge cases, and core acceptance criteria | completed |
| SHAPE-003 | Prioritize MVP and deferred work | product-analyst + engineering-manager | SHAPE-001, SHAPE-002 | `prioritization.md` identifies candidate scope, MVP cut, deferred work, and rationale | completed |
| ARCH-001 | Ratify or revise proposed architecture decisions | software-architect + engineering-manager + human | Updated `decision-log.md` | DEC-0003 through DEC-0006 are approved, revised, or explicitly deferred | pending |
| PLAN-001 | Run a scout-backed code/docs gap check before readiness approval | engineering-manager + scout | Updated artifacts | Gap report separates codebase facts from documentation claims and updates artifacts if mismatches change project context | pending |
| PLAN-002 | Prepare readiness approval packet | engineering-manager | SHAPE-001 through SHAPE-003, ARCH-001, PLAN-001 | Human can review clear go/no-go status, unresolved questions, risks, and proposed implementation tasks | pending |

## Proposed Implementation and Quality Tasks

These tasks are not authorized while the project remains in shaping mode. They
become eligible only after the readiness gate is approved by the human.

| ID | Task | Owner Role | Dependencies | Acceptance Criteria | Status |
| --- | --- | --- | --- | --- | --- |
| DEV-001 | Implement machine-enforced readiness gate | developer + engineering-manager | DEC-0004 approved; readiness approval for this implementation task | Implementation mode fails closed when readiness is not approved; gate state is machine-readable or otherwise checkable by the manager; denial messages identify missing gate items; tests cover approved and unapproved states | proposed / blocked |
| DEV-002 | Tighten implementation-mode write permissions | developer + security-reviewer | DEC-0005 approved; DEV-001 or equivalent guard | Developer tasks require explicit write scopes; out-of-scope writes are rejected or require manager-mediated escalation; access expansion requests include requested paths, rationale, risk, and alternatives; manager may consult product and architecture before approving, denying, splitting, or redirecting the task; mode permissions distinguish shaping docs-only access from implementation task scopes; tests cover allowed, denied, and escalation paths | proposed / blocked |
| QA-001 | Add automated tests for agent-team wiring | qa-engineer + developer | Stable package APIs; DEC-0001 and DEC-0002 retained | Tests cover manager construction, resident product/architecture tools, stable thread IDs, SQLite/memory checkpointers, scout wiring, Tavily tool registration, artifact templates, and mode permissions | proposed / blocked |
| DEVOPS-001 | Add CI for tests and packaging checks | devops-engineer | QA-001 test command defined | CI runs on pull requests or equivalent checks; package installs in a clean environment; CLI smoke test runs; failures block release readiness | proposed / blocked |
| ARCH-002 | Decide Python runtime support range | software-architect + devops-engineer | DEC-0006 proposed | Compatibility review documents dependency and environment support; package metadata and docs match the ratified Python version or range; CI tests the ratified version or range | proposed / blocked |
| QA-002 | Validate CLI smoke path | qa-engineer + developer | CLI entrypoint stable; QA-001/DEVOPS-001 as appropriate | CLI starts in a clean environment, initializes the selected checkpointer, and reaches a safe interactive prompt without requiring implementation-mode approval | proposed / blocked |
| SEC-001 | Review tool and permission boundaries | security-reviewer | DEV-002 design available | Review covers scout read-only behavior, Tavily tools, filesystem write scopes, destructive operation protections, and secret handling; findings are triaged before release readiness | proposed / blocked |
| WRITER-001 | Update user-facing usage docs after gate decisions | technical-writer | SHAPE-001 through SHAPE-003; ARCH-001; relevant implementation tasks complete | README or equivalent docs describe installation, CLI use, checkpointer configuration, mode rules, and limitations consistent with code and decisions | proposed / blocked |

## Implementation Ordering Recommendation

1. Review and validate the draft product, requirements, and prioritization artifacts.
2. Ratify proposed architecture decisions, especially readiness enforcement,
   write scopes, and Python runtime support.
3. Run scout-backed gap analysis against the actual codebase.
4. Seek human readiness approval.
5. Implement readiness enforcement and permission tightening before broad
   feature work.
6. Add tests and CI before release readiness.
7. Update user-facing documentation after behavior and runtime support are
   stable.
