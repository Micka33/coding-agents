# Team Working Directory Scope

## Decision

Teams declare their runtime scope with a top-level `working_directory` key. The
key is optional and defaults to `"."`. Relative values resolve from the CWD
where the CLI was launched, captured when the team is loaded. Absolute values
are allowed. `working_directory` is not resolved relative to `team.yaml`.

Agents declare their own runtime scope with `relative_working_directory`. The
key is optional and defaults to `"."`.

Agent working directories are always resolved relative to the resolved team
`working_directory`.

For example, if the CLI is launched from `/repo`:

- `working_directory: "."` resolves to `/repo`.
- `working_directory: "apps/api"` resolves to `/repo/apps/api`.
- An agent with `relative_working_directory: "src"` inside that team resolves
  to `/repo/apps/api/src`.
- A relative SQLite path such as `.coding-agents/checkpoints.sqlite` resolves to
  `/repo/.coding-agents/checkpoints.sqlite`, not under `/repo/apps/api`.
- Project skills resolve from `/repo/.agents/skills`, not from the team
  `working_directory`.

## Rationale

The team scope is a workspace concern, not a shared storage default. A top-level
key makes that scope visible at the same level as team identity.

Agent scopes should be explicit because each agent may be responsible for a
different part of a workspace. The `relative_working_directory` name makes the
containment rule clear: agents can narrow their scope within the team directory,
but cannot escape it.

Prompt configuration remains separate from runtime scope. Agent `config` paths
continue to resolve relative to the `team.yaml` file, while
`relative_working_directory` resolves relative to the team working directory.

## Enforcement

The loader validates these invariants:

- `working_directory` is non-empty and points to an existing directory.
- `relative_working_directory` is non-empty, relative, and points to an existing
  directory.
- Each resolved agent working directory must stay inside the resolved team
  working directory.
- Directory-related template variables expose `{working_directory}`.

The runtime applies the resolved scopes this way:

- SQLite checkpointer storage is not scoped by the team working directory. There
  must be one SQLite database for the CLI process, and relative SQLite paths
  resolve from the CWD where the CLI was launched. Absolute SQLite paths remain
  absolute.
- Project skills are not scoped by the team working directory. They resolve
  under `.agents/skills` in the CWD where the CLI was launched.
- Agent filesystem tools, shell execution, custom tool context, scoped read
  tools, and memory file checks resolve under the agent working directory.
- Custom scoped-read tool arguments may narrow the agent scope further with a
  relative path, but cannot escape the agent working directory.
