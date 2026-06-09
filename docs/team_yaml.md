# `team.yaml`

`team.yaml` describes one runnable team: shared defaults, tool capability
groups, agents, directed relations, and optional public conversation routing.

Agent prompts live in `.mdc` files referenced from `team.yaml`. See
[`agent_mdc.md`](agent_mdc.md) for that file format.

## Quick Example

```yaml
schema_version: 1
id: software
description: A software development team.
working_directory: "."

defaults:
  model:
    env: CODING_AGENTS_MODEL
    default: openai:gpt-5.5
  reasoning_effort:
    env: CODING_AGENTS_REASONING_EFFORT
    default: xhigh
  checkpointer:
    env: CODING_AGENTS_CHECKPOINTER
    default: sqlite
    sqlite_path:
      env: CODING_AGENTS_SQLITE_CHECKPOINT_PATH
      default: .coding-agents/checkpoints.sqlite
  execution_backend:
    env: CODING_AGENTS_EXECUTION
    default: local
  memory:
    error_when_missing: false
    candidates:
      - /AGENTS.md

custom_tools:
  scoped_read_tools:
    factory: src.team_instanciator.tools.scoped_read_tools_factory:create_scoped_read_tools
    exposes:
      - ls
      - read_file
      - glob
      - grep

toolsets:
  web:
    - web_search
    - fetch_url
  scoped_read_tools:
    - custom: scoped_read_tools
  write:
    - write_file
    - edit_file
  shell:
    - execute

agents:
  engineering-manager:
    kind: deepagent
    config: ./agents/engineering-manager.mdc
    relative_working_directory: "."
    entrypoint: true
    enable_general_purpose_subagent: false

  developer:
    kind: subagent
    config: ./agents/developer.mdc

relations:
  - id: implement
    from: engineering-manager
    to: developer
    relation: subagent
```

## File Shape

| Key | Required | Purpose |
| --- | --- | --- |
| `schema_version` | Yes | Must be `1`. |
| `id` | Yes | Stable team id. It is also the default root thread id. |
| `description` | No | Display summary for people and tooling. |
| `working_directory` | No | Team runtime scope. Defaults to `"."`. |
| `defaults` | No | Shared runtime defaults for models, storage, execution, and memory. |
| `custom_tools` | No | Tool factories that can be reused from toolsets. |
| `mcp_servers` | No | Local or hosted MCP servers that can be reused from toolsets. |
| `toolsets` | No | Named groups of tools that agents request from `.mdc` frontmatter. |
| `agents` | Yes | Canonical agent ids and paths to their `.mdc` files. |
| `relations` | No | Directed links that expose agents as tools or subagents. |
| `conversation` | No | Public mention-router conversation settings. |

The loader accepts a small YAML subset: mappings, lists, comments, strings,
integers, booleans, `null`, quoted strings, `[]`, `{}`, folded scalars (`>`),
and literal scalars (`|`). Keep configuration in simple block-style YAML.

## Names And Paths

Agent ids are the keys under `agents`. References in `relations`,
`conversation.human_input.default_targets`, and mentions are matched
case-insensitively and then stored with the canonical casing from `agents`.

`agents.<id>.config` is resolved relative to the directory containing
`team.yaml`.

`working_directory` is the team workspace scope. Relative values are resolved
from the current working directory captured when the team is loaded, not from
the `team.yaml` file. Absolute values are allowed.

SQLite checkpointer storage and project skills are not scoped by
`working_directory`. Relative SQLite paths resolve from the current working
directory captured when the CLI is launched. Project skills resolve from
`.agents/skills` under that same current working directory.

`agents.<id>.relative_working_directory` is resolved relative to the team
`working_directory`. It defaults to `"."`, must be relative, must point to an
existing directory, and must stay inside the team `working_directory`. Agent
filesystem tools, shell commands, and memory checks run from this resolved agent
directory.

Configuration strings can use single-brace substitutions:

| Placeholder | Source | Behavior |
| --- | --- | --- |
| `{working_directory}` | `working_directory` | Inserts the configured working-directory string. |
| `{name}` | `--var name=value` or `TeamInstanciator.instantiate(..., variables={...})` | Inserts the run variable. |
| Unknown placeholders | None | Left unchanged. |

## Defaults

`defaults` controls values inherited by agents and runtime components.

| Key | When omitted | Behavior |
| --- | --- | --- |
| `model.env` | None | Runtime config key or environment variable to read first. |
| `model.default` | None | Fallback model for agents with `model: inherit`. Inherited agents must resolve a model from `env` or `default`. |
| `reasoning_effort.env` | None | Runtime config key or environment variable to read first. |
| `reasoning_effort.default` | None | Fallback reasoning effort. If both `env` and `default` are absent, no reasoning-effort parameter is sent. If `env` is set with no default, inherited agents require that runtime value. |
| `checkpointer.env` | None | Runtime config key or environment variable selecting the checkpointer backend. |
| `checkpointer.default` | `memory` | Supported backends are `memory` and `sqlite`. `postgres` is parsed but currently raises at instantiation. |
| `checkpointer.sqlite_path.env` | None | Runtime config key or environment variable for the SQLite file. |
| `checkpointer.sqlite_path.default` | `.team-instanciator/checkpoints.sqlite` | SQLite path when the backend is `sqlite`. Relative paths are under the CLI launch current working directory. |
| `execution_backend.env` | None | Runtime config key or environment variable selecting command execution. |
| `execution_backend.default` | `none` | Use `local` to enable a local shell backend for agents with the `shell` toolset. |
| `memory.error_when_missing` | `false` | If `true`, missing inherited memory files fail instantiation. |
| `memory.candidates` | `[]` | Files offered as inherited Deep Agents memory. A leading `/` is treated as relative to each agent's resolved working directory. |

Runtime config values can come from process environment, `.env`, CLI
`--config key=value`, or `config_variables`.

## Toolsets

Toolsets are named capability groups. Agents request them from their `.mdc`
frontmatter:

```yaml
toolsets:
  web:
    - web_search
    - fetch_url
  shell:
    - execute
```

Built-in tool names:

| Tool | Visible behavior |
| --- | --- |
| `web_search` | Searches with Tavily when `TAVILY_API_KEY` is configured; otherwise returns an empty result with a note. |
| `fetch_url` | Fetches textual URL content. |
| `write_file` | Writes a file under the agent's resolved working directory. |
| `edit_file` | Replaces the first matching text occurrence in a file under the agent's resolved working directory. |
| `execute` | Runs a local shell command from the agent's resolved working directory. |

The current runtime also gives special meaning to these toolset names:

| Toolset name | Runtime effect |
| --- | --- |
| `scoped_read_tools` | Allows read access for Deep Agents. Read-only LangChain subagents receive the custom read tools declared by the team. |
| `write` | Allows write access for Deep Agents. |
| `shell` | Enables a local shell backend only when `defaults.execution_backend` resolves to `local`. |

Other toolset names are valid as ordinary groups, but they do not change
filesystem permissions or shell backend selection unless the runtime is changed.

For Deep Agents, toolsets also control which Deep Agents built-in tools are
shown to the model:

| Capability | Visible Deep Agents built-ins |
| --- | --- |
| `scoped_read_tools` | `ls`, `read_file`, `glob`, `grep` |
| `write` | `write_file`, `edit_file` |
| `shell` with resolved `defaults.execution_backend: local` | `execute` |
| Declared `relation: subagent` or `enable_general_purpose_subagent: true` | `task` |

The permission layer still denies unauthorized filesystem operations if a call
reaches the tool layer, but unavailable Deep Agents built-ins are hidden from
the model before it can choose them.

Deep Agents' `write_todos` planning tool remains available as internal agent
scaffolding. It is not controlled by a `team.yaml` toolset.

## Custom Tools

`custom_tools` registers factories that `toolsets` can reference.

```yaml
custom_tools:
  scoped_read_tools:
    factory: src.team_instanciator.tools.scoped_read_tools_factory:create_scoped_read_tools
    args:
      label: docs
    exposes:
      - ls
      - read_file
      - glob
      - grep

toolsets:
  scoped_read_tools:
    - custom: scoped_read_tools
```

`factory` must use `module:function` format. The function is called as:

```python
def create_tools(context, args):
    ...
```

`args` is the rendered mapping from `custom_tools.<id>.args`. Use it for
user-facing options such as labels, limits, allowed paths, or feature toggles.

`exposes` must exactly match the names returned by the factory. Missing or extra
tools fail instantiation.

## MCP Servers

`mcp_servers` registers Model Context Protocol servers that `toolsets` can
reference directly.

```yaml
mcp_servers:
  time:
    transport: stdio
    command: uvx
    args:
      - mcp-server-time

toolsets:
  time:
    - mcp: time
```

The public `mcp-server-time` reference server exposes `get_current_time` and
`convert_time`. Because `exposes` is omitted in the example above, every tool
advertised by the server is visible to agents that request the `time` toolset.

Use `exposes` as an allowlist when only some server tools should be visible:

```yaml
mcp_servers:
  company_docs:
    transport: http
    url: https://mcp.example.com/mcp
    auth:
      type: bearer
      env: COMPANY_DOCS_MCP_TOKEN
    headers:
      X-Tenant:
        env: COMPANY_TENANT_ID
      X-Client: coding-agents
    exposes:
      - search_docs
      - fetch_doc

toolsets:
  docs:
    - mcp: company_docs
```

`transport` values:

| Transport | Required fields | Optional fields |
| --- | --- | --- |
| `stdio` | `command` | `args`, `env`, `cwd` |
| `http` | `url` | `headers`, `auth`, `timeout` |
| `streamable_http` | `url` | `headers`, `auth`, `timeout` |
| `sse` | `url` | `headers`, `auth`, `timeout` |

`http` is accepted as user-facing shorthand for `streamable_http`.
`timeout` is in seconds and defaults to `30`. For `stdio`, configured `env`
values are merged over the runtime/process environment.

Authentication supports common HTTP cases:

```yaml
auth:
  type: bearer
  env: MCP_TOKEN
```

```yaml
auth:
  type: api_key
  header: X-API-Key
  env: MCP_API_KEY
```

Header values can be strings or `{env: NAME}` references. Secret values should
come from environment variables, `.env`, CLI `--config`, or `config_variables`,
not from checked-in `team.yaml` files.

Advanced HTTP auth can use a factory:

```yaml
auth:
  type: custom
  factory: my_package.auth:create_httpx_auth
  args:
    audience: docs
```

The factory must accept `(context, args)` and return an auth object compatible
with the MCP HTTP client path.

Local `stdio` MCP servers execute the configured command. Treat MCP server
configuration as trusted team configuration, similar to shell-enabled teams.

## Agents

Each entry under `agents` declares one canonical agent id.

```yaml
agents:
  engineering-manager:
    kind: deepagent
    config: ./agents/engineering-manager.mdc
    entrypoint: true
    conversation:
      aliases:
        - manager
```

| Key | Required | Behavior |
| --- | --- | --- |
| `kind` | Yes | `deepagent` or `subagent`. |
| `config` | Yes | Path to the agent `.mdc` file, relative to `team.yaml`. |
| `relative_working_directory` | No | Path relative to the team `working_directory`. Defaults to `"."`. |
| `entrypoint` | No | Exactly one agent must have `entrypoint: true`. |
| `enable_general_purpose_subagent` | No | Deep Agents only. Defaults to `false`. Set to `true` to expose the default `general-purpose` subagent through the `task` tool. |
| `conversation` | No | Makes a `deepagent` available on the public mention bus. |

Use `deepagent` for agents that can run as first-class collaborators or
relation-tool targets. Use `subagent` for agents meant to be delegated to from a
parent agent.

Public conversation participants must be `kind: deepagent`.

`enable_general_purpose_subagent` is valid only for `kind: deepagent`. It is
disabled by default so `task` access comes only from explicit team topology
unless this opt-in is set:

```yaml
agents:
  Francis-Bacon:
    kind: deepagent
    config: ./agents/francis-bacon.mdc
    enable_general_purpose_subagent: true
```

## Relations

Relations connect a source agent to a target agent.

```yaml
relations:
  - id: qa-review
    from: developer
    to: qa-engineer
    relation: tool
    tool_name: ask_qa_engineer
    input_schema:
      message: string
    description: Ask QA to run checks and report the result.
```

| Key | Required | Behavior |
| --- | --- | --- |
| `id` | No | Stable relation id. Recommended when persisted history matters. |
| `from` | Yes | Source agent id. |
| `to` | Yes | Target agent id. |
| `relation` | Yes | `tool` or `subagent`. |
| `tool_name` | For `tool` only | Name of the generated tool on the source agent. Must be omitted for `subagent`. |
| `input_schema` | No | Current relation tools accept `message: string`. Keep this shape for generated relation tools. |
| `description` | No | Description shown on generated `tool` relations. |

`relation: tool` adds a named tool to the source agent. Calling that tool sends
the `message` to the target agent and returns the target's final text.

`relation: subagent` makes the target available through the source agent's
delegation mechanism.

Declaring `relation: subagent` exposes only the declared target agent through
delegation. It does not implicitly enable the default Deep Agents
`general-purpose` subagent.

When `id` is omitted, the loader assigns an order-based id such as
`relation_001`. Use explicit ids before reordering or renaming relations if you
want persisted relation history to remain stable.

## Conversation

Top-level `conversation` opts the team into the public mention-router
conversation bus. If it is absent, the team still has an entrypoint graph, but
no public mention routing is created.

```yaml
conversation:
  mentions:
    max_parallel_agents: 2
    max_cascade_turns: null
    max_agent_failures: 2
  identity_refresh_after_tokens: 10000
  human_input:
    default_targets:
      - engineering-manager
```

An agent becomes mentionable only when its agent reference has a
`conversation` block:

```yaml
agents:
  software-architect:
    kind: deepagent
    config: ./agents/software-architect.mdc
    conversation:
      aliases:
        - architect
        - architecture
```

Mention behavior:

| Setting | Default | Behavior |
| --- | --- | --- |
| `mentions.max_parallel_agents` | `2` | Maximum agents running from the public queue at once. Must be positive. |
| `mentions.max_cascade_turns` | `null` | Maximum mention-triggered reply cascades. `null` means unlimited. |
| `mentions.max_agent_failures` | `2` | Positive failure limit stored with mention settings. |
| `identity_refresh_after_tokens` | `10000` | Token estimate after which participant identity context is refreshed. Must be positive. |
| `human_input.default_targets` | `[]` | Participants to wake for non-empty human messages that contain no mentions. |

Mentions use `@name` or `@alias`, outside inline code and fenced code blocks.
Unknown mentions remain visible text and do not wake agents. Self-mentions and
duplicate mentions in one message are ignored.

Aliases are case-insensitive. An alias cannot duplicate another alias or
conflict with another participant id.

## Validation Checklist

Before a team can instantiate:

- `schema_version` must be `1`.
- `id` must be non-empty.
- Agent ids must be unique after case-insensitive normalization.
- There must be exactly one entrypoint.
- Every agent `kind` must be `deepagent` or `subagent`.
- `enable_general_purpose_subagent` may be set only on `deepagent` entries.
- Every referenced toolset, custom tool, and MCP server must exist.
- Custom tool `exposes` must exactly match returned tool names.
- MCP `exposes` is optional. If present, it must list at least one tool and
  every listed tool must be returned by the MCP server.
- MCP `stdio` servers require `command`; HTTP-style servers require `url`.
- MCP auth config must use a supported type and required environment values
  must be available at instantiation time.
- Final tool names for each agent must not collide.
- Relation endpoints must reference declared agents.
- `tool` relations require `tool_name`; `subagent` relations must not set it.
- Conversation participants must be `deepagent`.
- Conversation defaults and aliases must point to valid, non-conflicting
  participants.
