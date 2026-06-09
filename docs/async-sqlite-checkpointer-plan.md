# Async SQLite Checkpointer And Thread Namespace

## Goal

SQLite-backed teams use LangGraph `AsyncSqliteSaver` and a scoped checkpoint
namespace so several teams can intentionally point to the same `sqlite_path`
without checkpoint, conversation, relation-tool, or file-artifact collisions.

The implementation has one contract:

- LangGraph checkpoint rows are keyed by scoped physical thread ids.
- Application conversation rows are keyed by `(team_id, conversation_id, ...)`.
- Relation-tool edge rows include both `team_id` and `conversation_id`.
- Conversation files live under both team id and conversation id.
- SQLite LangGraph calls run through the async saver owner loop.

## Persistence Contract

One SQLite file may contain data for many teams and conversations. The SQLite
path is only a storage location; team identity comes from `team.yaml`, and
conversation identity comes from the active conversation id.

The physical LangGraph thread id includes the full application scope:

```text
ca:v1:team:<team_id>:conversation:<conversation_id>
ca:v1:team:<team_id>:conversation:<conversation_id>:branch:<branch_id>
ca:v1:team:<team_id>:conversation:<conversation_id>:branch:<branch_id>:mention:<agent_id>
ca:v1:team:<team_id>:conversation:<conversation_id>:branch:<branch_id>:mention:<agent_id>:relation:<relation_id>:agent:<target_agent_id>
```

Dynamic segments are URL-quoted with `quote(value, safe="-._~")`.

Logical thread keys remain conversation-relative because the store already has
team, conversation, and branch columns:

```text
mention:<agent_id>
mention:<agent_id>:relation:<relation_id>:agent:<target_agent_id>
```

## Thread Id Factory And Codecs

`ThreadIdFactory` is the stable public API for physical and logical id
construction:

```python
root(team_id=..., conversation_id=...)
branch(root_thread_id, branch_id)
mention(branch_thread_id, agent_id)
relation(parent_thread_id, relation)
logical_mention(agent_id)
logical_relation(parent_logical_key, relation)
parse(thread_id)
logical_thread_key(physical_thread_id)
```

Version-specific physical id parsing and writing lives under:

```text
src/team_instanciator/runtime/thread_ids/
```

Current files:

```text
thread_id_codec.py
thread_id_v1_codec.py
parsed_thread_id.py
```

`ThreadIdFactory` writes with the configured writer codec and parses through a
version registry. To add a new physical format, add a new codec class beside
`thread_id_v1_codec.py`, register it in `ThreadIdFactory`, and keep call sites
using the factory.

`parse(...)` returns the thread-id version, team id, conversation id, branch id,
mention agent id, and the relation chain. Nested relation ids are supported by
appending additional `:relation:<id>:agent:<agent>` segments.

All runtime call sites build thread ids through `ThreadIdFactory`:

- `MentionAwareTeam` creates the scoped root thread id.
- `MentionRouter` creates scoped mention physical ids.
- Prompt injection and checkpoint resume use conversation-relative logical keys.
- Activity and checkpoint history compute scoped ids when no branch-thread row
  exists.
- `BranchThreadResolver` parses scoped ids to recover conversation id.
- Relation tools derive child ids from the runtime parent physical id.

## Relation Tools

Relation tools are built before a concrete conversation is known, so they do not
store a static parent thread id. At runtime they require:

- `runtime.config["configurable"]["thread_id"]`;
- runtime metadata `team_id`;
- runtime metadata `conversation_id`;
- runtime metadata `branch_id`;
- runtime metadata `logical_thread_key`.

If any required scope value is missing, the tool fails with a clear error. This
keeps relation-tool calls tied to the exact LangGraph parent invocation.

Relation-tool locks are keyed by:

```text
(team_id, conversation_id, branch_id, child_logical_thread_key)
```

`ToolCallEdge` carries `team_id` and `conversation_id`, and
`tool_call_edges` uses this primary key:

```sql
primary key (team_id, conversation_id, id)
```

If a local `tool_call_edges` table exists without the scope columns,
`ConversationStore` drops and recreates that table before reconciliation. The
new schema is the only supported shape.

## Conversation Files

Conversation file artifacts are stored under:

```text
.coding-agents/conversations/<team_id>/<conversation_id>/files
```

Generated public files and copied input attachments both use this directory.
Agent sync payloads expose matching scoped read paths:

```text
/.coding-agents/conversations/<team_id>/<conversation_id>/files/<file_id>
```

## Async SQLite Checkpointer

SQLite-backed teams use `AsyncSqliteSaver`, owned by
`AsyncCheckpointerLoop`.

`AsyncCheckpointerLoop` owns:

- a background asyncio event loop;
- one `aiosqlite.Connection`;
- one `AsyncSqliteSaver`;
- a blocking `run(...)` method for sync orchestration code;
- an idempotent `close(...)` method.

The saver is constructed inside the background loop because
`AsyncSqliteSaver.__init__` captures the running event loop. SQLite graph
invocations are then scheduled onto that same loop.

`CheckpointerFactory` now opens two connections for SQLite teams:

- a sync `sqlite3.Connection` for `ConversationStore`, manifest persistence,
  checkpoint history, branch forking, and app-owned tables;
- an async `aiosqlite.Connection` for LangGraph checkpointing.

Both connections set `busy_timeout`. LangGraph setup enables WAL through the
async saver.

`CheckpointerHandle` contains:

```python
checkpointer: object
connection: sqlite3.Connection | None
async_runner: AsyncCheckpointerLoop | None
```

Close order is:

1. Drain conversation router work.
2. Close async checkpointer resources.
3. Close the sync SQLite connection.

## Graph Invocation

`invoke_graph_sync(...)` accepts an optional async runner.

Rules:

- When `async_runner` is present, `graph.ainvoke(...)` is required and runs on
  the runner loop.
- When `async_runner` is absent, existing memory-backed behavior remains
  synchronous unless the graph itself only exposes async invocation.
- Async graph exceptions propagate unchanged.

The async runner is passed through:

- `MentionRouter._run_agent(...)`;
- `MentionAwareTeam.inject_agent_prompt(...)`;
- `MentionAwareTeam.resume_checkpoint(...)`;
- `RelationTool.run(...)`.

Relation tools receive the runner through both creation paths:

```text
AgentGraphRegistry -> RelationToolFactory -> RelationTool
SubagentFactory -> RelationToolFactory -> RelationTool
```

## Studio And Checkpoint History

Studio checkpoint history reads only scoped physical thread ids:

- computed scoped mention ids for current participants;
- persisted `team_conversation_branch_threads.physical_thread_id` values for
  relation and forked branch histories.

History queries keep filtering by the current branch, and Studio payloads keep
returning physical thread ids for inspection and checkpoint operations.

Private-message activity also reads `writes` by scoped physical thread id. For
focused agent activity, the runtime uses the stored branch-thread physical id
when present and computes a scoped mention id only for an empty thread.

## Branching And Forking

`ThreadForker` remains synchronous because it copies rows through the app-owned
sync SQLite connection.

Branch-thread rows store:

- conversation-relative `logical_thread_key`;
- scoped `physical_thread_id`;
- fork source metadata;
- the creating run or relation commit id.

Branch-thread uniqueness remains:

```text
(team_id, conversation_id, branch_id, logical_thread_key)
```

## Verification

Commands run:

```bash
uv run python -m unittest discover tests/team_instanciator
uv run python -m unittest tests.webapp_studio.test_backend_api tests.webapp_studio.test_local_launcher
uv run python -m unittest discover tests/webapp
```

Additional full discovery was attempted:

```bash
uv run python -m unittest discover tests
```

That command still hits repository-level discovery import errors unrelated to
this change:

- `teams.philosophers.conversation_counter_tools` is not importable as
  `teams.philosophers...`;
- `webui.pricing` is not importable as `webui.pricing`;
- `webui.server` is not importable as `webui.server`.

The real-team Studio launcher smoke now starts with the existing root `.env`
and the local SQLite file.

## Manual Smoke

From a workspace that uses a shared SQLite path:

1. Start Studio without an explicit team file.
2. Create a philosophers conversation and ping `@Francis`.
3. Confirm no `SqliteSaver does not support async methods` error appears.
4. Create another team conversation using the same SQLite path.
5. Confirm both conversations appear in Studio history.
6. Create a branch from a checkpoint and resume it.
7. Attach or generate files under both teams using the same conversation id.
8. Confirm checkpoint thread ids and file paths include the correct team id.

Useful inspection query:

```sql
select thread_id, checkpoint_ns, checkpoint_id
from checkpoints
order by thread_id, checkpoint_id
limit 50;
```

Expected thread-id prefixes:

```text
ca:v1:team:<team-a>:conversation:<conversation-id>:...
ca:v1:team:<team-b>:conversation:<conversation-id>:...
```
