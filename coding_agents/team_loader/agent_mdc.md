# Agent `.mdc` Reference

Agent files live under `coding_agents/teams/<team>/agents/*.mdc`.

Each `.mdc` file combines two parts:

1. YAML frontmatter between the first two `---` separators.
2. A Markdown body after the second `---`.

Example:

```md
---
schema_version: 1
name: developer
description: Implements a bounded development task after readiness approval.
toolsets:
  - scoped_read_tools
  - write
  - shell
  - web
state:
  persistence: disposable
---

You are a developer in a development-agent team.
```

The frontmatter configures the agent. The Markdown body is the agent system
prompt.

## Frontmatter Keys

### `schema_version`

Integer schema version for the agent file.

```yaml
schema_version: 1
```

An unsupported version produces a configuration error.

### `name`

Runtime or display name for the agent.

```yaml
name: developer
```

This usually matches the canonical agent id from `team.yaml`.

The canonical agent id is declared in `team.yaml` under `agents`. Do not repeat
it in the `.mdc` frontmatter.

### `description`

Short description of the agent role.

```yaml
description: Validates acceptance criteria, defines and runs or recommends tests, and reports residual quality risk.
```

For subagents, this is used as the subagent description. For the entrypoint, it
is optional unless the runtime needs a display summary.

### `model`

Optional model override for this agent.

```yaml
model: inherit
```

Supported values by convention:

- `inherit`: use the run-level or team-level model.
- a model string such as `openai:gpt-5.4`: use that model.

When an agent sets a model string, that model is used for that agent only. The
team-level model is still used by agents that omit `model` or set
`model: inherit`.

Model names use the LangChain `provider:model` format. The official LangChain
documentation explains this format and where to find available model names by
provider:
https://docs.langchain.com/oss/python/concepts/providers-and-models

If the key is absent, behavior is equivalent to `model: inherit`. If the
team-level model has no default, inherited agents require the configured
team-level model environment variable at runtime.

### `reasoning_effort`

Optional reasoning-effort override for this agent.

```yaml
reasoning_effort: inherit
```

Supported values by convention:

- `inherit`: use the run-level or team-level reasoning effort.
- `null`: request no explicit reasoning effort.
- a provider-supported value, for example `none`, `low`, `medium`, or `high`.

When an agent sets a provider-supported value, that reasoning effort is used for
that agent only. When an agent sets `null`, no reasoning-effort parameter is sent
for that agent.

If the key is absent, behavior is equivalent to `reasoning_effort: inherit`. If
the team-level reasoning effort has no default, inherited agents require the
configured team-level reasoning-effort environment variable at runtime.

### `variables`

Variables available to the Markdown body.

```yaml
variables:
  system_spec_path: docs/development-agent-team-architecture.md
  artifacts_dir: "{artifacts_dir}"
```

Values can contain template expressions. They are resolved before the prompt is
rendered.

The Markdown body can then reference these variables:

```md
{{ artifacts_dir }}
```

### `toolsets`

List of toolsets requested by the agent.

```yaml
toolsets:
  - scoped_read_tools
  - write
  - shell
  - web
```

Each value must reference a toolset declared in `team.yaml`.

`toolsets` describe the agent's technical capabilities. They do not encode
workflow modes or permission policy. The runtime can still apply stricter
permissions.

### `state`

Agent state and persistence configuration.

```yaml
state:
  persistence: disposable
```

The `state` key is optional.

Default behavior when `state` is absent:

- an agent used as a `subagent` is `disposable`
- an agent called through a `tool` relation is `persistent`
- the `entrypoint` agent is `persistent`

In practice, `state.persistence` makes explicit a behavior that should not only
be inferred from topology.

#### `state.persistence`

Conversation persistence behavior.

Possible values:

```yaml
persistence: disposable
persistence: persistent
persistence: inherit
```

`disposable` means each delegation can be treated as stateless, with no durable
conversation history owned by the agent.

`persistent` means the agent keeps stable conversation history across calls.

`inherit` means the agent follows the default behavior inferred from topology
and from the relation used to call it.

If `state.persistence` is omitted, behavior is equivalent to `inherit`.

### `skills`

Configures the skills available to this agent.

```yaml
skills: inherit
```

Possible values:

- `inherit`: use the skills active for the run.
- `none`: disable inherited skills for this agent.
- a list of skill names.

Example with skills dedicated to one agent:

```yaml
skills:
  - langchain-rag
  - github:gh-fix-ci
```

`skills` contains skill ids, not file paths.

A skill is a directory that contains a `SKILL.md` file.

Placement convention:

```text
.agents/skills/<skill-id>/SKILL.md
$CODEX_HOME/skills/<skill-id>/SKILL.md
```

Example project skill:

```text
.agents/skills/my-api-client/SKILL.md
```

Reference it like this:

```yaml
skills:
  - my-api-client
```

Project skills make the configuration portable with the repository. Skills in
`$CODEX_HOME/skills` are personal to the user.

Recommended resolution order:

1. project skills in `.agents/skills/`
2. user skills in `$CODEX_HOME/skills/`
3. skills provided by plugins or by the environment

Use a list when an agent needs personal or more specialized skills than the run
provides. Use `none` to isolate an agent from global skills. If the key is
absent, behavior is equivalent to `inherit`.

### `memory`

Configures memory files visible to this agent.

```yaml
memory: inherit
```

Possible values:

- `inherit`: use the run memory files.
- `none`: use no memory files for this agent.
- a list of memory file paths.

Example:

```yaml
memory:
  - /AGENTS.md
  - /docs/development-agent-team-architecture.md
```

Use a list when an agent should see specific stable context. Use `none` for an
agent that should not receive project memory. If the key is absent, behavior is
equivalent to `inherit`.

### `debug`

Configures debug behavior for this agent.

```yaml
debug: inherit
```

Supported values:

- `inherit`: use the run-level debug flag.
- `true`: enable debug for this agent.
- `false`: disable debug for this agent.

Use `true` to diagnose one specific agent without enabling debug for the whole
team. Use `false` to keep an agent quiet even when the run is in debug mode. If
the key is absent, behavior is equivalent to `inherit`.

## Markdown Body

The Markdown body after the frontmatter is the system prompt.

It can use frontmatter variables:

```md
Primary workflow artifact folder:

- /{{ artifacts_dir }}
```

It can include shared fragments:

```md
{{ include:../prompts/common/clarification-rule.md }}
```

Relative include paths are resolved from the `.mdc` file.
