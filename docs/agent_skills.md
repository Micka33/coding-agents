# Agent Skills

## Goal

Define how skills are discovered, selected, and exposed to agents.

Success criteria:

- Skills follow the Agent Skills directory shape.
- Reusable skills can be shared across teams.
- Team-specific skills can be vendored with the team.
- Agent `.mdc` files stay portable and do not depend on machine-specific paths.
- Skill source precedence is deterministic.
- Deep Agents receives skill source roots in the shape its skills middleware
  expects.
- Agents can read selected skill files without gaining general workspace read
  access.

## Core Model

Skills are organized as layered source roots.

Each source root contains zero or more skill directories:

```text
<source-root>/
  web-research/
    SKILL.md
    scripts/
    references/
  langchain-rag/
    SKILL.md
```

`SKILL.md` is the required entrypoint for a skill. Supporting files are optional
and belong inside the same skill directory.

The team runtime should pass source roots to Deep Agents, not individual skill
directories. Deep Agents scans each source root for child directories that
contain `SKILL.md`.

## Responsibility Split

`team.yaml` owns skill source roots.

Agent `.mdc` frontmatter owns whether the agent uses skills and, if needed,
which skill ids are visible to that agent.

`SKILL.md` owns the skill's instructions, metadata, and references to supporting
files.

Skill file access is separate from workspace file access. An agent may need to
read `SKILL.md` and supporting files even when it does not have a general
repository read toolset.

This keeps authoring simple:

- team authors decide where skills come from;
- agent authors decide whether an agent should use the available skill catalog;
- skill authors keep scripts and reference material next to the skill.

## Source Layers

Skill sources should be loaded from lowest priority to highest priority:

| Layer | Purpose | Example |
| --- | --- | --- |
| Built-in | Client or runtime-provided defaults | packaged Deep Agents skills |
| User | Personal skills shared across projects | `$CODEX_HOME/skills` |
| Project | Repository-wide reusable skills | `<cli-cwd>/.agents/skills` |
| Team | Skills vendored for one team | `<team-dir>/skills` |

If two layers provide the same skill id, the higher-priority layer wins.

The built-in layer is optional. If this runtime has no bundled skills, no
built-in source is added.

Team-local skills are useful for vendoring, pinning, or overriding behavior for
one team. They should not be the only supported location. Reusable skills should
live in the project or user layer so multiple teams can share them.

The resolver should pass source labels to Deep Agents when supported, so the
prompt can distinguish sources that share a leaf directory name such as
`skills`.

## Path Semantics

Skill source roots are resolved by scope:

- User sources resolve from runtime configuration or environment, such as
  `$CODEX_HOME/skills`.
- Project sources resolve from the CLI launch CWD, such as
  `<cli-cwd>/.agents/skills`.
- Package sources resolve from `.coding-agents/skills` for installed package
  teams, restricted to dependency ids locked for that package.
- Team sources resolve relative to the directory containing `team.yaml`, such as
  `./skills`.

Skill-internal references are relative to the skill directory:

```text
skills/code-review/
  SKILL.md
  scripts/check.py
  references/checklist.md
```

From `SKILL.md`, references like `scripts/check.py` and
`references/checklist.md` mean files inside `skills/code-review/`.

Skills must not require `.mdc` authors to reference those internal files
directly.

## Skill File Access

Progressive disclosure requires agents to read skill files after seeing the
skill catalog.

Reading skill files is not the same permission as reading the target workspace.
An agent with skills enabled should be allowed to read files inside its
effective skill source roots:

```text
<source-root>/<skill-id>/SKILL.md
<source-root>/<skill-id>/scripts/...
<source-root>/<skill-id>/references/...
```

That access must not grant reads outside skill roots. Workspace reads remain
controlled by the `scoped_read_tools` toolset.

Implementation options:

- expose a dedicated skill-file read tool; or
- keep Deep Agents' `read_file` visible when skills are enabled, but enforce
  permissions that allow skill-root reads and deny workspace reads unless the
  agent has `scoped_read_tools`.

Because Deep Agents' default skills prompt tells agents to use `read_file`, the
second option is the most compatible short-term path.

## `team.yaml` Shape

Teams may declare additional team-specific skill source roots:

```yaml
skill_sources:
  - ./skills
```

Relative `skill_sources` entries resolve from the directory containing
`team.yaml`.

The runtime also includes the standard user and project sources unless a future
configuration explicitly disables them.

The runtime should also include `<team-dir>/skills` when that directory exists.
Absence of this implicit team source is not a diagnostic. Missing explicitly
configured `skill_sources` entries should produce a diagnostic.

This gives teams a zero-config local convention:

```text
teams/software/team.yaml
teams/software/skills/code-review/SKILL.md
```

If `teams/software/skills` exists, it is included automatically. A team only
needs `skill_sources` for additional or non-standard locations.

Recommended effective order:

```text
built-in skills
$CODEX_HOME/skills
<cli-cwd>/.agents/skills
<cli-cwd>/.coding-agents/skills restricted by package lockfile
<team-dir>/skills
team.yaml skill_sources, in declaration order
```

Later entries have higher priority.

After resolving paths, duplicate source roots should be collapsed by normalized
absolute path. The highest-priority occurrence wins.

For example, these two entries point to the same directory:

```yaml
skill_sources:
  - ./skills
  - /repo/teams/software/skills
```

The runtime should keep only the higher-priority occurrence so the same skills
are not scanned and listed twice.

Source labels should be explicit when passing source roots to Deep Agents. This
is mostly for prompt clarity. Without labels, several paths end in `skills`,
which can produce ambiguous prompt sections such as `Skills Skills`.

Useful labels are `User`, `Project`, `Team`, and any configured source name.

## Agent `.mdc` Shape

Agents use a compact skill policy in frontmatter.

Default behavior:

```yaml
skills: inherit
```

`inherit` means the agent receives the team runtime's effective skill source
roots.

Disable skills:

```yaml
skills: none
```

Restrict visible skills:

```yaml
skills:
  only:
    - openai-docs
    - langchain-rag
```

`only` filters the discovered catalog by skill id after source precedence is
applied.

For example, if the effective sources contain these skills:

```text
$CODEX_HOME/skills/openai-docs/SKILL.md
<cli-cwd>/.agents/skills/langchain-rag/SKILL.md
<team-dir>/skills/code-review/SKILL.md
```

then this agent sees only `openai-docs` and `langchain-rag`:

```yaml
skills:
  only:
    - openai-docs
    - langchain-rag
```

The `.mdc` file should not reference local skill directories such as
`../skills/langchain-rag`. Directory layout belongs to source configuration,
not agent prompts.

## Selection Semantics

Supported agent skill policies:

| Policy | Behavior |
| --- | --- |
| omitted or `inherit` | Use the effective source roots for the team. |
| `none` | Disable skills for this agent. |
| `only` | Expose only the listed skill ids after source precedence is applied. |

Filtering must not be implemented by passing individual skill directories as
Deep Agents source roots. A path like `<source-root>/<skill-id>` is a skill
directory, not a source root, and Deep Agents will scan its child directories
rather than load that skill.

The distinction:

```text
Correct source root:
  .agents/skills
    langchain-rag/
      SKILL.md

Wrong source root for selecting one skill:
  .agents/skills/langchain-rag
    SKILL.md
```

Deep Agents expects the first shape. If it receives
`.agents/skills/langchain-rag`, it looks for child directories under
`langchain-rag/`, such as `.agents/skills/langchain-rag/some-child/SKILL.md`.
It does not treat `langchain-rag/SKILL.md` itself as the selected skill.

Viable implementations for `only` are:

- a local skills middleware that supports a skill-id allowlist while preserving
  Deep Agents' source-root behavior; or
- a generated backend overlay source that exposes only selected skill
  directories as children.

This runtime uses generated backend overlay sources so Deep Agents can keep its
native skills middleware and source-root scanning behavior.

## Skill Ids

Skill ids are directory names under a source root.

```text
.agents/skills/langchain-rag/SKILL.md
```

The skill id is `langchain-rag`.

`SKILL.md` frontmatter should use the same name:

```yaml
---
name: langchain-rag
description: Build retrieval-augmented generation systems with LangChain.
---
```

Skill ids should follow the Agent Skills specification:

- lowercase alphanumeric characters and hyphens;
- no leading or trailing hyphen;
- no consecutive hyphens;
- maximum length of 64 characters.

## Validation

The loader should validate configuration at the source boundary:

- `skill_sources` must be a list of strings when present.
- Relative team source paths must stay inside the team directory unless an
  explicit absolute path is used.
- `skills: inherit` and omitted `skills` are equivalent.
- `skills: none` disables skills for that agent.
- `skills.only` must be a list of strings.
- Each `skills.only` entry must match a skill id available in at least one
  existing effective source root.

Missing source roots should not fail loading by default. They should produce a
diagnostic because empty user or project skill directories are common during
setup.

Malformed skill directories are handled by the Deep Agents skills middleware
when it scans `SKILL.md` files.

## Implementation Notes

The runtime mounts host skill source roots into the agent backend as virtual
paths.

Unfiltered sources use stable virtual roots:

```text
/skills/user
/skills/project
/skills/team
```

Filtered `skills.only` sources use agent-scoped virtual roots so each agent can
have a different visible catalog:

```text
/skills/<agent-id>/project
```

These virtual paths are what Deep Agents sees as source roots. The host paths
remain hidden behind backend routes.

Skill-root read access is implemented as filesystem permission rules for the
resolved virtual skill paths. When an agent has skills enabled but does not have
`scoped_read_tools`, `read_file` remains visible and is limited to skill-root
paths. General workspace reads are still denied.

Legacy list syntax is implemented as `only` during migration:

```yaml
skills:
  - langchain-rag
```

is treated like:

```yaml
skills:
  only:
    - langchain-rag
```

The runtime still passes source roots to Deep Agents, not individual skill
directories.

## Migration

Recommended authoring style:

```yaml
skills:
  only:
    - legacy-id
```

Legacy list syntax remains accepted for now:

```yaml
skills:
  - legacy-id
```

A later schema version may reject legacy lists and require the explicit `only`
mapping.

## Non-Goals

This specification does not define:

- installing skills from remote registries;
- version locking or dependency resolution for skills;
- running arbitrary skill setup hooks;
- granting tools from `allowed-tools` metadata;
- changing workspace filesystem permissions for agents.

Tool visibility and permissions remain controlled by `toolsets` and the
existing Deep Agents permission layer. Skill-root reads are a separate access
surface needed for progressive disclosure.
