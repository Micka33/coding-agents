# Webapp Studio Reference Autocomplete

## Goal

Add a single autocomplete experience in the Studio main conversation prompt when the user types `@`.

The autocomplete should support:

- mentioning conversation agents;
- including files from the directory where the Studio command was launched.

## Assumptions

- The launch directory is the Studio backend `root_dir`.
- Workspace file inclusion should create real conversation attachments, not only insert file paths into the prompt text.
- Agent mentions should keep using the existing mention syntax, such as `@agent`.
- File references should be represented separately from agent mentions so the runtime parser does not need to interpret files as agents.
- The browser cannot read arbitrary local files, so workspace file listing and attachment creation must happen through the backend.

## Current State

The frontend already has an agent mention autocomplete in `ChatPanel`.

- `activeMentionQuery()` detects an active `@` token.
- `mentionOptionsForState()` filters `state.participants` and aliases.
- `insertMention()` replaces the active token with `@participant `.

The existing backend `GET /api/studio/v1/files` lists only files already attached to the conversation. It does not list files from the launch directory.

Message submission already supports file attachments, but the frontend currently sends uploaded files as base64 data. The backend converts those into `ConversationFileRef` values before calling `append_human_message`.

The conversation layer already supports local filesystem paths as file inputs: passing a `Path` to `append_human_message(files=...)` copies the file into the conversation attachment store.

## Proposed Design

Use `@` as one unified reference trigger with two groups:

- Agents
- Files

When the user types `@`, show both agent and file candidates. When they type more characters, filter both groups.

Examples:

```text
@
@arch
@src/webapp
```

Selecting an agent inserts an agent mention into the prompt content:

```text
@software-architect 
```

Selecting a file adds the file to a selected workspace file list in the composer. The prompt can also receive a readable marker, for example:

```text
@{src/webapp_studio/frontend/components/studio/chat-panel.tsx} 
```

The marker is for user readability. The actual inclusion should be sent as structured data, not inferred from prompt text.

## Backend Changes

Add a workspace file search endpoint:

```text
GET /api/studio/v1/workspace-files?query=chat&limit=20
```

Response:

```json
{
  "files": [
    {
      "path": "src/webapp_studio/frontend/components/studio/chat-panel.tsx",
      "filename": "chat-panel.tsx",
      "media_type": "text/plain",
      "size_bytes": 12345
    }
  ]
}
```

Search rules:

- Resolve all candidates under `_resolved_root_dir()`.
- Return relative paths only.
- Refuse absolute paths and path traversal.
- Prefer `git ls-files -co --exclude-standard -z` when the root is a Git repository.
- Fall back to a bounded recursive scan when Git is unavailable.
- Exclude `.git`, `.coding-agents`, `node_modules`, `.next`, caches, and hidden generated directories.
- Limit results and stop scanning early.
- Skip directories.
- Optionally skip files above the attachment limit.

Extend message append input:

```python
class AppendMessageRequest(ContractModel):
    content: str
    author_id: str = "human"
    attachments: list[dict[str, JsonLike]] = Field(default_factory=list)
    workspace_paths: list[str] = Field(default_factory=list)
    wait: bool = False
    client_message_id: str | None = None
```

In `StudioApiController.append_message()`:

1. Convert uploaded `attachments` with the existing attachment factory.
2. Validate each `workspace_paths` entry as a relative path under `_resolved_root_dir()`.
3. Reject missing files, directories, files outside the root, and files above the configured limit.
4. Pass both uploaded attachment refs and validated `Path` objects to `append_human_message(files=...)`.

This keeps file inclusion as a backend-controlled operation and reuses the existing conversation file copy path.

## Frontend Changes

Replace the agent-only mention option type with a shared reference option type:

```ts
type ReferenceOption =
  | {
      kind: "agent"
      participant: string
      aliases: string[]
    }
  | {
      kind: "file"
      path: string
      filename: string
      mediaType: string | null
      sizeBytes: number | null
    }
```

State additions:

```ts
const [selectedWorkspaceFiles, setSelectedWorkspaceFiles] = useState<WorkspaceFileItem[]>([])
const [workspaceFileQuery, setWorkspaceFileQuery] = useState("")
const [workspaceFileOptions, setWorkspaceFileOptions] = useState<WorkspaceFileItem[]>([])
```

Autocomplete behavior:

- `@` opens the reference menu.
- Arrow keys move through both groups.
- `Enter` and `Tab` select the active option.
- `Escape` dismisses the current query.
- Selecting an agent calls the existing insertion path.
- Selecting a file adds it to `selectedWorkspaceFiles` and removes or replaces the active `@` token.
- Selected files render as removable chips near uploaded attachments.
- Submitting the prompt sends `workspacePaths: selectedWorkspaceFiles.map(file => file.path)`.

API client additions:

```ts
async workspaceFiles(query: string, limit = 20): Promise<StudioWorkspaceFiles>
```

Message submit signature should include workspace paths:

```ts
appendMessage(
  content: string,
  files: FileUIPart[] = [],
  workspacePaths: string[] = [],
  clientMessageId?: string
)
```

## UX Details

The menu should be grouped and compact:

```text
Agents
  @software-architect
  @product-strategist

Files
  src/webapp_studio/frontend/components/studio/chat-panel.tsx
  src/webapp_studio/backend/api/studio_api_controller.py
```

For file rows, show:

- filename or path;
- optional size;
- optional media type or extension.

If no files match, keep agent results visible and show a quiet empty state for files only.

## Validation And Safety

Backend validation is required even if the frontend only sends options returned by the backend.

The backend must reject:

- `../` path traversal;
- absolute paths;
- symlinks resolving outside the workspace root;
- directories;
- missing files;
- files over the attachment size limit.

The frontend should treat backend failures as recoverable submit errors and keep the draft intact.

## Test Plan

Backend tests:

- workspace file search returns relative paths from `root_dir`;
- Git search excludes ignored files;
- non-Git fallback works;
- path traversal is rejected;
- absolute paths are rejected;
- directories are rejected;
- files above the limit are rejected;
- append message copies selected workspace files into conversation attachments.

Frontend tests:

- typing `@` opens the reference menu;
- agents are listed and filter by participant or alias;
- workspace files are requested and listed;
- keyboard navigation works across groups;
- selecting an agent inserts `@agent `;
- selecting a file adds a removable chip;
- submitting sends `workspacePaths`;
- failed submit preserves draft and selected files.

End-to-end smoke:

- start Studio from a workspace with known files;
- type `@`;
- select an agent;
- select a file;
- submit;
- verify the transcript contains the human message;
- verify the selected file appears in the Files inspector as an attachment.

## Recommended Implementation Order

1. Add backend workspace file search and tests.
2. Extend append message contracts with `workspace_paths` and tests.
3. Add frontend schemas and API client methods.
4. Refactor `ChatPanel` autocomplete from mention-only to reference options.
5. Render selected workspace file chips.
6. Add focused frontend tests.
7. Run a local Studio smoke test in the browser.
