# Webapp Studio Project Plan

Draft date: 2026-06-01

## Goal

Build a more modern and advanced successor to `src/webapp` for the mention-router
conversation runtime. The app should keep a local FastAPI backend workflow while
adding a dedicated Next.js frontend, LangGraph-compatible streaming, agent
observability, richer AI-native components, human review, queue management,
branching, time travel, and a separate safe generative UI workspace.

## Current App Baseline

`src/webapp` currently provides:

- Python standard-library HTTP server and CLI launcher.
- Static HTML, CSS, and vanilla JavaScript frontend.
- REST endpoints for state, activity, message append, runtime settings, and stop.
- Public transcript rendering with mentions and attachments.
- Mention suggestions, mention-hook toggle, cascade limit, and an activity panel.
- Polling every 1.5 seconds rather than true streaming.

This is a good compatibility base, but it has limited state modeling, no typed
frontend boundary, no real-time stream semantics, and no reusable component
system for tools, reasoning, structured outputs, generated UI, or run history.

## Documentation Findings

LangChain frontend:

- The core architecture is a `createAgent`/LangGraph backend streamed to the UI
  through `useStream` from `@langchain/react`.
- `useStream` exposes reactive messages, tool calls, interrupts, queues, run IDs,
  branch metadata, and state history.
- Markdown should be streamed, parsed, and sanitized. GFM support matters because
  model outputs commonly include tables, task lists, code blocks, and links.
- Tool calls should be rendered as specialized cards with pending, completed,
  and error states rather than raw JSON dumps.
- Human-in-the-loop uses interrupts. The UI surfaces an interrupt payload and
  resumes with approve, reject, edit, or respond decisions.
- Branching chat and time travel require LangGraph Agent Server-style history.
  They use checkpoints to edit/regenerate, switch branches, inspect old state,
  and resume from a selected point.
- Message queues, join/rejoin streams, and resumable run IDs matter for long
  multi-agent work where users keep interacting while agents are busy.
- Structured output and generative UI should be rendered progressively and only
  after validating partial data.

json-render:

- Use a catalog as the contract for AI-generated UI: components, props, actions,
  and validation are typed and constrained.
- Specs are JSON documents with a root element and an elements map.
- Streaming uses JSONL JSON Patch operations, letting the UI appear
  progressively while the model generates it.
- Data binding uses JSON Pointer paths against state, with support for runtime
  state providers, validation, and conditional visibility.
- Inline mode is a strong fit for chat: text remains conversational while JSONL
  patches become embedded UI parts.

AI Elements:

- AI Elements is a shadcn/ui-based component set for AI-native apps.
- Useful components for this project include Conversation, Message, Prompt
  Input, Queue, Reasoning, Tool, Confirmation, Checkpoint, Plan, Task, Artifact,
  File Tree, Terminal, Test Results, and Web Preview.
- The library expects React 19, Tailwind CSS 4, shadcn/ui conventions, and often
  Next.js App Router, though the installed components live in the codebase and
  can be adapted.

## Architecture Decision

Selected architecture: a FastAPI backend API app managed with `uv` from the
root Python project and a separate Next.js frontend app under
`src/webapp_studio/`. The frontend follows
Next.js, shadcn/ui, Tailwind, and AI Elements conventions. The frontend package
manager is `pnpm`.

Rationale:

- The repo is Python-first, so the conversation runtime should stay owned by a
  local FastAPI backend API app.
- FastAPI provides typed API routes, async request handling, streaming-friendly
  primitives, OpenAPI documentation, and Pydantic-based validation that fit the
  backend-contract-first plan.
- AI Elements is optimized for Next.js, shadcn/ui, and Tailwind conventions, so
  the frontend should use those conventions directly instead of adapting them to
  Vite.
- Separating backend and frontend folders keeps runtime contracts explicit and
  lets the Next.js app evolve naturally.
- The local developer workflow can still be one command later, but internally it
  should start both the FastAPI server and the Next.js app.

Framework layer:

- Keep Python runtime ownership in the existing team/conversation modules.
- Add a studio-native backend API layer that can expose both the current REST API
  and a LangGraph-compatible adapter surface for frontend hooks.
- Expose checkpoints, branches, and time-travel metadata as first-class backend
  API resources from the start. Some fields may initially be empty or derived,
  but the contract shape should be stable.
- Prioritize studio-native stream/history semantics with a LangGraph-compatible
  adapter because they unlock the most future functionality while preserving
  mention-router ownership: queues, interrupts, reconnect, branching, checkpoint
  history, and time travel.
- Keep a typed frontend client for current endpoints during implementation, but
  do not design `src/webapp` as a fallback path. It remains unchanged as a
  comparison artifact along with its tests.
- Use `@json-render/shadcn` for json-render surfaces.

## Target Directory Shape

Proposed future layout:

```text
src/webapp_studio/
  README.md
  PROJECT_PLAN.md
  backend/
    __init__.py
    server.py
    application/
      studio_backend_launcher.py
    api/
      studio_api_controller.py
      studio_protocol.py
      stream_protocol.py
      history_protocol.py
    http/
      request_handler.py
      sse_writer.py
  frontend/
    package.json
    next.config.ts
    src/
      app/
      components/
      features/
      hooks/
      lib/
      render/
```

## Product Scope

Product shape:

- Use a spacious research-notebook feel: generous reading space, clear temporal
  context, room for artifacts, and calm controls rather than a dense operations
  dashboard.
- Organize the first-class workspace as tabs next to each other: Chat, Activity,
  and Generated UI.
- Keep generated UI in the Generated UI tab. Chat messages that produce a
  rendered component show a compact hint/link, and clicking it switches focus to
  the matching generated component.
- Show private agent activity as ordinary selectable content in the Activity tab,
  not in an overlay, drawer, or modal, so users can easily copy and paste useful
  excerpts.

MVP parity:

- Launch from CLI for a selected `team.yaml`.
- Preserve public conversation, participant list, mentions, public attachments,
  mention-hook toggle, cascade limit, stop-agent control, and activity panel.
- Replace polling UI with typed state hooks and a cleaner React layout.
- Keep existing `src/webapp` code and tests unchanged for future comparison.
- Add parallel tests for the new API surface.

Modern chat foundation:

- Stream public messages and active agent status.
- Render markdown safely with compact chat styling.
- Add a durable composer with file attachments, mention autocomplete, queue
  feedback, keyboard submission, and optimistic message append.
- Add connection state, error state, and stale snapshot indicators.

Agent observability:

- Activity tab with per-agent private thread, run state, delivery status,
  queued follow-up state, tool calls, tool results, todos, terminal-like logs,
  artifacts, file references, and final public reply extraction.
- Private activity is read-only observability content. The UI must not provide a
  "promote to public chat" action; only runtime-extracted final replies enter the
  public transcript.
- Specialized cards for known tools plus a generic JSON inspector fallback.
- Reasoning display only when the backend intentionally exposes reasoning-style
  blocks; never fabricate it from ordinary hidden model internals.

Human-in-the-loop:

- Interrupt review cards for approve, reject, edit, and respond decisions.
- Resume flow wired to the runtime adapter.
- Audit trail showing who approved what and from which checkpoint or run.

Advanced conversation management:

- Message queue panel with queue order, cancel, clear, and failed-entry handling.
- Join/rejoin stream support with persisted active run IDs.
- First-class checkpoint, branch, and time-travel resources in the backend API.
- Branching chat for edit/regenerate in the first usable version.
- Time-travel timeline for inspecting checkpoints and resuming from prior state
  in the first usable version.
- Branch creation, branch switching, checkpoint resume, edit, and regenerate
  must be fully usable before the studio is considered first-version complete.

Generative UI:

- Define a json-render catalog for safe agent-generated UI in a separate
  workspace.
- Render generated UI with `@json-render/shadcn`.
- Use a closed allowlist catalog. Agents may only render approved components and
  bind approved actions; arbitrary component names, arbitrary JavaScript, and
  unregistered event handlers are rejected.
- Show a compact hint/link in the chat when a message has a rendered component;
  clicking it focuses the rendered component in the workspace.
- Start with domain-specific components: metric, plan, task list, file list,
  tool result, code artifact, test summary, terminal output, and web preview.
- Support progressive rendering from partial specs, validation before display,
  and explicit action handlers for any generated controls.

## Non-Goals For The First Build

- Replacing the team instantiation/runtime internals.
- Deploying to a hosted SaaS environment.
- Adding arbitrary generated code execution in the browser.
- Making private agent activity part of the public transcript unless the runtime
  explicitly extracts it as a public reply. Private activity is visible by
  default in the Activity tab as selectable read-only content, not promoted into
  chat.
- Building a general LangSmith clone.

## Implementation Phases

1. Planning and contract design
   - Treat the decisions below as fixed project constraints.
   - Start the first real implementation here before scaffolding the React UI.
   - Define backend DTO fixtures matching `ConversationStateDict`, events,
     activities, deliveries, files, runtime settings, stream events, queues,
     checkpoints, and branches.
   - Design a studio-native stream/history contract first, with a
     LangGraph-compatible adapter over the existing conversation runtime.

2. Backend API app
   - Add `backend/` with the FastAPI API-only server and launcher.
   - Manage backend dependencies from the root `pyproject.toml` with `uv`.
   - Add FastAPI dependencies, including the standard server/runtime extras
     needed for local development.
   - Implement stream/history protocol classes before the frontend is scaffolded.
   - Add tests for state, activity, streams, queues, checkpoints, branching, time
     travel metadata, and current REST compatibility.

3. Frontend scaffold
   - Add `frontend/` using:

     ```bash
     pnpm dlx shadcn@latest init --preset bbVJxYW --template next --rtl --pointer
     pnpm dlx shadcn@latest add @ai-elements/all
     ```

   - Keep right-to-left support enabled intentionally through the shadcn
     scaffold and frontend layout choices.
   - Add `@json-render/shadcn`.
   - Create app shell, transcript, composer, runtime controls, and Activity tab
     against mocked fixtures.
   - Add Vitest and Playwright smoke coverage.

4. Local orchestration and compatibility API
   - Add a launcher matching the current CLI ergonomics that starts the Python
     FastAPI backend and Next.js frontend in local development.
   - Expose the existing REST behavior behind typed controller classes.
   - Keep old `src/webapp` untouched until feature parity is proven.

5. Streaming runtime adapter
   - Add SSE/event stream for public transcript updates, runtime activity, and
     per-agent activity.
   - Add run IDs, reconnect/rejoin semantics, queue metadata, checkpoint
     metadata, branch metadata, and time-travel state.
   - Keep polling only as an internal development escape hatch, not as the
     product path.

6. Rich rendering
   - Markdown renderer with sanitization.
   - AI Elements-style message, reasoning, queue, tool, artifact, terminal, test,
     file tree, and web preview surfaces.
   - Specialized renderer registry for known tools and generic fallback cards.

7. Advanced workflows
   - HITL interrupts and resume decisions.
   - Message queues with cancel/clear and queue position.
   - Checkpoint timeline, branching, regenerate, and time travel as first-version
     requirements.
   - Branch creation, branch switching, checkpoint resume, edit, and regenerate
     must be end-to-end usable, not only visible as timeline metadata.

8. Generative UI
   - Add json-render catalog and registry.
   - Use `@json-render/shadcn` as the renderer.
   - Render structured output and generated specs in a separate workspace.
   - Add chat hints that focus linked rendered components.
   - Add validation, explicit action handlers, readable fallbacks for invalid
     specs, and security review for generated controls.

9. Migration
   - Run parity tests with fake conversations and
     `teams/conversing_philosophers/team.yaml`.
   - Switch automatic launch to the studio after parity and smoke tests pass.
   - Leave `src/webapp` unchanged as a historical comparison point.

## First Implementation Step

Start with backend stream/history contracts. The first coding milestone should
define the Python-side contract, DTO fixtures, stream event types, checkpoint and
branch metadata shape, queue metadata, and the studio-native compatibility
adapter needed for `@langchain/react` before the Next.js frontend is scaffolded.

## Testing Strategy

- Python unit tests for FastAPI routes, backend launcher, controller, attachment
  handling, runtime controls, stream event serialization, and API server
  behavior.
- TypeScript unit tests for DTO validation, reducers, hooks, mention parsing,
  queue behavior, and renderer selection.
- Component tests for transcript, composer, Activity tab, tool cards, HITL
  cards, and json-render surfaces.
- Playwright smoke tests for desktop and mobile layouts, message send, mention
  autocomplete, file attach, Activity tab, stop, reconnect, and queue states.
- Contract fixtures shared between Python and TypeScript to prevent API drift.

## Risks

- `@langchain/react` advanced features assume LangGraph Agent Server semantics.
  The current local runtime is custom, so Webapp Studio uses a studio-native API
  with a LangGraph-compatible adapter rather than cloning Agent Server routes
  exactly.
- AI Elements is optimized around Next.js/shadcn/Tailwind. Webapp Studio follows
  that structure directly with a separate Next.js frontend initialized through
  the required shadcn preset and `@ai-elements/all`.
- Private run activity is visible by default, so the UI must clearly separate it
  from public transcript content, render it as selectable non-modal content in
  the Activity tab, and avoid accidental promotion.
- Checkpoint branching and time travel are first-version requirements, but they
  depend on checkpoint metadata that may need to be newly exposed through the
  conversation runtime. Webapp Studio resolves this by defining checkpoints,
  branches, resume, edit, regenerate, and time-travel operations as first-class
  backend API resources from the start, then implementing the mutation paths
  before first-version completion.
- json-render generated UI needs a narrow catalog and strict action handlers to
  stay useful without becoming unsafe. Webapp Studio resolves this with a closed
  allowlist catalog, explicit action routing, no arbitrary JavaScript, no
  unregistered handlers, and readable validation-error fallbacks for unknown
  specs.
- Agent activity can include tool inputs, tool outputs, terminal logs, headers,
  environment values, and file paths. Webapp Studio resolves accidental secret
  exposure with backend redaction helpers for common sensitive field names, plus
  explicit per-tool sensitive-field metadata later.

## Resolved Decisions

1. Keep the local Python backend workflow, but split the studio into a backend
   API app and a separate Next.js frontend app.
2. Prioritize the path that enables the most future functionality: a
   studio-native streaming and history API with a LangGraph-compatible adapter
   for `@langchain/react`.
3. Use `pnpm` for the frontend package manager.
4. Show private agent activity by default in the observability surface.
5. Include fully usable branching, checkpoint resume, edit, regenerate, and time
   travel in the first usable version.
6. Put json-render generated UI in a separate workspace, with chat hints/links
   that focus the rendered component.
7. Leave old `src/webapp` and its tests unchanged as comparison leftovers, not
   as a fallback.
8. Use a spacious research-notebook product feel.
9. Make Generated UI a full tab next to Chat and Activity.
10. Start real implementation with backend stream/history contracts.
11. Split Webapp Studio into separate `backend/` and `frontend/` folders.
12. Initialize the frontend as a Next.js app with the required shadcn preset, then
    add `@ai-elements/all`.
13. Use `@json-render/shadcn` for generated UI rendering.
14. Render private activity as read-only selectable content in the Activity tab,
    never as an overlay/modal and never with a promote-to-public action.
15. Expose checkpoints, branches, and time-travel metadata as first-class backend
    API resources from the start.
16. Use a closed allowlist catalog for Generated UI with explicit action routing
    and readable validation fallbacks for unknown specs.
17. Use FastAPI for the Python backend API app and manage dependencies from the
    root `pyproject.toml` with `uv`.
18. Keep right-to-left frontend support intentionally enabled.
19. Use `teams/conversing_philosophers/team.yaml` as the real-team parity and
    smoke-test target.
20. Use Pydantic DTOs plus shared JSON fixtures as the first type-sharing
    strategy between Python and TypeScript.
21. Add backend redaction helpers for common sensitive activity fields such as
    API keys, tokens, secrets, passwords, authorization headers, and cookies.

## Documentation Sources

- https://docs.langchain.com/oss/python/langchain/frontend/overview
- https://docs.langchain.com/oss/python/langchain/frontend/markdown-messages
- https://docs.langchain.com/oss/python/langchain/frontend/tool-calling
- https://docs.langchain.com/oss/python/langchain/frontend/human-in-the-loop
- https://docs.langchain.com/oss/python/langchain/frontend/branching-chat
- https://docs.langchain.com/oss/python/langchain/frontend/reasoning-tokens
- https://docs.langchain.com/oss/python/langchain/frontend/structured-output
- https://docs.langchain.com/oss/python/langchain/frontend/message-queues
- https://docs.langchain.com/oss/python/langchain/frontend/join-rejoin
- https://docs.langchain.com/oss/python/langchain/frontend/time-travel
- https://docs.langchain.com/oss/python/langchain/frontend/generative-ui
- https://github.com/fastapi/fastapi
- https://fastapi.tiangolo.com
- https://json-render.dev/docs
- https://json-render.dev/docs/quick-start
- https://json-render.dev/docs/specs
- https://json-render.dev/docs/data-binding
- https://json-render.dev/docs/validation
- https://json-render.dev/docs/streaming
- https://json-render.dev/docs/generation-modes
- https://elements.ai-sdk.dev/
- https://elements.ai-sdk.dev/docs/setup
- https://elements.ai-sdk.dev/docs/usage
- https://elements.ai-sdk.dev/components/conversation
- https://elements.ai-sdk.dev/components/queue
- https://elements.ai-sdk.dev/components/reasoning
- https://elements.ai-sdk.dev/components/tool
- https://elements.ai-sdk.dev/components/artifact
- https://elements.ai-sdk.dev/components/file-tree
- https://elements.ai-sdk.dev/components/terminal
- https://elements.ai-sdk.dev/components/test-results
- https://elements.ai-sdk.dev/components/web-preview
