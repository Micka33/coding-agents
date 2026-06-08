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

defaults:
  root_dir: "."
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
| `defaults` | No | Shared runtime defaults for models, storage, execution, and memory. |
| `custom_tools` | No | Tool factories that can be reused from toolsets. |
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

`defaults.root_dir` is the runtime workspace root used for filesystem tools,
memory files, and project skills. Relative values are resolved from the current
working directory of the process, not from the `team.yaml` file.

Configuration strings can use single-brace substitutions:

| Placeholder | Source | Behavior |
| --- | --- | --- |
| `{root_dir}` | `defaults.root_dir` | Inserts the configured root string. |
| `{name}` | `--var name=value` or `TeamInstanciator.instantiate(..., variables={...})` | Inserts the run variable. |
| Unknown placeholders | None | Left unchanged. |

## Defaults

`defaults` controls values inherited by agents and runtime components.

| Key | When omitted | Behavior |
| --- | --- | --- |
| `root_dir` | `"."` | Workspace root for runtime file access. |
| `model.env` | None | Runtime config key or environment variable to read first. |
| `model.default` | None | Fallback model for agents with `model: inherit`. Inherited agents must resolve a model from `env` or `default`. |
| `reasoning_effort.env` | None | Runtime config key or environment variable to read first. |
| `reasoning_effort.default` | None | Fallback reasoning effort. If both `env` and `default` are absent, no reasoning-effort parameter is sent. If `env` is set with no default, inherited agents require that runtime value. |
| `checkpointer.env` | None | Runtime config key or environment variable selecting the checkpointer backend. |
| `checkpointer.default` | `memory` | Supported backends are `memory` and `sqlite`. `postgres` is parsed but currently raises at instantiation. |
| `checkpointer.sqlite_path.env` | None | Runtime config key or environment variable for the SQLite file. |
| `checkpointer.sqlite_path.default` | `.team-instanciator/checkpoints.sqlite` | SQLite path when the backend is `sqlite`. Relative paths are under `root_dir`. |
| `execution_backend.env` | None | Runtime config key or environment variable selecting command execution. |
| `execution_backend.default` | `none` | Use `local` to enable a local shell backend for agents with the `shell` toolset. |
| `memory.error_when_missing` | `false` | If `true`, missing inherited memory files fail instantiation. |
| `memory.candidates` | `[]` | Files offered as inherited Deep Agents memory. A leading `/` is treated as relative to `root_dir`. |

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
| `write_file` | Writes a file under `root_dir`. |
| `edit_file` | Replaces the first matching text occurrence in a file under `root_dir`. |
| `execute` | Runs a local shell command from `root_dir`. |

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
- Every referenced toolset and custom tool must exist.
- Custom tool `exposes` must exactly match returned tool names.
- Relation endpoints must reference declared agents.
- `tool` relations require `tool_name`; `subagent` relations must not set it.
- Conversation participants must be `deepagent`.
- Conversation defaults and aliases must point to valid, non-conflicting
  participants.
