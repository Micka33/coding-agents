# Decision Log

Status: draft

## Status Legend

- `approved`: decision is accepted as current project direction.
- `proposed`: decision is recommended but still needs explicit approval or
  ratification.
- `implemented`: observed in code.
- `partial`: partially observed in code or documentation.
- `missing`: not observed in code.

## Decisions

### DEC-0001: SQLite checkpointing for resident agent memory

Decision status: approved  
Implementation status: implemented

Context:

Product and architecture agents need to stay alive as collaborators. They may
ask follow-up questions, receive clarifications from the engineering manager,
and continue the same shaping discussion later. Stateless Deep Agents subagents
do not preserve that conversational continuity.

Decision:

Use SQLite-backed LangGraph checkpointing as the default V0 persistence layer
for the engineering manager and resident product and architecture agents. Keep a
Postgres checkpoint adapter installed and configurable for future shared or
production deployments. Keep an in-memory option available for tests or
disposable sessions.

Options considered:

- SQLite checkpointer.
- Postgres checkpointer.
- In-memory checkpointer.

Selected option:

- SQLite as the local V0 default, with Postgres available for shared/production
  deployments and memory available for tests.

Rejected options:

- Postgres-only persistence for V0, because it adds unnecessary local setup.
- In-memory-only persistence, because resident collaborators need continuity
  across CLI restarts.

Rationale:

SQLite satisfies the local-first V0 goal without external infrastructure while
still allowing durable resident conversations. Repository artifacts remain the
source of truth for durable decisions.

Consequences:

- Local CLI restarts can preserve resident product and architecture thread
  history.
- The default setup does not require provisioning external infrastructure.
- Postgres can be enabled by configuration when the system needs shared durable
  persistence.
- Versioned repository artifacts remain the source of truth for approved
  decisions and requirements.

### DEC-0002: Scout subagent for codebase reconnaissance

Decision status: approved  
Implementation status: implemented

Context:

The engineering manager may be asked where implementation stands. Answering from
workflow artifacts alone can be misleading when the codebase has advanced beyond
the docs or when docs are stale.

Decision:

Add a disposable `scout` subagent that performs fast codebase reconnaissance and
returns compressed context for handoff to the engineering manager or another
agent. The manager must call the scout for status, progress, readiness, or gap
analysis questions unless the human explicitly asks for docs-only analysis.

Options considered:

- Manager manually reads docs and code with generic filesystem tools.
- Add a read-only status snapshot tool.
- Add a scout subagent with codebase reconnaissance instructions.

Selected option:

- Disposable scout subagent with scoped reconnaissance tools.

Rejected options:

- Docs-only status answers, because they can be stale.
- Manual manager-only reconnaissance as the default, because it increases prompt
  bloat and reduces repeatability.

Rationale:

The scout creates a consistent codebase-fact gathering step while keeping final
interpretation and decision-making with the engineering manager.

Consequences:

- Status answers must compare documented state with actual code state.
- The manager can delegate context-gathering without bloating its own prompt.
- Scout remains disposable and does not own product or architecture decisions.
- Scout `execute` access must remain constrained to reconnaissance commands.

### DEC-0003: Ratify reusable Python package plus CLI as the V0 delivery shape

Decision status: proposed  
Implementation status: implemented

Context:

The codebase already exists largely as a reusable Python package under
`coding_agents/` plus a minimal interactive CLI. The previous workflow artifacts
did not explicitly record this as the delivery shape.

Decision:

Ratify the reusable Python package plus CLI as the V0 delivery shape.

Options considered:

- One-off script.
- Reusable Python package with CLI.
- Hosted service or web UI.

Selected option:

- Reusable Python package with a minimal CLI.

Rejected options:

- One-off script, because it would make testing, reuse, and future integrations
  harder.
- Hosted service or web UI for V0, because it adds deployment, auth, and product
  surface area not needed for the local-first architecture.

Rationale:

The package-plus-CLI shape matches the observed implementation, keeps local
setup lightweight, and provides a stable boundary for tests and future tools.

Consequences:

- Package APIs and CLI behavior become part of the V0 contract.
- Packaging metadata, runtime version support, and CLI smoke tests become
  release-relevant.
- Future UI or service entrypoints should wrap the package rather than duplicate
  agent wiring.

### DEC-0004: Machine-enforce readiness before implementation mode

Decision status: proposed  
Implementation status: missing

Context:

The readiness gate is documented but not observed as coded enforcement. The
system is currently in shaping mode, and implementation tasks should not be
assigned until the human approves the gate.

Decision:

Add machine-readable readiness state and runtime enforcement so implementation
mode cannot delegate developer work or grant implementation write permissions
until the readiness gate is approved.

Options considered:

- Documentation-only readiness convention.
- Machine-readable readiness file plus runtime guard.
- Manual human approval outside the repository.

Selected option:

- Machine-readable readiness file plus runtime guard.

Rejected options:

- Documentation-only convention, because it is easy to bypass accidentally.
- External-only approval, because it does not give agents a durable source of
  truth inside the repository.

Rationale:

The readiness rule is a core governance control. It should be enforced by code,
not only by instructions.

Consequences:

- The engineering manager must fail closed when readiness is not approved.
- Developer, reviewer, QA, DevOps, security, and writer subagents should only be
  activated for implementation after approval.
- The readiness artifact must be kept synchronized with any machine-readable
  gate representation.

### DEC-0005: Tighten implementation-mode write scopes

Decision status: proposed  
Implementation status: partial

Context:

Mode-aware permissions are present, but implementation-mode write permissions are
currently broad. Broad writes increase the risk that implementation subagents
modify unrelated files or cross module boundaries.

Decision:

Require task-scoped write allowlists for implementation work. Each developer task
brief must identify files or modules in scope, files or modules out of scope,
constraints, and acceptance criteria before write permissions are granted.
Implementation subagents may request access to additional files or modules, but
must do so through the engineering manager with a concise justification, the
specific files or paths requested, the reason the current scope is insufficient,
and the risk of not granting access. The engineering manager may consult the
software architect and product analyst before approving the expansion,
suggesting an alternate solution, splitting the task, or escalating to the
human.

Options considered:

- Broad implementation-mode write access.
- Role-scoped write profiles.
- Task-scoped write allowlists.

Selected option:

- Task-scoped write allowlists, with role-specific defaults where useful.
- Manager-mediated scope expansion requests, with product/architecture
  consultation when the request may change scope, boundaries, or tradeoffs.

Rejected options:

- Broad write access, because it weakens governance and makes review harder.
- Role-only scoping, because two tasks owned by the same role may still require
  different boundaries.

Rationale:

Task-scoped write permissions align implementation authority with the approved
brief and reduce accidental cross-cutting changes.

Consequences:

- Task briefs become permission inputs, not just planning documents.
- The engineering manager must validate scopes before delegation.
- Subagents can request additional access, but cannot grant it to themselves.
- Scope expansion decisions must be documented when they change product,
  architecture, planning, or delivery context.
- Some implementation tasks may need to be split when their write scopes overlap
  too broadly.

### DEC-0006: Ratify or adjust the Python runtime floor

Decision status: proposed  
Implementation status: partial / risky

Context:

A Python `>=3.14` runtime requirement was observed as a potential adoption risk.
Python version support affects contributor setup, CI availability, dependency
compatibility, and package usability.

Decision:

Do not treat Python `>=3.14` as settled for release readiness until a runtime
compatibility review ratifies it or proposes a lower supported range.

Options considered:

- Keep Python `>=3.14`.
- Lower the minimum to an older supported Python version.
- Support a tested version range across multiple Python versions.

Selected option:

- Proposed: perform a compatibility review before release readiness, then either
  ratify Python `>=3.14` or update the supported range.

Rejected options:

- Treat the current runtime floor as final without review.

Rationale:

Runtime support is a structural adoption choice. It should be explicit and
validated rather than an accidental packaging default.

Consequences:

- CI should test the ratified Python version or version range.
- Package metadata and documentation must match the ratified runtime support.
- A lower version range may require dependency or syntax compatibility checks.
