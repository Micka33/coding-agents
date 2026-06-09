# Webapp Studio UI Improvements

Status: design draft

Scope: `src/webapp_studio/frontend`

## Summary

The Webapp Studio UI should behave more like a focused conversation workspace.
The chat must remain the primary surface, with navigation and operational
controls moved out of the transcript area. The right panel should be a general
inspector for contextual workspace information such as files, agent activity,
file changes, terminal output, and generated UI, all side-by-side with the chat
instead of replacing it.

## Goals

- Maximize visible conversation height.
- Keep controls discoverable without consuming header or footer space.
- Let users inspect generated UI while continuing the conversation.
- Let users inspect conversation files, agent activity, file changes, terminal
  sessions, and other contextual workspace information without leaving chat.
- Make participant activity visible while agents are preparing answers.
- Make mentioning participants fast and reliable.
- Make persisted conversation state understandable and recoverable after
  restarts.

## Layout

The app should not have a global header or footer. Header and footer content
such as settings, stats, runtime controls, queue state, branch/checkpoint
actions, links, and informational status should move into a left sidebar.

Desktop layout should use three horizontally resizable panels:

1. Left sidebar: open by default, collapsible to an icon rail, and resizable.
2. Center chat: the primary panel and the default recipient of extra width.
3. Right inspector: contextual panel for files, activity, changes, terminal
   sessions, generated UI, and other focused workspace views.

Users must be able to resize panel boundaries with draggable splitters. Panel
widths should have sensible minimums and should persist for the current browser
profile. Panel widths persist globally, not per team or thread.

Panel size constraints:

- left sidebar: 238px minimum, 518px maximum;
- right inspector: 318px minimum, 875px maximum.

On narrow screens, the same information should collapse into a drawer or
stacked inspector flow that keeps the chat usable first.

## Left Sidebar

The sidebar should contain the app menu and operational controls:

- team and conversation identifiers;
- mention hook toggle;
- cascade limit control;
- queue and review controls;
- active agents and stop controls;
- thread selector and thread switcher;
- branch and checkpoint actions;
- files, changes, generated UI counts, and other conversation stats;
- links, settings, and app info.

When collapsed, the sidebar should remain useful through icons and tooltips.
The resolved database path should not be shown as always-visible chrome. It
should be available behind an info/details affordance in the sidebar.

## Center Chat

The center panel is the public transcript and composer. It should keep the chat
visible while the user opens files, participant activity, file changes,
terminal sessions, generated UI, or other contextual views in the right
inspector.

The composer should preserve the current draft when the user switches inspector
content, resizes panels, or opens any right-inspector view.

When a user submits a prompt, the message should appear in the transcript
immediately with a sending state. Once the backend acknowledges the append, the
optimistic message should be reconciled with the saved public event and marked
saved. Agent work may continue after the human prompt is saved.

## Backend Contract

The frontend cannot infer persistence context or recent thread ids reliably.
The backend must expose that data through explicit API responses.

`GET /api/studio/v1/session`

Returns the current app and persistence context:

```json
{
  "team_id": "openspec",
  "conversation_id": "openspec-test-manuel",
  "team_file": "/abs/path/to/team.yaml",
  "launcher_cwd": "/Users/mickael/Documents/github/my_project",
  "resolved_root_dir": "/Users/mickael/Documents/github/my_project",
  "checkpointer": {
    "backend": "sqlite",
    "sqlite_path": "/Users/mickael/Documents/github/my_project/.coding-agents/checkpoints.sqlite",
    "storage_id": "sqlite:/Users/mickael/Documents/github/my_project/.coding-agents/checkpoints.sqlite"
  },
  "loaded_at": "2026-06-02T10:17:06Z"
}
```

`sqlite_path` is `null` for non-SQLite backends. `storage_id` must be stable for
the same resolved persistence store and should be safe to use in localStorage
keys.

`GET /api/studio/v1/conversations?limit=20`

Returns recent conversations for the current team in the same persistence store:

```json
{
  "team_id": "openspec",
  "current_conversation_id": "openspec-test-manuel",
  "conversations": [
    {
      "conversation_id": "openspec-test-manuel-3",
      "event_count": 1,
      "last_seq": 1,
      "last_event_at": "2026-06-02T10:17:06Z",
      "last_author_id": "human"
    }
  ]
}
```

`PUT /api/studio/v1/session/conversation`

Switches the active thread for the running backend process:

```json
{
  "conversation_id": "openspec-test-manuel-3"
}
```

The response must include the updated session context and the hydrated
`StudioState` for the selected conversation. The stream should publish a
snapshot replacement, or the frontend should reconnect after the switch.

`POST /api/studio/v1/messages`

The append request should accept an optional `client_message_id` idempotency key
generated by the browser. The response must echo the saved event id and sequence
so the frontend can mark the optimistic transcript item as saved. Retrying the
same `client_message_id` for the same team, conversation, and author should not
create duplicate public events.

`GET /api/studio/v1/state`

The state response must include all persisted public conversation events for
the active conversation before the frontend marks the chat ready.

Right inspector data should also come from explicit backend contracts rather
than ad hoc parsing in the frontend.

`GET /api/studio/v1/files`

Returns files attached to the active conversation:

```json
{
  "files": [
    {
      "id": "file_mobile_requirements",
      "filename": "mobile-requirements.pdf",
      "media_type": "application/pdf",
      "size_bytes": 24576,
      "added_by": "human",
      "event_id": "evt_123",
      "event_seq": 4,
      "preview_url": "/api/studio/v1/files/file_mobile_requirements/preview",
      "download_url": "/api/studio/v1/files/file_mobile_requirements/download"
    }
  ]
}
```

Preview URLs should be available only for media types the app can safely render.
Download URLs should serve the original file with the original filename.

`GET /api/studio/v1/changes`

Returns file changes associated with the active conversation when the runtime can
observe them:

```json
{
  "changes": [
    {
      "id": "change_1",
      "path": "docs/example.md",
      "status": "modified",
      "source": "tool_call",
      "agent_id": "openspec-guide",
      "event_id": "evt_123",
      "diff_url": "/api/studio/v1/changes/change_1/diff"
    }
  ]
}
```

The frontend should not infer durable file changes from markdown text alone.
When structured change data is unavailable, the changes view should show an
empty or unsupported state.

Terminal support requires explicit backend APIs because the terminal runs in the
resolved workspace/root directory. The API shape can be WebSocket or SSE plus
POSTed input, but it must model terminal sessions explicitly:

- create a terminal session for the current resolved workspace/root directory;
- stream terminal output;
- send user input;
- resize the terminal;
- terminate the session.

Terminal sessions should be scoped to the active Webapp Studio process and
should not be restored across restarts unless a future backend explicitly
supports that.

## Restart And Thread Recovery

The UI must make persisted conversation identity visible and recoverable across
restarts. A user who starts Webapp Studio twice with the same team, thread id,
and resolved storage path should see the same public transcript.

The left sidebar should show the active persistence context:

- team id;
- conversation/thread id;
- resolved workspace/root directory;
- checkpointer backend;
- resolved checkpoint database path when using SQLite.

This matters because relative team settings such as `working_directory: "."`
and relative SQLite paths are resolved from the launcher working directory.
Running the same command from a different folder can point the same thread id
at a different database. The UI should expose that fact instead of looking like
an empty or buggy chat.

On startup, the chat must hydrate from the backend's persisted public
conversation before presenting itself as ready. If the selected thread has
persisted events, they must be displayed. If the selected thread is empty, but
the same store contains nearby or recent conversation ids for the same team, the
sidebar or empty state should make that visible so the user can tell whether
they opened the wrong thread id.

Thread recovery UX:

- the sidebar must let the user change the active thread id;
- selecting a recent thread should switch to it and hydrate its transcript
  without requiring a process restart;
- entering a new thread id should create or open that empty thread in the same
  persistence store;
- an empty thread state should show the current team/thread and offer recent
  threads from the same store when available;
- the persistence details affordance should show the resolved database path and
  launcher working directory for debugging.

Submitting a prompt should have an explicit durability lifecycle:

- sending: the browser has submitted the message but the backend has not
  acknowledged it;
- saved: the backend has appended the public event and returned its sequence;
- failed: the backend did not acknowledge the append.

An acknowledged prompt must survive a restart. If the process is stopped before
the backend acknowledges the append, the UI should preserve the unsent draft or
outbox item locally and clearly mark that it was not saved to the public
conversation.

Unsent prompt recovery should use localStorage with keys scoped by persistence
store, team id, and thread id. Suggested key shape:

```text
webapp-studio:v1:{storage_id}:{team_id}:{conversation_id}:draft
webapp-studio:v1:{storage_id}:{team_id}:{conversation_id}:outbox
```

The draft key stores the current composer text. The outbox key stores submitted
text prompts that did not receive backend acknowledgement. Attachment bytes
should not be stored in localStorage; if an unsaved prompt included files, the
recovered outbox item should preserve text and file names and ask the user to
reattach files before retrying.

Restart hydration should follow common loading practices:

- show a loading state while session context and persisted state are loading;
- do not show an empty transcript until hydration has completed;
- show a retryable backend-disconnected state if hydration fails;
- reconcile local drafts and outbox items only after the server state is known;
- avoid duplicating optimistic messages when a saved event with the same
  `client_message_id` already exists.

## Mention Autocomplete

The composer must support autocomplete for participant mentions.

When the user types `@` at a mention boundary, the UI should show mentionable
participants, filter them as typing continues, and support keyboard and pointer
selection. Selecting an entry should insert the canonical mention text.

Aliases may be displayed as search or helper metadata, but inserted mentions
should resolve to the canonical participant id unless the runtime explicitly
requires preserving aliases. Unknown mentions remain visible plain text and
must not enqueue work.

Autocomplete should follow common composer patterns:

- trigger only at mention boundaries, not inside emails or ordinary words;
- filter case-insensitively across canonical ids and aliases;
- replace only the active `@query` range and preserve the rest of the draft;
- support ArrowUp, ArrowDown, Enter, Tab, Escape, pointer selection, and IME
  composition safely;
- insert a trailing space after selection when appropriate;
- remain available when the mention hook is disabled, but clearly indicate that
  mentions will not wake participants while disabled;
- avoid triggering inside inline code or fenced code when detectable;
- expose accessible combobox/listbox semantics.

## Activity Hint

When any participant is running or has a queued follow-up, the chat must show a
concise clickable hint directly above the composer. For example:

```text
software-architect is replying...
```

When multiple participants are active, the hints should merge into one compact
summary, for example:

```text
2 agents running
```

The absence of this hint while a participant is running should be treated as a
UI bug.

When exactly one participant is active, clicking the hint must open the right
inspector to that participant's live activity.

For multiple active participants, clicking the compact hint should expand a
small list of active participants and their statuses. Choosing a participant
from that list opens that participant's activity in the right inspector. The
hint expansion itself should not change the right inspector content.

## Right Inspector

The right inspector should be contextual rather than another top-level tab. It
is a reusable workspace inspector, similar in spirit to Codex's side surfaces:
the user can keep the chat open while inspecting artifacts, agent execution, and
local workspace state.

It should support at least these modes:

- conversation files added to the current thread;
- selected file preview and download;
- generated UI preview;
- selected participant live activity, actions, thinking/debug traces when
  available, tool calls, and tool results;
- file changes and diffs;
- terminal in the resolved workspace/root directory;
- empty state.

Generated UI links in the transcript should open the generated UI preview in
the right inspector while keeping the chat visible.

The right inspector must not change content unless the user takes an explicit
action. If generated UI is open and an agent starts replying, the generated UI
must remain open. Agent activity should surface through the activity hint, count,
or badge, and should open in the inspector only after the user selects it.

Users should be able to open inspector views from multiple places:

- left sidebar navigation items for Files, Activity, Changes, Terminal, and
  Generated UI;
- inline transcript affordances, such as attachment chips, generated UI links,
  tool call references, or file-change links;
- activity hints above the composer;
- inspector-internal links, such as a file reference inside an activity view.

The inspector should have a stable shell:

- compact header with icon, title, and current view name;
- close/collapse button;
- view switcher menu for user-initiated view changes;
- optional back button for inspector-local navigation history;
- lightweight status or badge area for background updates;
- body area owned by the active view component.

The shell should avoid a permanent tab strip that competes with the chat. A
view switcher menu and contextual links are preferred because the inspector has
many possible modes and should stay compact.

Recommended right-inspector UX model:

- the inspector is always controlled by an explicit `InspectorView` descriptor;
- sidebar buttons open broad views, such as Files, Activity, Changes, Terminal,
  and Generated UI;
- transcript affordances open deep-linked views, such as a selected file,
  selected generated UI artifact, selected tool call, or selected file change;
- the active inspector view and its selected item remain stable until the user
  changes them;
- background activity updates badges, counters, and data inside the currently
  open view, but does not replace the active view;
- the shell keeps lightweight local navigation history so a user can open a
  detail and go back to the previous inspector view;
- the empty state should be useful, offering the main inspector destinations
  and showing small counts/status where available.

The view switcher should be a compact menu or icon row, not a large tab system.
Each view entry can show a count or status badge:

- Files: current-thread file count;
- Activity: running or queued participant count;
- Changes: observed change count or unsupported status;
- Terminal: inactive, running, or unsupported status;
- Generated UI: generated artifact count.

Files view:

- list files added to the current thread;
- show filename, media type, size, who added it, and public event sequence;
- support safe preview for renderable media;
- support download for every file;
- provide an empty state when no files exist.

Participant activity should show live run history and debugging details where
available:

- streamed activity;
- private message history;
- tool calls;
- tool results;
- todo or plan progress;
- delivery status;
- running, queued, stopping, or idle state.

Changes view:

- list file changes associated with the current thread;
- show path, status, source agent or tool call when available, and event
  association;
- display a readable diff for selected changes;
- provide an unsupported state when the backend cannot observe changes.

Terminal view:

- open a terminal in the resolved workspace/root directory;
- make the cwd visible in the terminal header;
- start terminal sessions only after a user clicks a clear start/open action;
- support streaming output, input, resize, and termination;
- keep terminal sessions user-initiated;
- do not auto-open the terminal because of background activity.

Generated UI view:

- list generated UI artifacts for the current thread;
- show selected generated UI side-by-side with chat;
- preserve the selected generated UI artifact while other inspector data
  updates;
- preserve generated UI state while unrelated activity happens in the
  background.

This inspector is an observability surface only. Private activity must not be
promoted into the public conversation unless it becomes the participant's final
extracted public reply.

## Acceptance Criteria

- There is no global header or footer in the workspace.
- Sidebar content remains available when collapsed through icons and tooltips.
- The center chat remains visible while any right-inspector view is open.
- Generated UI can be viewed side-by-side with the chat.
- Left panel resizing respects the 238px minimum and 518px maximum.
- Right panel resizing respects the 318px minimum and 875px maximum.
- Panel widths persist globally across reloads and threads.
- Clicking a generated UI link opens the right inspector without losing the chat
  draft.
- Attachment/file links open the right inspector files view without losing the
  chat draft.
- File change links open the right inspector changes view without losing the
  chat draft.
- Clicking a single active-participant hint opens live activity in the right
  inspector.
- The right inspector can switch between generated UI and selected participant
  activity, files, changes, and terminal without losing the chat draft.
- Dragging either splitter resizes adjacent panels without overlapping text or
  breaking the composer.
- Mention autocomplete works for all conversation participants.
- Mention autocomplete does not submit or unexpectedly mutate the draft.
- A running or queued participant always creates a visible clickable activity
  hint above the composer.
- Multiple active participants are merged into one compact hint that expands on
  click.
- The right inspector never switches content because of background agent
  activity; it changes only after a user action.
- The right inspector exposes user-initiated views for files, agent activity,
  file changes, terminal, generated UI, and empty state.
- Files added to the active thread can be listed, safely previewed when
  supported, and downloaded.
- File changes associated with the active thread can be listed and displayed as
  diffs when backend change data is available.
- Terminal sessions open only after user action and run in the resolved
  workspace/root directory.
- The sidebar shows the active team id, thread id, resolved workspace/root
  directory, checkpointer backend, and SQLite database path when applicable.
- The resolved SQLite database path is available behind an info/details
  affordance, not as always-visible chrome.
- The sidebar lets the user change the active thread id.
- Restarting with the same resolved persistence context reloads acknowledged
  public conversation events before the chat is marked ready.
- Opening an empty thread while nearby/recent threads exist in the same store
  surfaces those thread ids instead of showing only an unexplained empty chat.
- Submitted prompts visibly move from sending to saved after backend
  acknowledgement.
- Stopping the process before backend acknowledgement does not silently lose the
  user's draft; it remains recoverable as an unsaved draft or outbox item.
- A saved human prompt appears in the transcript immediately and remains there
  while agent work continues.

## Test Plan

Frontend unit tests:

- mention autocomplete triggers only at valid mention boundaries;
- autocomplete filters by canonical ids and aliases;
- autocomplete keyboard and pointer selection replace only the active mention
  range;
- autocomplete does not submit the draft unexpectedly;
- panel width persistence uses global keys and clamps to configured minimum and
  maximum widths;
- inspector view state is represented as a typed view descriptor rather than
  scattered booleans;
- inspector shell renders the correct view component for files, activity,
  changes, terminal, generated UI, and empty state;
- localStorage draft and outbox keys include storage id, team id, and
  conversation id.

Backend contract tests:

- session context returns team id, conversation id, launcher cwd, resolved root
  directory, checkpointer backend, and SQLite path when applicable;
- recent conversations returns only conversations from the same team and same
  persistence store;
- switching conversations returns the new session context and hydrated state;
- appending a message with the same `client_message_id` twice does not create
  duplicate public events;
- state hydration includes persisted public events for the active conversation;
- files endpoint returns only files attached to the active conversation and
  exposes safe preview and download URLs;
- changes endpoint returns structured changes when available and supports an
  unsupported state when unavailable;
- terminal session APIs create, stream, resize, accept input, and terminate a
  cwd-scoped terminal session.

Frontend integration or e2e tests:

- launching the app shows loading until session context and state have loaded;
- an empty hydrated thread shows the current thread id and recent threads from
  the same store;
- selecting a recent thread in the sidebar switches thread and displays its
  transcript;
- changing to a new thread id creates or opens an empty thread without a
  process restart;
- submitting a prompt immediately adds a sending transcript item, then marks it
  saved after backend acknowledgement;
- a saved human prompt stays visible while agent work continues;
- if message append never acknowledges and the page reloads, the prompt is
  recoverable from the per-thread outbox;
- restarting with the same working directory, team, thread id, and storage path
  reloads the saved transcript;
- launching from a different working directory exposes the different resolved
  database path in the details affordance;
- generated UI remains open when an agent starts replying;
- files view lists current-thread attachments and can preview or download a
  selected file;
- changes view lists current-thread changes and opens a selected diff;
- terminal view opens in the resolved workspace/root directory and remains
  user-initiated;
- multiple active agents show one compact hint, expand to a participant list,
  and open activity only after a participant is selected;
- right inspector content never changes due to background activity alone;
- no global header or footer is rendered.

## Suggested Implementation Notes

Use existing frontend primitives where possible. The current frontend already
has command/popover components suitable for mention autocomplete and has
generated UI and activity panel components that can be moved into a contextual
inspector.

For resizable panels, either add a small focused panel splitter component or use
a lightweight proven dependency. The important behavior is the contract:
resizable left, center, and right panels with persisted widths and clear minimum
sizes.

Suggested inspector code structure:

```ts
type InspectorView =
  | { kind: "empty" }
  | { kind: "files"; selectedFileId?: string }
  | { kind: "activity"; agentId?: string }
  | { kind: "changes"; selectedChangeId?: string }
  | { kind: "terminal"; sessionId?: string }
  | { kind: "generated-ui"; specId?: string }

type InspectorController = {
  view: InspectorView
  open: (view: InspectorView) => void
  close: () => void
  back: () => void
}
```

Suggested file/module structure:

```text
components/studio/inspector/
  right-inspector-shell.tsx
  inspector-controller.ts
  inspector-view-registry.ts
  views/files-inspector-view.tsx
  views/activity-inspector-view.tsx
  views/changes-inspector-view.tsx
  views/terminal-inspector-view.tsx
  views/generated-ui-inspector-view.tsx
```

Recommended component boundaries:

- `StudioWorkspace`: owns panel layout and global workspace state.
- `StudioSidebar`: owns navigation, settings, thread switching, and persistence
  details.
- `ChatPanel`: owns transcript, composer, activity hints, and inline affordances
  that call `inspector.open(...)`.
- `InspectorController`: owns the active view descriptor, back stack, close
  behavior, and view persistence if implemented later.
- `RightInspectorShell`: owns header, view switcher, local navigation history,
  close/collapse, and badges.
- `FilesInspectorView`: lists, previews, and downloads thread files.
- `ActivityInspectorView`: renders participant activity, tool calls, private
  messages, and run state.
- `ChangesInspectorView`: lists changes and renders selected diffs.
- `TerminalInspectorView`: owns terminal session lifecycle and IO.
- `GeneratedUiInspectorView`: renders generated UI artifacts.

The inspector controller should be the only place that changes the active
inspector view. Streaming updates may update badges, counts, or the data inside
the current view, but they must not call `open(...)` on their own.

Suggested data boundaries:

- durable thread data, such as files and file changes, should be loaded through
  backend API contracts and keyed by the active team/thread;
- live activity should come from the studio stream and be reduced into typed
  participant activity state;
- terminal IO should live behind a dedicated terminal-session client because it
  has lifecycle, resize, input, and termination concerns;
- generated UI should remain a first-class state slice and be rendered by the
  generated UI inspector view rather than embedded in the transcript;
- view components should receive typed data and callbacks rather than reaching
  into unrelated workspace state.

The resulting UI structure should make the right panel extensible without
turning it into a pile of conditional rendering:

```ts
type InspectorViewDefinition = {
  kind: InspectorView["kind"]
  label: string
  icon: ComponentType<{ className?: string }>
  badge?: (state: StudioState) => string | null
  render: (props: InspectorViewProps) => ReactNode
}
```

A small registry like this lets the shell render the switcher consistently while
each view component keeps its own focused responsibilities.
