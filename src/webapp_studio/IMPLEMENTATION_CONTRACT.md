# Webapp Studio Implementation Contract

Draft date: 2026-06-01

This document is the implementation companion to `PROJECT_PLAN.md`. It turns the
remaining planning gaps into contracts and operating rules so the backend can be
built first, the frontend can rely on stable shapes, and later LangGraph-native
features can arrive without rewriting the product surface.

## Contract Principles

- Version the studio API under `/api/studio/v1`. Breaking changes require a new
  prefix. Additive fields are allowed inside v1.
- Backend DTOs are canonical Pydantic models. The frontend mirrors them through
  generated JSON Schema or checked TypeScript fixtures, not hand-maintained guess
  types.
- Every top-level response includes `schema_version: "studio.v1"` and
  `capabilities`, so unsupported advanced features are explicit instead of
  silently represented as empty data.
- Use stable opaque identifiers for events, runs, checkpoints, branches, queue
  items, files, artifacts, generated UI specs, and interrupt requests. Do not
  encode behavior into IDs.
- Prefer append-only event and history models. Mutable resources expose
  `updated_at` and preserve enough audit metadata for debugging.
- Unknown fields must be ignored by clients and preserved by backend pass-through
  code where possible.
- Feature status is represented with capability flags:
  `available`, `degraded`, `unsupported`, or `planned`.

## Resolved Open Decisions

- Use a studio-native API as the durable product contract, with a
  LangGraph-compatible adapter for `@langchain/react`. Do not clone LangGraph
  Agent Server routes exactly unless a later compatibility layer explicitly
  needs them.
- Fully usable branch creation, branch switching, checkpoint resume, edit,
  regenerate, and time travel are first-version requirements.
- Manage backend dependencies from the root `pyproject.toml` with `uv`; do not
  introduce a nested backend `pyproject.toml` for the first build.
- Use Pydantic DTOs plus shared JSON fixtures as the first Python/TypeScript
  type-sharing strategy.
- Keep right-to-left frontend support intentionally enabled.
- Use `teams/conversing_philosophers/team.yaml` as the required real-team
  parity and smoke-test target.
- Add backend redaction helpers for common sensitive activity fields, then allow
  explicit per-tool sensitive-field metadata later.

## 1. LangGraph-Compatible API Contract

The API should expose studio-native local endpoints while keeping the payload
concepts close enough to LangGraph Agent Server concepts to support an adapter:
runs, stream modes, checkpoints, branches, interrupts, and state history.

### Endpoint Table

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/studio/v1/health` | Process health, versions, and feature capabilities. |
| `GET` | `/api/studio/v1/state` | Complete conversation snapshot for initial page load and fallback refresh. |
| `GET` | `/api/studio/v1/activity` | Activity snapshot, optionally filtered by `agent_id`. |
| `POST` | `/api/studio/v1/messages` | Append a human message and enqueue/dispatch mentioned agents. |
| `PATCH` | `/api/studio/v1/runtime` | Update mention hook and cascade settings. |
| `POST` | `/api/studio/v1/agents/{agent_id}/stop` | Request cancellation for an active agent run. |
| `GET` | `/api/studio/v1/stream` | SSE stream for snapshot diffs, runs, queues, activity, and generated UI patches. |
| `GET` | `/api/studio/v1/runs` | Active and recent runs, including reconnect metadata. |
| `POST` | `/api/studio/v1/runs/{run_id}/join` | Rejoin an active run and receive replay cursor metadata. |
| `GET` | `/api/studio/v1/queue` | Queue snapshot with positions and failed entries. |
| `DELETE` | `/api/studio/v1/queue/{queue_item_id}` | Cancel a queued entry when cancellation is supported. |
| `POST` | `/api/studio/v1/queue/clear` | Clear failed or pending queue entries according to request scope. |
| `GET` | `/api/studio/v1/checkpoints` | Checkpoint timeline for the current conversation/thread. |
| `GET` | `/api/studio/v1/checkpoints/{checkpoint_id}` | Checkpoint detail and summarized state metadata. |
| `POST` | `/api/studio/v1/checkpoints/{checkpoint_id}/resume` | Resume from a checkpoint when supported. |
| `GET` | `/api/studio/v1/branches` | Branch list and current branch pointer. |
| `POST` | `/api/studio/v1/branches` | Create a branch from a checkpoint or message edit. |
| `POST` | `/api/studio/v1/branches/{branch_id}/switch` | Switch the visible branch. |
| `POST` | `/api/studio/v1/branches/{branch_id}/archive` | Archive a non-current branch without deleting its persisted history. |
| `GET` | `/api/studio/v1/interrupts` | Active human-review interrupts. |
| `POST` | `/api/studio/v1/interrupts/{interrupt_id}/resume` | Approve, reject, edit, or respond to an interrupt. |
| `GET` | `/api/studio/v1/files/{file_id}` | Serve public conversation attachments with authorization and content checks. |

Keep existing `/api/state`, `/api/activity`, `/api/messages`, `/api/runtime`, and
`/api/stop` compatibility endpoints available behind typed controller methods
until the studio replaces the old webapp launch path.

### Response Envelope

Use an envelope for studio endpoints, except raw file downloads and SSE frames.
This example shows a pre-V1 contract-slice response where some first-version
features are not implemented yet:

```json
{
  "schema_version": "studio.v1",
  "request_id": "req_01H...",
  "capabilities": {
    "streaming": "available",
    "queue_control": "degraded",
    "interrupts": "degraded",
    "checkpoints": "degraded",
    "branching": "degraded",
    "time_travel": "degraded",
    "generated_ui": "degraded"
  },
  "data": {},
  "errors": []
}
```

Errors use a stable shape:

```json
{
  "code": "invalid_request",
  "message": "agent_id is required",
  "field": "agent_id",
  "retryable": false,
  "details": {}
}
```

### Core DTOs

`StudioState` wraps the current `ConversationStateDict` instead of replacing it
immediately:

```json
{
  "team_id": "team",
  "conversation_id": "thread",
  "participants": ["agent-a"],
  "runtime": {},
  "conversation": {
    "events": [],
    "deliveries": [],
    "agent_states": []
  },
  "activity": {
    "active_agent_ids": [],
    "private_threads": []
  },
  "runs": [],
  "queue": [],
  "history": {
    "current_branch_id": "branch_main",
    "checkpoints": [],
    "branches": []
  },
  "generated_ui": []
}
```

Important DTO rules:

- Keep legacy event, delivery, and agent-state fields structurally compatible
  with the current runtime.
- Add studio-specific metadata beside legacy objects, not inside them, until the
  runtime owns the fields directly.
- `created_at`, `updated_at`, `completed_at`, and `observed_at` are ISO 8601 UTC
  strings.
- Client-visible ordering uses explicit numeric sequence fields when available.
  Timestamps are display data, not ordering authority.

## 2. Checkpoint, Branch, And Time-Travel Feasibility

The first version must model these resources, but it must be honest about what
the current runtime can actually do.

### Capability Levels

| Feature | First-Version Contract | Pre-V1 Runtime Behavior |
| --- | --- | --- |
| Checkpoint listing | Available. | Derive timeline from LangGraph checkpoint tables and metadata when connection access exists. |
| Checkpoint detail | Available. | Return metadata and summarized writes first; add full state reconstruction before first-version completion. |
| Resume from checkpoint | Available. | May return `unsupported_feature` only in pre-V1 contract-slice builds. |
| Branch listing | Available. | Expose `branch_main` until real branches are persisted. |
| Branch creation | Available. | May return explicit unsupported response only in pre-V1 contract-slice builds. |
| Branch switching | Available. | May return explicit unsupported response only in pre-V1 contract-slice builds. |
| Edit/regenerate from branch | Available. | May return explicit unsupported response only in pre-V1 contract-slice builds. |
| Time-travel inspection | Available. | Show timeline/checkpoint summaries first. |
| Time-travel resume | Available. | May return explicit unsupported response only in pre-V1 contract-slice builds. |

Do not fabricate branch trees. If the runtime cannot distinguish branches yet,
return a single branch during pre-V1 development:

```json
{
  "id": "branch_main",
  "label": "Main",
  "parent_branch_id": null,
  "origin_checkpoint_id": null,
  "current": true,
  "status": "derived"
}
```

### History DTOs

`CheckpointSummary`:

```json
{
  "id": "checkpoint_...",
  "thread_id": "thread:mention:agent-a",
  "checkpoint_ns": "",
  "parent_checkpoint_id": "checkpoint_parent",
  "seq": 42,
  "created_at": "2026-06-01T10:00:00Z",
  "source": "langgraph_sqlite",
  "metadata": {},
  "summary": {
    "message_count": 12,
    "tool_call_count": 3,
    "agent_id": "agent-a",
    "event_id": "event_..."
  },
  "capabilities": {
    "inspect": "available",
    "resume": "available",
    "branch_from_here": "available"
  }
}
```

`BranchSummary`:

```json
{
  "id": "branch_main",
  "label": "Main",
  "parent_branch_id": null,
  "origin_checkpoint_id": null,
  "created_at": "2026-06-01T10:00:00Z",
  "current": true,
  "status": "derived",
  "head_checkpoint_id": "checkpoint_...",
  "archived_at": null
}
```

Maintainability rule: history adapters must be read-only first. Mutation
operations for resume, regenerate, edit, and branch creation should be separate
service methods with tests that prove they do not corrupt the active
conversation. The read-only adapter is a development milestone, not the
first-version finish line.

## 3. Streaming Mechanics

Use Server-Sent Events for the local backend because it is simple, observable,
and compatible with a Next.js client running in the browser. WebSockets can be
added later behind the same event DTOs if bidirectional streaming becomes useful.

### Stream Request

`GET /api/studio/v1/stream?conversation_id=thread&cursor=event_seq:42`

Supported request headers:

- `Last-Event-ID`: last delivered stream event ID.
- `Accept: text/event-stream`.

Supported query params:

- `cursor`: opaque replay cursor from a previous stream frame or join response.
- `run_id`: optional active run to prioritize on reconnect.
- `agent_id`: optional activity filter.

### SSE Frame Format

```text
id: stream_00000043
event: conversation.event.appended
data: {"schema_version":"studio.v1","cursor":"event_seq:43","payload":{}}
```

Use these initial event names:

| Event | Meaning |
| --- | --- |
| `studio.hello` | Stream accepted, capabilities and initial cursor. |
| `studio.heartbeat` | Keepalive every 15 seconds while connected. |
| `snapshot.replace` | Full snapshot for initial connect or unrecoverable cursor gap. |
| `conversation.event.appended` | Public transcript event appended. |
| `conversation.delivery.updated` | Agent delivery status changed. |
| `agent.state.updated` | Running, queued, stopped, or token-estimate state changed. |
| `activity.private_message.appended` | Private thread gained an observable message summary. |
| `run.started` | Run metadata became active. |
| `run.updated` | Run status, checkpoint, interrupt, or stream metadata changed. |
| `run.completed` | Run completed, failed, stopped, or was superseded. |
| `queue.updated` | Queue snapshot or queue item changed. |
| `checkpoint.observed` | New checkpoint discovered from checkpointer state. |
| `branch.updated` | Branch metadata changed. |
| `interrupt.created` | Human review needed. |
| `interrupt.resolved` | Human review resolved. |
| `generated_ui.patch` | JSON Patch operation for a generated UI spec. |
| `generated_ui.validated` | Spec is valid and can be displayed. |
| `studio.error` | Recoverable stream-level error. |

### Replay And Retention

- Maintain an in-memory ring buffer of recent stream frames per conversation.
- Minimum retention: 500 frames or 10 minutes, whichever is larger in practice
  for the local process.
- If a cursor cannot be replayed, send `snapshot.replace` and continue from the
  latest cursor.
- `POST /runs/{run_id}/join` returns the best cursor for reconnecting to that
  run.
- Stream IDs are monotonic within a backend process. They do not need to survive
  process restarts, because the snapshot endpoint is the durable fallback.

### Runtime Bridge

The current runtime does not emit all required events directly. Implement a
bridge in layers:

1. Wrap write operations such as message append, runtime update, stop, and queue
   mutation to publish deterministic stream events.
2. Poll checkpointer-derived private activity and history on a modest interval
   while agents are running.
3. Diff snapshots to discover changes that the current runtime does not notify
   yet.
4. Later replace polling/diffing with native runtime event hooks.

Concurrency rules:

- Stream publishing must never block agent execution.
- Slow clients get dropped after a bounded send queue fills.
- Agent stop and queue mutation endpoints must be idempotent where possible.
- Heartbeats continue during long agent runs.

## 4. Dependency And Developer Workflow

The project remains Python-first, with the studio split into backend and
frontend folders for ownership clarity.

### Backend

Use the root project as the source of truth for Python package ownership. Add
FastAPI and local server dependencies to the root `pyproject.toml` unless a
future packaging need requires publishing `src/webapp_studio/backend` as an
independent app.

Recommended dependencies:

- `fastapi`
- `uvicorn[standard]`
- `pydantic`
- `sse-starlette` only if FastAPI's native streaming response becomes too
  low-level for clean SSE handling.

Backend module path:

```text
src/webapp_studio/backend/
  server.py
  application/
  api/
  contracts/
  history/
  streaming/
```

Do not add `src/webapp_studio/backend/pyproject.toml` in the first build. A
nested project can be introduced later only if the backend needs independent
packaging or deployment.

### Frontend

Pin frontend tooling after scaffold generation:

- `next`
- `react`
- `react-dom`
- `typescript`
- `tailwindcss`
- `@langchain/react`
- `@json-render/shadcn`
- shadcn/ui component files committed into the repo
- AI Elements component files committed into the repo

Use `pnpm-lock.yaml` and avoid unpinned `@latest` after the initial scaffold.
The plan's scaffold commands are acceptable for bootstrapping, but the generated
`package.json` and lockfile become the durable contract.

Right-to-left support is intentional. Keep the shadcn `--rtl` scaffold behavior
and verify that layout primitives do not assume left-to-right positioning.

### Local Commands

Target command shape:

```bash
uv run python -m src.webapp_studio.backend.server team.yaml --port 8765
pnpm --dir src/webapp_studio/frontend dev --port 3765
```

The eventual one-command launcher should:

- Start FastAPI first and wait for `/health`.
- Start Next.js second with `STUDIO_API_BASE_URL`.
- Print both URLs and the selected `team.yaml`.
- Forward shutdown to both processes.
- Preserve current CLI ergonomics: `team.yaml`, `--thread-id`, `--host`,
  `--port`, `--var`, and `--no-env-file`.

## 5. Security Boundaries

The studio is local-first, but it still renders model output and serves files, so
the boundaries should be explicit from the beginning.

### Attachments And Files

- Store public attachments under the existing conversation file area.
- Enforce maximum request size before decoding base64 content.
- Start with a conservative default max attachment size of 10 MiB per file and
  25 MiB per request.
- Serve only known conversation file IDs. Never serve arbitrary filesystem paths.
- Set `Content-Type` from stored media type or safe sniffing fallback.
- Add `Content-Disposition: attachment` for unknown or risky types.
- Do not inline HTML, SVG, or JavaScript attachments unless a later explicit safe
  preview pipeline exists.

### Markdown

- Parse Markdown with GFM support.
- Sanitize rendered HTML with a strict allowlist.
- Disable raw HTML by default.
- Links open in a new tab with `rel="noopener noreferrer"`.
- Code blocks are text-only display; no automatic execution.

### Generated UI

- Only render component names from the closed catalog.
- Validate every spec against JSON Schema before display.
- Validate JSON Patch operations before applying them.
- Bind actions by explicit action IDs. No arbitrary JavaScript, dynamic imports,
  string-evaluated handlers, or unregistered event names.
- Generated controls may call only registered backend actions. Each action
  declares input schema, confirmation requirement, and audit behavior.
- Invalid specs render a readable fallback with validation errors, not a broken
  or partially trusted UI.

### Activity And Reasoning

- Private activity is visible in the Activity tab but remains separate from the
  public transcript.
- Do not expose hidden model internals as reasoning. Only render
  reasoning-style blocks when the backend deliberately marks a block as safe to
  display.
- Tool input/output cards should redact fields marked sensitive by the backend.
- Add a backend redaction helper for common sensitive key names before rich tool
  cards ship: `api_key`, `apikey`, `token`, `secret`, `password`,
  `authorization`, `cookie`, `set-cookie`, and `credential`.
- Redaction should preserve structure while replacing values with
  `[redacted]`, so the Activity tab remains useful for debugging.
- Later, tools may provide explicit sensitive-field paths that are applied in
  addition to the common-name helper.

### Browser Policy

Use conservative frontend headers where practical in local development:

- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- A CSP that allows the local frontend/backend origins and blocks inline script
  except what Next.js development mode requires.

## 6. Phase Acceptance Criteria

### Phase 1: Contract Design Is Done When

- Pydantic DTOs exist for state, events, activity, deliveries, files, runtime
  settings, stream frames, runs, queue items, checkpoints, branches, interrupts,
  generated UI specs, and errors.
- JSON fixtures exist for each DTO family under a shared contract fixture
  directory.
- Tests prove all fixtures validate through Pydantic.
- TypeScript validation or fixture tests consume the same JSON fixtures.
- The API endpoint table above is represented in code-level route names or test
  names, even if some routes return `unsupported_feature`.
- Capability flags distinguish real, degraded, planned, and unsupported
  features.
- Contract fixtures include branch/resume/edit/regenerate examples even before
  mutation handlers are fully implemented.

### Phase 2: Backend API Is Done When

- FastAPI serves `/health`, `/state`, `/activity`, `/messages`, `/runtime`,
  `/agents/{agent_id}/stop`, and `/stream`.
- Compatibility endpoints still pass the existing old-webapp behavioral tests
  through typed controller methods.
- SSE emits `studio.hello`, heartbeats, snapshot replacement, and deterministic
  events after message append, runtime update, and stop.
- Queue, checkpoint, branch, interrupt, and generated UI endpoints return valid
  envelopes with honest capabilities, even when mutation operations are not yet
  supported.
- Attachment upload and file-serving limits are tested.
- API error responses use the standard error shape.

### Phase 3: Frontend Scaffold Is Done When

- Next.js loads against mocked fixtures without requiring a live team.
- The frontend has a typed API client and fixture-backed DTO tests.
- Chat, Activity, and Generated UI tabs exist.
- Chat renders public messages, attachments, runtime controls, connection state,
  and stale snapshot state.
- Activity renders per-agent private activity as selectable read-only content.
- Generated UI renders valid fixture specs and readable validation fallbacks.
- Vitest covers DTO validation and basic reducers/hooks.
- Playwright smoke tests cover desktop and mobile first paint without layout
  overlap.

### Phase 4: Local Orchestration Is Done When

- One command starts backend and frontend for a selected `team.yaml`.
- Shutdown closes the instantiated team and both local servers.
- Ports can be configured and conflicts produce clear errors.
- The launcher preserves current webapp CLI arguments.

### Phase 5: Streaming Adapter Is Done When

- Public messages and agent activity update through SSE without polling in the
  product path.
- Reconnect with `Last-Event-ID` or cursor replays recent frames.
- Cursor gaps fall back to `snapshot.replace`.
- Active run IDs survive page refresh through `/runs` and `/runs/{run_id}/join`.
- Long-running agents keep heartbeats flowing.

### Phase 6: Rich Rendering Is Done When

- Markdown is sanitized and supports GFM tables, task lists, links, and code
  blocks.
- Known tool calls render specialized cards.
- Unknown tools render a generic JSON inspector.
- Reasoning-style blocks appear only when explicitly exposed by the backend.

### Phase 7: Advanced Workflows Are Done When

- HITL cards can approve, reject, edit, and respond to backend interrupts.
- Queue entries show order, state, cancellation support, and failure details.
- Checkpoint timeline shows derived checkpoint metadata.
- Branch and time-travel controls disable or explain unsupported actions rather
  than pretending they work during pre-V1 development.
- When mutation support is implemented, tests prove active conversation state is
  not corrupted by branch/resume operations.
- Before first-version completion, branch creation, branch switching, checkpoint
  resume, edit, regenerate, and time-travel resume are end-to-end usable against
  the local runtime.

### Phase 8: Generative UI Is Done When

- The catalog is versioned and closed by default.
- Specs and JSON Patch streams validate before display.
- Registered generated actions have schemas, audit entries, and optional
  confirmation requirements.
- Invalid specs produce readable fallbacks.
- Chat hints focus matching generated components in the Generated UI tab.

### Phase 9: Migration Is Done When

- Parity tests pass against fake conversations and at least one real team config.
- The required real-team parity target is
  `teams/conversing_philosophers/team.yaml`.
- The studio launch path is documented and can replace the old webapp launcher.
- The old `src/webapp` remains unchanged as the comparison artifact until an
  explicit removal decision is made.

## First Implementation Slice

Implement in this order:

1. Add backend Pydantic contract models and JSON fixtures.
2. Add fixture validation tests.
3. Add FastAPI app shell with `/health` and envelope/error helpers.
4. Add typed adapters over current state, activity, message append, runtime, and
   stop behavior.
5. Add SSE frame model and an in-memory stream buffer with hello, heartbeat, and
   snapshot events.

This slice gives the frontend a durable target while keeping advanced features
modeled as honest capabilities until the runtime can support them directly.
