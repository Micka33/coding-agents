# `team.yaml` Reference

This document describes the YAML keys used by
`coding_agents/teams/software/team.yaml`.

`team.yaml` describes the team topology and shared loading rules.

## Top-Level Keys

### `schema_version`

Integer schema version for the team file.

```yaml
schema_version: 1
```

An unsupported version produces a configuration error.

### `id`

Stable team identifier.

```yaml
id: software
```

This value identifies the team configuration. It is not a runtime thread and not
an agent.

### `description`

Human-readable description.

```yaml
description: Current software development-agent team topology.
```

### `defaults`

Global default values.

#### `defaults.root_dir`

Repository root used for relative paths.

```yaml
root_dir: "."
```

#### `defaults.model`

Default model configuration.

```yaml
model:
  env: CODING_AGENTS_MODEL
  default: null
```

`env` is the environment variable read first.

`default` is used when the environment variable is absent. `default: null`
makes `CODING_AGENTS_MODEL` required at runtime for agents that inherit the
team-level model.

Model names use the `provider:model` format, for example `openai:gpt-5.4`.
LangGraph uses LangChain chat models for model integration. The official
LangChain documentation explains this format and where to find available model
names by provider:
https://docs.langchain.com/oss/python/concepts/providers-and-models

#### `defaults.reasoning_effort`

Default reasoning effort configuration.

```yaml
reasoning_effort:
  env: CODING_AGENTS_REASONING_EFFORT
  default: null
```

`default: null` makes `CODING_AGENTS_REASONING_EFFORT` required at runtime for
agents that inherit the team-level reasoning effort.

For OpenAI reasoning models, the common values exposed by LangChain are:

```yaml
reasoning_effort:
  default: minimal
```

```yaml
reasoning_effort:
  default: low
```

```yaml
reasoning_effort:
  default: medium
```

```yaml
reasoning_effort:
  default: high
```

Some LangChain/OpenAI surfaces also document `none` and `xhigh`, depending on
the model and API surface. To verify available values, consult the official
LangChain documentation:

- Python `langchain-openai` reference for `reasoning_effort`:
  https://reference.langchain.com/python/langchain-openai/chat_models/base/BaseChatOpenAI/reasoning_effort
- LangChain/LangSmith model provider and model parameter page:
  https://docs.langchain.com/langsmith/playground-model-providers

#### `defaults.checkpointer`

Default persistence configuration.

```yaml
checkpointer:
  env: CODING_AGENTS_CHECKPOINTER
  default: sqlite
  sqlite_path:
    env: CODING_AGENTS_SQLITE_CHECKPOINT_PATH
    default: .coding-agents/checkpoints.sqlite
  postgres_url:
    env:
      - CODING_AGENTS_POSTGRES_URL
      - DATABASE_URL
    default: null
```

`env` is the environment variable that selects the checkpointer backend.

`default` is the backend used when no environment variable is set.

`sqlite_path.env` is the environment variable for the SQLite path.

`sqlite_path.default` is the default SQLite path, relative to the repository.

`postgres_url.env` is the ordered list of environment variables checked for a
Postgres URL.

`postgres_url.default` is used when none of the listed variables exists.

#### `defaults.execution_backend`

Global command-execution backend selector.

```yaml
execution_backend:
  env: CODING_AGENTS_EXECUTION
  default: local
```

This is a run-level setting. Agents express capabilities through `toolsets`;
backend needs are derived from those toolsets.

Possible values:

- `local`: enables a local backend for filesystem tools and, for agents with the
  `shell` toolset, command execution through `execute`.
- `none`: disables local command execution. Tools that require `shell` must not
  expose `execute`.

Official Deep Agents backend documentation, including `FilesystemBackend`,
`LocalShellBackend`, sandbox backends, and the `execute` tool:
https://docs.langchain.com/oss/python/deepagents/backends

#### `defaults.memory`

Memory-file discovery configuration.

```yaml
memory:
  error_when_missing: false
  candidates:
    - /AGENTS.md
    - /docs/development-agent-team-architecture.md
```

`error_when_missing` controls what happens when a file listed in `candidates`
does not exist.

`false` is the default: missing files are ignored.

`true` makes every listed file required. If a file is missing, the configuration
is invalid.

`candidates` is the ordered list of virtual or repository-rooted memory files.

### `custom_tools`

Declares custom tool factories that `toolsets` can reference.

```yaml
custom_tools:
  scoped_read_tools:
    factory: src.team_instanciator.tools.scoped_read_tools_factory:create_scoped_read_tools
    exposes:
      - ls
      - read_file
      - glob
      - grep
```

Each key under `custom_tools` is a custom tool id.

`factory` is an import path in `module:function` format. This function is called
to create the tools. The function must use the standard custom-tool factory
signature:

```python
from collections.abc import Mapping, Sequence

from langchain_core.tools import BaseTool

from src.team_instanciator.tools.custom_tool_context import CustomToolContext


def create_tools(
    context: CustomToolContext,
    args: Mapping[str, object],
) -> Sequence[BaseTool]:
    ...
```

The factory receives two inputs:

- `context`: runtime values provided by the team instantiator.
- `args`: the user-defined mapping from `custom_tools.<id>.args` after variable
  substitution.

Every custom factory receives the same `CustomToolContext`:

- `context.root_dir`: resolved repository root for this team.
- `context.env`: read-only environment view. Use `context.env.get("NAME")` for
  optional values and `context.env.require("NAME")` for required values.
- `context.runtime_config`: runtime configuration values passed to the
  instantiator, including values loaded from `.env` or CLI `--config`.
- `context.agent_config`: the agent definition that requested this tool through
  one of its `toolsets`.
- `context.team_config`: the full loaded team definition.
- `context.history`: high-level conversation-history helpers for the current
  tool call.
- `context.checkpointer`: the underlying LangGraph checkpointer when direct
  checkpoint access is necessary.

Tool functions should expose only task-specific parameters to the model. Do not
add `root_dir`, environment values, agent config, team config, or checkpointer
parameters to the tool input schema; they are already available through
`context`.

`args` is a mapping of named arguments passed to the factory after variable
substitution. Use it for user-visible configuration such as limits, labels,
allowed paths, or feature toggles.

For example, the scoped read tools use `context.root_dir` by default. Do not set
`args.root_dir` unless this tool must deliberately read from another root or a
subdirectory:

```yaml
custom_tools:
  docs_read_tools:
    factory: src.team_instanciator.tools.scoped_read_tools_factory:create_scoped_read_tools
    args:
      root_dir: "{root_dir}/docs"
    exposes:
      - ls
      - read_file
      - glob
      - grep
```

Configuration strings support single-brace substitutions. These substitutions
are resolved before factories are called.

| Substitution | Source | Effect |
| --- | --- | --- |
| `{root_dir}` | `defaults.root_dir` | Inserts the team root exactly as configured in `team.yaml`. Use it only when a config value must explicitly contain that path; custom factories already receive the resolved root as `context.root_dir`. |
| `{name}` | A template variable passed to `TeamInstanciator.instantiate(..., variables={...})` or the instantiator CLI `--var name=value` | Inserts that user-provided value wherever the placeholder appears. Use this for team-file parameters that should vary between runs, such as labels, tool limits, or path suffixes. |
| Unknown placeholders | No matching built-in or user-provided variable | Remain unchanged in the loaded configuration, for example `{missing}` stays `{missing}`. |

`exposes` is the whitelist of tools the factory must expose. Every listed tool
must be returned by the factory, otherwise the configuration is invalid. Any tool
returned by the factory but absent from `exposes` also makes the configuration
invalid.

Factories should return tools whose result is immediately useful to the calling
agent. Prefer dictionaries or concise strings that say what happened and include
the values the agent needs for its next step.

Example custom factory:

```python
from collections.abc import Mapping, Sequence

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, StructuredTool

from src.team_instanciator.tools.custom_tool_context import CustomToolContext


def create_tools(
    context: CustomToolContext,
    args: Mapping[str, object],
) -> Sequence[BaseTool]:
    label = str(args.get("label", context.agent_config.id))
    keep_last = int(args.get("keep_last", 20))

    def conversation_stats(runtime: ToolRuntime) -> dict[str, object]:
        """Return visible conversation statistics for the current thread."""

        messages = context.history.current_messages(runtime)
        return {
            "label": label,
            "thread_id": context.history.thread_id(runtime),
            "message_counts": context.history.count_messages(messages),
        }

    def compact_context(summary: str, runtime: ToolRuntime):
        """Replace old context with a summary and keep recent messages."""

        return context.history.compact_messages_command(
            runtime,
            summary=summary,
            keep_last=keep_last,
            visible_result=f"Context compacted for {label}; kept the last {keep_last} messages.",
        )

    return [
        StructuredTool.from_function(conversation_stats, name="conversation_stats"),
        StructuredTool.from_function(compact_context, name="compact_context"),
    ]
```

When a tool changes conversation history, use `context.history` helpers and
return a LangGraph `Command` with a visible `ToolMessage`. The helper
`compact_messages_command` already does this. Avoid writing directly to the
checkpointer for normal state updates; direct checkpointer writes are reserved
for advanced recovery or inspection tools.

### `toolsets`

Declares tool groups that agents can request from their `.mdc` frontmatter.

```yaml
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
```

Each key under `toolsets` is a toolset name.

An item can be a built-in tool name:

```yaml
- fetch_url
```

Or a custom tool reference:

```yaml
- custom: scoped_read_tools
```

Toolset names should describe capabilities, not the consuming agent.

### `agents`

Declares the team agents and each agent `.mdc` file.

```yaml
agents:
  developer:
    kind: subagent
    config: ./agents/developer.mdc
```

Each key under `agents` is the canonical agent id used by relations.

#### `agents.<agent_id>.kind`

Topological agent type.

Current values:

```yaml
kind: deepagent
kind: subagent
```

`deepagent` is a full agent with its own conversation cycle. Use it for agents
that can act as persistent collaborators or serve as the entrypoint.

`subagent` is a delegation agent. Another agent uses it through a `subagent`
relation or indirectly exposes it through a `tool` relation. By default, a
`subagent` is disposable unless its `.mdc` file declares a different persistence
behavior.

`kind` belongs in `team.yaml`, not in the agent `.mdc` file.

`kind`, relations, state, and toolsets determine the agent runtime shape.

#### `agents.<agent_id>.config`

Path to the agent `.mdc` file, relative to `team.yaml`.

```yaml
config: ./agents/developer.mdc
```

#### `agents.<agent_id>.entrypoint`

Marks the human-facing entrypoint agent.

```yaml
entrypoint: true
```

There must be exactly one entrypoint. `thread_id` values are managed
automatically and must not be written in `team.yaml`.

### `conversation`

Top-level `conversation` opts the team into the public mention-router
conversation bus. If this key is absent, no public conversation is created.

```yaml
conversation:
  mentions:
    max_parallel_agents: 2
    max_cascade_turns: null
  identity_refresh_after_tokens: 10000
  human_input:
    default_targets:
      - engineering-manager
```

`conversation.mentions.max_parallel_agents` defaults to `2`.
`conversation.mentions.max_cascade_turns` defaults to `null`, which means
unlimited. `identity_refresh_after_tokens` defaults to `10000`.

`human_input.default_targets` defaults to `[]`. Use it when an unmentioned
human message should wake one or more public participants.

An agent becomes mentionable only when its agent reference contains an
`agents.<agent_id>.conversation` block. Participants must be `kind: deepagent`.

```yaml
agents:
  product-analyst:
    kind: deepagent
    config: ./agents/product-analyst.mdc
    conversation:
      aliases:
        - product
        - product-analyst
```

Aliases live in `team.yaml` and resolve to canonical agent ids. Unknown mentions
and mentions of non-participants remain visible text and do not wake agents.

### `relations`

Declares directed links between agents.

```yaml
relations:
  - from: developer
    to: qa-engineer
    relation: tool
    tool_name: ask_qa_engineer
    input_schema:
      message: string
    description: >
      Ask the qa-engineer to run tests, linters, build commands and report the results.
```

#### `relations[].from`

Source agent id. It must reference an agent declared under `agents`.

#### `relations[].to`

Target agent id. It must reference an agent declared under `agents`.

#### `relations[].relation`

Relation type.

Current values:

```yaml
relation: tool
relation: subagent
```

`tool` adds a concrete tool to the source agent. That tool calls the target
agent.

`subagent` means the source agent can delegate to the target agent as a
subagent.

#### `relations[].tool_name`

Name of the tool injected for `relation: tool`.

```yaml
tool_name: ask_qa_engineer
```

This key is required for `relation: tool` and must be omitted for
`relation: subagent`.

#### `relations[].input_schema`

Input schema for the generated tool.

Current shape:

```yaml
input_schema:
  message: string
```

This schema is valid and exposed through the generated tool.

#### `relations[].description`

Human-readable description. For `relation: tool`, it becomes the generated tool
description.
