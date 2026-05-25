# Task Breakdown

Status: approved for implementation entry

## Current Position

The human decision maker approved broad implementation mode on 2026-05-25 for
bounded, task-scoped tasks. Runtime implementation still requires the
machine-readable `readiness-gate.yaml` to record that approval; the current agent
write attempt was denied by tool permissions.

The codebase already contains a broad V0 implementation as a Python package and
CLI under `coding_agents/`. This task breakdown now separates:

- completed shaping and governance validation work;
- implementation/quality tasks eligible after machine-readable gate recording;
- release-readiness blockers that must be cleared before delivery-ready,
  release-ready, production-ready, or external distribution claims.

## Status Legend

- `completed`: done as a docs-only shaping update.
- `pending`: still needed in shaping artifacts.
- `approved / task brief required`: authorized for implementation entry, but not assignable until a bounded brief and write scope are defined.
- `blocked`: cannot start until a dependency, machine-readable gate recording, or other approval is complete.

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
| Implementation subagent prompts/wiring | Implemented / statically inspected and tested; gated | Scout reports implementation subagents are registered only after implementation-mode readiness approval. |
| Tavily tools | Implemented | Web search/fetch tools exist. |
| Workflow artifacts | Approved for implementation entry | Files exist and capture the human decision approving bounded, task-scoped implementation entry; machine-readable YAML recording remains pending by permitted process. |
| Permissions by mode | Implemented / statically inspected and tested | Shaping mode remains docs-only for writes; implementation writes require explicit task-scoped allowlists. |
| Readiness gate enforcement | Implemented / statically inspected and tested; human-approved, YAML recording pending | Human approved broad implementation entry on 2026-05-25; `readiness-gate.yaml` still has `approved: false` because current agent write permissions denied updating it. |
| Tests and CI | Tests passing locally; CI missing | Local validation passed with `uv run --project / python -m unittest discover -s tests`; result: exit code 0, `Ran 64 tests in 0.297s`, `OK`; CI is still missing. |
| Python runtime support | Risk / partial | Python `>=3.14` needs ratification or adjustment. |

## Shaping Tasks

| ID | Task | Owner Role | Dependencies | Acceptance Criteria | Status |
| --- | --- | --- | --- | --- | --- |
| DOC-001 | Reconcile architecture, decision, task, and readiness artifacts with observed V0 implementation | software-architect | Observed implementation summary from engineering manager | `architecture-brief.md`, `decision-log.md`, `task-breakdown.md`, and `readiness-gate.md` reflect implemented/partial/missing status, risks, decisions, and proposed tasks | completed |
| SHAPE-001 | Replace product placeholders with real product context | product-analyst | Human/product input or existing validated context | `product-brief.md` documents problem, target users, goals, non-goals, MVP scope, and open questions | completed |
| SHAPE-002 | Replace requirements placeholders with acceptance criteria | product-analyst | SHAPE-001 | `requirements.md` documents functional requirements, non-functional requirements, edge cases, and core acceptance criteria | completed |
| SHAPE-003 | Prioritize MVP and deferred work | product-analyst + engineering-manager | SHAPE-001, SHAPE-002 | `prioritization.md` identifies candidate scope, MVP cut, deferred work, and rationale | completed |
| ARCH-001 | Ratify or revise proposed architecture decisions | software-architect + engineering-manager + human | Updated `decision-log.md` | DEC-0003 through DEC-0008 are approved, revised, or explicitly deferred | completed |
| PLAN-001 | Reconcile observed code facts into official readiness artifacts | engineering-manager + scout | Updated artifacts | `architecture-brief.md`, `decision-log.md`, `readiness-gate.md`, and this task breakdown separate observed code facts from readiness claims and record material mismatches | completed |
| PLAN-002 | Prepare readiness approval packet | engineering-manager | SHAPE-001 through SHAPE-003, ARCH-001, PLAN-001 | Human can review clear go/no-go status, unresolved questions, risks, and proposed implementation tasks | completed |

## Approved Implementation and Quality Tasks

Broad implementation mode is approved for bounded, task-scoped work. These tasks
are eligible after the machine-readable readiness gate records approval and each
task receives a concrete brief with explicit write scope. CI and DEC-0006 remain
release-readiness blockers, not implementation-entry blockers.

| ID | Task | Owner Role | Dependencies | Acceptance Criteria | Status |
| --- | --- | --- | --- | --- | --- |
| DEV-001 | Implement machine-enforced readiness gate | developer + engineering-manager | DEC-0004 approved; limited governance implementation authorized by human on 2026-05-24 | Implementation mode fails closed when readiness is not approved; gate state is machine-readable or otherwise checkable by the manager; denial messages identify missing gate items; tests cover approved, unapproved, missing, and invalid states | implemented / statically inspected and tested |
| DEV-002 | Tighten implementation-mode write permissions | developer + security-reviewer | DEC-0005 approved; DEV-001 or equivalent guard; limited governance implementation authorized by human on 2026-05-24 | Developer tasks require explicit write scopes; out-of-scope writes are rejected or require manager-mediated escalation; access expansion requests include requested paths, rationale, risk, and alternatives; manager may consult product and architecture before approving, denying, splitting, or redirecting the task; mode permissions distinguish shaping docs-only access from implementation task scopes; tests cover allowed, denied, and escalation paths | implemented / statically inspected and tested |
| QA-001 | Add automated tests for agent-team wiring | qa-engineer + developer | Stable package APIs; DEC-0001 and DEC-0002 retained; machine-readable gate recording | Tests cover manager construction, resident product/architecture tools, stable thread IDs, SQLite/memory checkpointers, scout wiring, Tavily tool registration, artifact templates, and mode permissions | approved / task brief required |
| DEVOPS-001 | Add CI for tests and packaging checks | devops-engineer | Test command defined; machine-readable gate recording | CI runs on pull requests or equivalent checks; package installs in a clean environment; CLI smoke test runs; failures block release readiness | approved / task brief required |
| ARCH-002 | Run Python runtime compatibility review | software-architect + devops-engineer | DEC-0006 approved; implementation-entry approved; machine-readable gate recording if code/docs changes are needed | Compatibility review documents dependency and environment support; package metadata, `.python-version`, docs, and CI match the ratified Python version or range; CI tests the ratified version or range | approved / task brief required |
| QA-002 | Validate CLI smoke path | qa-engineer + developer | CLI entrypoint stable; machine-readable gate recording | CLI starts in a clean environment, initializes the selected checkpointer, and reaches a safe interactive prompt without requiring implementation-mode approval | approved / task brief required |
| SEC-001 | Review tool and permission boundaries | security-reviewer | DEV-002 design available; machine-readable gate recording if code changes are needed | Review covers scout read-only behavior, Tavily tools, filesystem write scopes, destructive operation protections, and secret handling; findings are triaged before release readiness | approved / task brief required |
| WRITER-001 | Update user-facing usage docs after gate decisions | technical-writer | SHAPE-001 through SHAPE-003; ARCH-001; relevant implementation tasks complete; machine-readable gate recording if repo docs outside workflow artifacts are changed | README or equivalent docs describe installation, CLI use, checkpointer configuration, mode rules, and limitations consistent with code and decisions | approved / task brief required |

## DEC-0004/DEC-0005 Corrective Security Pass

The corrective security pass has been implemented, statically inspected, and
validated by the local unittest suite on 2026-05-25. It:

- removed `scout.execute` instead of attempting broad shell command validation;
- closed case-variant bypasses for readiness and secret deny paths;
- rejects symlink components and verifies resolved containment for artifact dirs
  and write scopes;
- validates `artifacts_dir` after resolution, not by string checks alone;
- redacts secrets from startup/runtime exception output.

Validation evidence: `uv run --project / python -m unittest discover -s tests` exited 0 with `Ran 64 tests in 0.297s`, `OK`.

This pass did not introduce new dependencies, change runtime metadata, broaden
implementation mode, or add new scout command capabilities.

## Implementation Ordering Recommendation

1. Record the human approval in `readiness-gate.yaml` through a permitted process so runtime implementation mode can pass the machine gate.
2. Use the current baseline recorded in `architecture-brief.md`, `decision-log.md`, `readiness-gate.md`, and this task breakdown.
3. Require a bounded task brief and explicit write scope before assigning any implementation specialist.
4. Prioritize CI and DEC-0006 work as release-readiness blockers, not implementation-entry blockers.
5. Rerun scout-backed reconnaissance and update the official artifacts when code changes.
6. Update user-facing documentation after behavior and runtime support are stable.
