# Decision Log

Status: draft

## Decisions

### DEC-0001: SQLite checkpointing for resident agent memory

Status: approved

Context:

Product and architecture agents need to stay alive as collaborators. They may
ask follow-up questions, receive clarifications from the engineering manager,
and continue the same shaping discussion later. Stateless Deep Agents subagents
do not preserve that conversational continuity.

Decision:

Use SQLite-backed LangGraph checkpointing as the default V0 persistence layer
for the engineering manager and resident product and architecture agents. Keep a
Postgres checkpoint adapter installed and configurable for future shared or
production deployments.

Options considered:

- SQLite checkpointer
- Postgres checkpointer
- In-memory checkpointer

Consequences:

- Local CLI restarts can preserve resident product and architecture thread
  history.
- The default setup does not require provisioning external infrastructure.
- Postgres can be enabled by configuration when the system needs shared durable
  persistence.
- Versioned repository artifacts remain the source of truth for approved
  decisions and requirements.

### DEC-0002: Scout subagent for codebase reconnaissance

Status: approved

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

Consequences:

- Status answers must compare documented state with actual code state.
- The manager can delegate context-gathering without bloating its own prompt.
- Scout remains disposable and does not own product or architecture decisions.
- Scout `execute` access must remain constrained to reconnaissance commands.
