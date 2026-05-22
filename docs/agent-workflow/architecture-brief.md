# Architecture Brief

Status: draft

## Context

The V0 development-agent team is a reusable Python module with a minimal
interactive CLI. The engineering manager is the main Deep Agent. Product and
architecture collaborators must behave like resident teammates rather than
stateless subagents, because they may need to ask follow-up questions and
continue a shaping discussion over multiple turns.

The engineering manager must also be able to inspect the actual codebase before
answering status, progress, readiness, or implementation-gap questions. A scout
subagent provides this fast reconnaissance and returns compressed context for
handoff.

## Constraints

- Keep implementation lightweight for local development.
- Preserve product and architecture conversation history across CLI restarts.
- Keep repository artifacts as the durable source of truth.
- Provide a path to shared or production deployments.
- Do not rely on documentation alone when the human asks where implementation
  stands.

## Proposed Architecture

Use a LangGraph checkpointer shared by the engineering manager and resident
product and architecture agents. SQLite is the default V0 backend for local
durable thread state. The product analyst and software architect use stable
thread IDs derived from the manager thread ID:

```text
<manager-thread-id>:resident:product-analyst
<manager-thread-id>:resident:software-architect
```

Keep a Postgres checkpointer adapter available for production or shared
deployments.

Add a disposable `scout` subagent exposed through the manager's `task` tool. The
scout uses scoped reconnaissance tools (`ls`, `read_file`, `glob`, `grep`,
read-only `execute`, `web_search`, `fetch_url`) and a medium-reasoning model by
default. The manager calls it before answering codebase status questions and
then compares docs state with code state.

## Options Considered

| Option | Pros | Cons | Decision |
| --- | --- | --- | --- |
| SQLite checkpointer | Simple local persistence, no external service, good CLI default | Single-file local storage, not ideal for multi-user deployments | Selected for V0 |
| Postgres checkpointer | Production-ready shared persistence | Requires database provisioning and connection configuration | Available adapter |
| In-memory checkpointer | Minimal setup, useful for tests | Loses resident conversations on restart | Supported for tests only |
| Scout subagent | Forces actual codebase inspection before status answers, returns compact handoff context | Adds one extra agent call for status/progress questions | Selected for V0 |

## Risks

- SQLite files should be treated as local working memory, not the project source
  of truth.
- Decisions and clarifications must still be written to versioned artifacts.
- Postgres setup needs explicit database credentials before it can be used.
- Scout output is still a compressed reconnaissance report; high-risk claims may
  require direct follow-up reads by the manager or another specialist.
