# Requirements

Status: draft

## Functional Requirements

### Shaping workflow

- The system must start in shaping mode unless a request is explicitly ready for implementation.
- The engineering-manager agent must be the default human-facing coordinator.
- The system must maintain durable workflow artifacts under `docs/agent-workflow/`.
- Product and architecture clarifications that change project context must be captured in the relevant artifact before responding.
- No production code changes should be made while operating in shaping mode.

### Resident specialists

- The engineering manager must be able to consult resident product-analyst and software-architect agents through manager-only tools.
- Resident specialists must route clarification questions through the engineering manager.
- Resident specialist state may be checkpointed through SQLite, Postgres, or memory, but durable truth remains in repository artifacts.

### Disposable specialists

- The system must provide a scout subagent for codebase reconnaissance.
- The system must provide implementation-mode specialist agents for developer, code-reviewer, QA, devops, security-reviewer, and technical-writer responsibilities.
- Disposable subagent delegation must include a complete task brief because subagents are stateless across calls.

### Tools and CLI

- The package must expose a usable CLI for operating the development-agent team.
- The system must expose Tavily-backed `web_search` and `fetch_url` tools when configured.
- Artifact templates must be available for the expected workflow documents.

### Readiness and governance

- The readiness gate must remain unapproved until explicit human approval is recorded.
- The system must document whether each readiness condition is satisfied, partial, blocked, or deferred.
- Implementation-mode tasks must have bounded ownership, scope, constraints, and acceptance criteria before assignment.

## Non-Functional Requirements

- Documentation accuracy: artifacts must reflect observed code state and known gaps.
- Safety: shaping mode must permit workflow-doc updates but not production-code implementation.
- Traceability: major product, planning, and readiness decisions must be recorded in versioned artifacts.
- Operability: CLI and checkpointing options must be understandable to an operator from docs.
- Testability: core workflow behavior should be covered by tests before V0 is represented as delivery-ready or production-ready; if tests require repository code changes, that work needs gate approval or an explicit shaping exception.
- Compatibility: the Python version requirement must be reviewed because `>=3.14` may limit adoption.
- Least privilege: implementation-mode write access should be scoped by task and role.

## Edge Cases

- A user asks to “update docs” while implementation code already exists; docs must reflect observed state without implying approval.
- A specialist lacks enough context; it must ask the engineering manager rather than inventing assumptions.
- The codebase and artifacts disagree; the mismatch must be documented as a gap or reconciliation task.
- A developer task is requested before gate approval; it must remain blocked until the readiness gate is approved.
- Tavily credentials are unavailable; web tools should be documented as configured capabilities, not guaranteed runtime availability.
- SQLite checkpointing is used across CLI restarts; artifacts still remain the durable source of truth.
- Python `>=3.14` blocks adoption in common environments; compatibility must be evaluated before release positioning.

## Acceptance Criteria

Documentation alignment is acceptable when:

- `product-brief.md` defines problem, target users, goals, non-goals, MVP scope, current state, and open questions.
- `requirements.md` captures functional requirements, non-functional requirements, edge cases, and acceptance criteria for V0.
- `prioritization.md` identifies MVP priorities, deferred work, risks, and sequencing.
- `task-breakdown.md` lists proposed tasks with dependencies, owner role, acceptance criteria, and draft/blocked status.
- `readiness-gate.md` explicitly states that implementation mode is not approved.
- Known gaps are visible: missing tests/CI, no coded readiness-gate enforcement, draft/unapproved artifacts, broad implementation write scope, and Python `>=3.14` adoption risk.
- No artifact claims production readiness or human approval.
