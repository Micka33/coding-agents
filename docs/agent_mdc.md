# Agent `.mdc`

An agent `.mdc` file contains the agent's frontmatter and system prompt.
`team.yaml` decides which agent id uses the file, whether it is an entrypoint,
and how other agents can call it.

```text
---
schema_version: 1
description: Use to implement a bounded development task.
model: inherit
reasoning_effort: inherit
toolsets:
  - scoped_read_tools
  - write
  - shell
state:
  persistence: disposable
---

You are a developer in a development-agent team.
```

## File Shape

| Part | Purpose |
| --- | --- |
| YAML frontmatter | Optional agent-local options: prompt variables, model override, toolsets, memory, skills, and debug. |
| Markdown body | The system prompt passed to the agent after includes and variables are rendered. |

Frontmatter is optional. When present, the file must start with `---`, close the
frontmatter with a second `---`, and parse to a mapping. A file that does not
start with `---` is treated as a body-only prompt with empty frontmatter; supply
its agent-local options from the `team.yaml` agent entry instead. An empty
frontmatter block (`---` immediately followed by `---`) is also allowed.

Every frontmatter key can also be set on the `team.yaml` agent entry. When the
same key is set in both places, the `team.yaml` entry wins. See
[Overrides From team.yaml](#overrides-from-teamyaml).

The canonical agent id is the key in `team.yaml` under `agents`. A frontmatter
`name` key is ignored by the current loader; do not rely on it for ids,
relations, mentions, or display names.

## Frontmatter Keys

| Key | Default | Behavior |
| --- | --- | --- |
| `schema_version` | None | Conventionally `1`. The current loader parses it but does not validate agent schema versions. |
| `description` | None | Short role summary. Used in subagent listings and public conversation identity refreshes. If absent, subagent listings fall back to the agent id. |
| `model` | `inherit` | `inherit` uses the team default. A model string overrides this agent only. `null` behaves like absence and inherits. |
| `reasoning_effort` | `inherit` | `inherit` uses the team default. A non-empty string is passed as the provider reasoning effort. `null` behaves like absence and inherits. |
| `variables` | `{}` | Values available to the Markdown body as `{{ variable }}`. |
| `toolsets` | `[]` | Toolset names declared in `team.yaml`. |
| `state.persistence` | `inherit` | Accepted values: `inherit`, `disposable`, `persistent`. Currently validated and stored, but not used to change runtime behavior. |
| `skills` | `inherit` | `inherit` uses the team's effective skill source roots, `none` disables skills, and `only` restricts the visible catalog by skill id. Legacy lists are treated as `only`. |
| `memory` | `inherit` | `inherit` uses team default memory files, `none` disables memory, and a list uses those files. |
| `debug` | `inherit` | Only literal `true` enables debug in the current factories. |

## Overrides From team.yaml

Frontmatter holds an agent's default options. The same agent-local keys may also
appear directly on the `team.yaml` agent entry, where they override the `.mdc`
frontmatter. This lets several agents share one prompt file while differing only
in configuration.

Resolution order, highest priority first:

1. `team.yaml` agent entry
2. `.mdc` frontmatter
3. team `defaults` (reached when `model`, `reasoning_effort`, `memory`, or
   `skills` resolve to `inherit`)

Overridable keys: `description`, `model`, `reasoning_effort`, `variables`,
`toolsets`, `state`, `skills`, `memory`, `debug`.

Most keys replace the frontmatter value outright (for example `toolsets`
replaces the whole list). `variables` is merged key by key, so a `team.yaml`
entry can add or change one variable without restating the others.

Example: two agents reuse one body-only prompt file with different models.

```yaml
# team.yaml
agents:
  fast-reviewer:
    kind: subagent
    config: ./agents/reviewer.md
    model: openai:gpt-5.4-mini
  deep-reviewer:
    kind: subagent
    config: ./agents/reviewer.md
    model: openai:gpt-5.5
    reasoning_effort: high
```

```text
# agents/reviewer.md (no frontmatter)
You are a code reviewer. Prioritize correctness, then tests, then clarity.
```

## Description

Keep `description` short and action-oriented:

```yaml
description: Use to validate acceptance criteria and report residual quality risk.
```

For a `subagent` relation, parent agents see the target id and description when
choosing whether to delegate.

For public conversation participants, identity refresh messages include the id,
aliases, and description so other participants know whom to mention.

## Model And Reasoning

Use `inherit` unless one agent needs a different model or reasoning setting:

```yaml
model: openai:gpt-5.5
reasoning_effort: high
```

Model strings use the LangChain `provider:model` style.

Reasoning-effort values are provider-specific. Use `none` when you want the
literal value `none` sent to the provider. Do not use `null` to disable
reasoning for one agent; in frontmatter, `null` inherits from the team default.

If an agent inherits `model`, the team default model must resolve from runtime
configuration or `defaults.model.default`.

## Variables And Includes

Frontmatter variables can reference team/run variables with single braces:

```yaml
variables:
  system_spec_path: docs/development-agent-team-architecture.md
  artifacts_dir: "{artifacts_dir}"
```

The Markdown body uses double braces:

```md
Primary workflow artifact folder:

- /{{ artifacts_dir }}
```

Unknown body variables stay unchanged. Variables with `null` values render as an
empty string.

Prompt fragments can be included from the body:

```md
{{ include:../prompts/common/clarification-rule.md }}
```

Include paths are relative to the `.mdc` file. Includes can be nested. Missing
or recursive includes fail loading.

## Toolsets

`toolsets` lists capabilities declared in `team.yaml`:

```yaml
toolsets:
  - scoped_read_tools
  - write
  - shell
  - web
```

Every listed toolset must exist in the team file. Toolsets describe what the
agent can do; `team.yaml` owns the actual tool definitions and permission
effects.

## State

```yaml
state:
  persistence: disposable
```

Accepted values are `inherit`, `disposable`, and `persistent`.

Current runtime note: this field is validated and kept on the loaded agent, but
the factories do not yet use it to choose thread lifetime or checkpointer
behavior. Invocation topology still determines how the agent is called:
entrypoint graph, relation tool target, public mention participant, or task
subagent.

## Skills

```yaml
skills:
  only:
    - langchain-rag
    - github-gh-fix-ci
```

`inherit` or an omitted `skills` key gives the agent the team's effective skill
source roots. The runtime resolves source roots from user, project, and team
locations, then passes virtual source roots such as `/skills/project` to Deep
Agents.

Use `none` to disable skills for an agent:

```yaml
skills: none
```

Use `only` when an agent should see just a subset of the discovered catalog.
Each listed id must exist in at least one effective source root.

Legacy list syntax is accepted during migration and is interpreted as `only`:

```yaml
skills:
  - langchain-rag
```

Do not put filesystem paths in `.mdc` files. `team.yaml` owns skill source
locations; `.mdc` frontmatter only chooses the policy for this agent.

## Memory

```yaml
memory:
  - /AGENTS.md
  - /docs/development-agent-team-architecture.md
```

Memory values are file paths under the agent's resolved working directory. A
leading `/` is stripped before resolving the file, so `/AGENTS.md` means
`<agent-working-directory>/AGENTS.md`.

| Value | Behavior |
| --- | --- |
| `inherit` or absent | Use `defaults.memory.candidates` from `team.yaml`. Missing files are ignored or rejected according to `defaults.memory.error_when_missing`. |
| `none` | Pass no memory files. |
| list | Use the listed files. Missing files fail loading for this agent. |

## Debug

```yaml
debug: true
```

Only literal `true` enables debug for this agent. `false`, `inherit`, and an
absent key leave debug off in the current factories.

## Body

The Markdown body is the system prompt. Write it as instructions to the agent,
not as configuration reference. Prefer concrete behavior, boundaries, and output
requirements:

```md
You are a code-reviewer.

Review changes as if they were a pull request. Prioritize bugs, regressions,
missing tests, and unclear acceptance criteria.
```

Configuration such as `kind`, `entrypoint`, relation names, public aliases, and
tool implementations belongs in `team.yaml`, not in the `.mdc` body.

## Common Mistakes

- Adding `name` to frontmatter and expecting it to define the agent id.
- Putting `kind`, `entrypoint`, relation tools, or conversation aliases in the
  `.mdc` file instead of `team.yaml`.
- Using `reasoning_effort: null` to disable reasoning; it inherits instead.
- Expecting `state.persistence` to change runtime persistence today.
- Referencing a toolset that is not declared in `team.yaml`.
