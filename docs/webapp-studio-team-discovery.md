# Webapp Studio Team Discovery

Status: design draft

Scope: `src/webapp_studio`, `src/team_loader`, Studio launch workflow

## Summary

Webapp Studio should not require users to pass a specific `team.yaml` file when
starting the app. The launcher should discover available conversation teams from
the current workspace and from the built-in `coding-agents` repository, then let
the user choose a team inside the Studio before starting a conversation.

The current explicit launch shape remains useful for compatibility and advanced
debugging:

```bash
uv run webapp-studio /abs/path/to/team.yaml --thread-id thread
```

The desired default launch shape is:

```bash
uv run webapp-studio --port 8768 --frontend-port 3769
```

## Goals

- Improve developer experience by removing the need to choose a team from the
  shell command.
- Make local project teams discoverable through a stable convention.
- Make built-in repository teams discoverable in the same Studio session.
- Prevent ambiguous or unsafe team identity collisions.
- Let users choose a team before the first message without creating unused
  conversation ids.
- Make the active team visible in the current conversation and in conversation
  history.
- Preserve the existing explicit `team.yaml` launch mode as a compatibility
  path.

## Team Discovery Convention

The Studio launcher discovers conversation teams from two roots:

1. Project-local teams from the command working directory:

   ```text
   <launcher-cwd>/.coding-agents/teams/<team-name>/team.yaml
   ```

2. Built-in teams from the `coding-agents` repository:

   ```text
   <coding-agents-root>/teams/<team-name>/team.yaml
   ```

Only teams with a top-level `conversation:` section should be offered in the
Studio team picker. Non-conversation teams can still be valid for other CLI
surfaces, but they are not chat targets.

Each discovered team descriptor should include:

- `team_id`: the `id` declared in `team.yaml`;
- `description`: the `description` declared in `team.yaml`, if present;
- `team_file`: absolute path to the discovered `team.yaml`;
- `source`: `project` or `builtin`;
- `conversation_available`: whether the top-level `conversation:` section is
  present.

The `team_id` is the user-facing identity and the persistence partition for
Studio conversations. It must be globally unique across all Studio-discovered
conversation teams.

## Duplicate Team Ids

Duplicate `team.yaml` ids must block Studio usage until they are resolved.

The duplicate check is case-insensitive. Implement it with Python `casefold()`,
so values such as `OpenSpec`, `openspec`, and `OPENSPEC` collide.

When duplicates exist, the system should report them at two levels.

### Console Output

The launcher should print a clear blocking error listing each duplicated id and
the files that declare it.

Example:

```text
Studio team discovery failed: duplicate team ids.

id "philosophers" is declared by:
- /Users/mickael/Documents/github/coding-agents/teams/philosophers/team.yaml
- /Users/mickael/Documents/github/coding-agents/teams/conversing_philosophers/team.yaml

Rename one of these team.yaml ids, then restart webapp-studio.
```

The backend should still be allowed to start in a configuration-blocked mode so
the frontend can show the same problem in the browser. This avoids a confusing
blank or disconnected Studio page.

### Studio UI

The Studio should display a blocking configuration screen when duplicate ids
exist. The screen should:

- state that team discovery failed because multiple `team.yaml` files declare
  the same id;
- group the conflicting files by duplicate id;
- explain that ids are compared case-insensitively;
- tell the user to rename one of the ids and restart Studio;
- disable chat creation, team selection, and conversation switching.

No fallback team should be auto-selected while discovery is blocked.

## New Chat Flow

The left sidebar should always show a visible `New chat` button at the top. The
conversation history appears below it.

Clicking `New chat` creates a local draft chat state, not a persisted
conversation. The user then chooses the team they want to chat with.

Until the user sends the first message:

- changing the selected team should be immediate;
- no `conversation_id` should be generated;
- no conversation row or event should be persisted;
- browser-only draft state may be kept for the empty composer.

On the first submitted message, the Studio should atomically:

1. instantiate the selected team;
2. generate the `conversation_id`;
3. append the first human message;
4. dispatch normal conversation delivery;
5. return the hydrated session and `StudioState`.

After the first message is saved, the conversation's team is fixed.

## Conversation History

Empty conversations should not exist. Because a conversation is only created on
the first message, there is no need for placeholder conversation metadata in the
MVP.

Recent conversation history can be derived from persisted events grouped by:

```text
(team_id, conversation_id)
```

Each history item should include:

- `team_id`;
- `conversation_id`;
- inferred title, usually from the first human message;
- `event_count`;
- `last_seq`;
- `last_event_at`;
- `last_author_id`;
- optional first-message preview.

The sidebar should make the team visible for each historical conversation, not
only for the currently open conversation.

## Active Team Visibility

When a conversation is open, the active team must be subtle but easy to identify.

Recommended placements:

- a compact team badge in the chat header;
- the team id under the Studio title or current conversation label in the
  sidebar;
- a team badge on each conversation-history item.

The team indicator should not be hidden only in persistence details or debug
metadata.

## Backend Contract Direction

The existing backend is centered on a single instantiated team. The new Studio
session should introduce a discovery/session layer that owns discovered teams
and active conversation selection.

Recommended endpoints:

```text
GET /api/studio/v1/teams
```

Returns discovered teams, or a blocked discovery state with duplicate-id
details.

```text
POST /api/studio/v1/conversations
```

Creates a new conversation from the first message. Request shape:

```json
{
  "team_id": "openspec",
  "initial_message": "I want to shape a new feature",
  "attachments": [],
  "workspace_paths": [],
  "client_message_id": "client_..."
}
```

The response should include the updated `session`, hydrated `StudioState`, and
the append result for the saved first message.

```text
PUT /api/studio/v1/session/conversation
```

Switches to an existing persisted conversation. The request should include both
the team and conversation identifiers:

```json
{
  "team_id": "openspec",
  "conversation_id": "conv_..."
}
```

The response should include the updated `session` and hydrated `StudioState`.

```text
GET /api/studio/v1/conversations?limit=20
```

Returns recent persisted conversations across discovered Studio teams, or at
least across the currently selected team for the first implementation slice.
The preferred shape includes `team_id` on every item.

## Launcher Behavior

The public `webapp-studio` command should make `team_file` optional.

Recommended modes:

- `webapp-studio`: discover teams and start Studio with no preselected
  conversation;
- `webapp-studio path/to/team.yaml`: compatibility mode that preselects that
  team;
- `webapp-studio path/to/team.yaml --thread-id existing`: advanced/debug mode
  that opens a specific existing conversation directly.

The explicit mode should still validate duplicate discovered ids if the Studio
sidebar exposes all teams in the same session. If explicit mode is implemented
as a strict single-team session, duplicate discovery can be skipped, but the UI
should make that mode clear.

## MVP Implementation Slices

1. Add team discovery and duplicate-id reporting.
2. Add blocked-discovery backend state and frontend blocking screen.
3. Make `team_file` optional in the Studio launcher.
4. Add team picker for the empty `New chat` state.
5. Add first-message conversation creation.
6. Update conversation history to include team identity.
7. Replace the manual thread input in the sidebar with `New chat` plus recent
   conversation history.

## Open Questions

- Should duplicate-id checks include non-conversation teams, or only teams with
  top-level `conversation:`? For Studio, the stricter and simpler rule is to
  block duplicate ids among Studio-discoverable conversation teams.
- Should explicit `team.yaml` launch remain a single-team session or still show
  all discovered teams? Single-team explicit mode is simpler for debugging;
  full discovery is more consistent with normal Studio usage.
- What naming convention should generated `conversation_id` values use? They
  should be stable, opaque enough to avoid user naming burden, and safe for
  filesystem paths used by conversation attachments.
