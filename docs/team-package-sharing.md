# Team Package Sharing

Status: design draft

Scope: team package authoring, installation, skill dependencies, versioning,
lockfiles, trust, and Studio team discovery

## Summary

Users should be able to create reusable agent-team packages and share them
with other users. A package is a portable bundle around one or more
`team.yaml` files, agent `.mdc` files, optional vendored skills, and optional
runtime integrations.

`coding-agents` should borrow the simple install UX of npm-based tools, but
not make npm the only package substrate. The runtime is Python, the Studio
frontend is JavaScript, and teams are mostly data-first configuration. Team
packages should therefore be registry-agnostic and installable from local
paths and Git first, with npm and PyPI as later transport adapters over the
same package model.

The design extends existing machinery instead of adding parallel systems.
Team loading, validation, skill source layering, and Studio discovery already
exist; packages add a package manifest, an installer, a lockfile, and a trust
gate on top of them.

## Assumptions

- "Teams" means reusable agent-team definitions, not human organization or
  workspace membership.
- `team.yaml` remains the runtime entrypoint for a team.
- `team.yaml` `schema_version` describes the config format, not the package
  release version. The validator currently accepts only `schema_version: 1`.
- Team packages may contain executable surfaces through Python custom tools,
  local stdio MCP servers, or shell-enabled teams. Installing a package must
  not silently treat these as trusted configuration.
- Some teams depend on skills that are not included directly in the package.
- Project and user skill layers are managed by the user, often with the
  external `skills` CLI (vercel-labs/skills), which installs into
  `.agents/skills/` and writes its own `skills-lock.json`.

## Goals

- Let users author a team package from local `team.yaml` and `.mdc` files.
- Let users install shared team packages from local paths and Git.
- Keep the package format independent of the distribution registry.
- Make package installs reproducible through resolved versions, hashes, and a
  lockfile owned by `coding-agents`.
- Support team-local vendored skills, package skill dependencies, and
  externally managed skills.
- Avoid silently copying private user skills from `$CODEX_HOME/skills` into
  shared packages.
- Require an explicit, user-local trust decision before executable package
  surfaces run.
- Add installed package teams to the existing Studio discovery model.

## Non-Goals

- Replacing `team.yaml`.
- Making npm the canonical package registry.
- Automatically publishing packages to any public registry.
- Running arbitrary install scripts by default.
- Storing secrets, environment values, or API keys in package manifests or
  lockfiles.
- Solving hosted human collaboration, permissions, or organization
  membership.
- Replacing or wrapping the external `skills` CLI for project and user skill
  management. `skills-lock.json` belongs to that tool; `coding-agents` never
  writes it.
- User-global package installs. The first release is workspace-scoped.

## Existing Building Blocks

The package system builds on code that already exists:

| Package concern | Existing code |
| --- | --- |
| Team loading and validation | `src/team_loader` (`TeamLoader`, `TeamValidator`) |
| Restricted YAML parsing | `src/team_loader/parsing/yaml_parser.py` |
| Skill source layering | `src/team_instanciator/resolvers/skill_source_resolver.py` |
| Scoped skill sources | `ResolvedSkillSource` with `allowed_skill_ids` |
| Studio team discovery | `src/webapp_studio/backend/api/team_discovery_service.py` |

Naming: this document always says "package manifest" for
`coding-agents-package.yaml`. The existing `TeamRuntimeManifest` is runtime
lane metadata persisted with checkpoints and is unrelated to packages.

## Package Shape

A package is a directory or Git repository that contains a
`coding-agents-package.yaml` package manifest. Later transports (npm, PyPI)
unpack to the same shape.

Example:

```text
my-team-package/
  coding-agents-package.yaml
  teams/
    software/
      team.yaml
      agents/
        engineering-manager.mdc
        developer.mdc
      skills/
        code-review/
          SKILL.md
```

The package manifest owns package-level metadata and exported teams:

```yaml
schema_version: 1
name: acme/software-team
version: 1.4.2
description: Software delivery team for product engineering repositories.

compatibility:
  coding_agents: ">=0.3.0,<0.5.0"

exports:
  teams:
    - id: software
      path: teams/software/team.yaml

skills:
  dependencies:
    - id: langchain-rag
      source: git:https://github.com/acme/agent-skills.git
      ref: v2.0.0
  external:
    - id: company-private-docs
      install_hint: npx skills add acme/agent-skills

requires:
  env:
    - COMPANY_DOCS_MCP_TOKEN
```

Package manifest rules:

- The package manifest is parsed with the same restricted YAML subset as
  `team.yaml` (`YamlParser`). Keep it in simple block-style YAML.
- `name` uses lowercase letters, digits, and hyphens, with one optional
  `owner/` prefix. Mappings to npm and PyPI names are defined with those
  transports.
- `compatibility.coding_agents` is a PEP 440 specifier set evaluated with the
  `packaging` library, not an npm-style range.
- Each `exports.teams[].id` must equal the `id` declared inside the
  referenced `team.yaml`. Validation fails on mismatch.
- Bundled skills are not declared in the package manifest. A skill is bundled
  when it exists under `<team-dir>/skills/`; the validator derives the
  bundled set from disk, so the manifest cannot drift from the package
  contents.
- `requires.env` lists environment variable names the exported teams need at
  runtime, such as MCP auth tokens. Names only, never values. Missing values
  never block validation, install, or instantiation: they only produce
  warnings, in the CLI console and in the Studio UI. Runtime components that
  genuinely need a value, such as MCP auth, still fail on their own when it
  is absent.

## Authoring Commands

First-release authoring surface:

```bash
coding-agents team validate ./my-team-package
```

`team validate` validates the package manifest, each exported `team.yaml` and
its referenced `.mdc` files, compatibility metadata, and skill resolvability.
Every skill selected by an agent must be:

- bundled on disk under the exporting team's `skills/` directory, or
- declared in `skills.dependencies`, or
- declared in `skills.external`.

Missing external skills produce a diagnostic that names the skill and prints
the declared `install_hint`.

`team init` (scaffolding), `team pack` (archives), and `team vendor-skills`
are deferred. Local and Git installs operate on directories and repositories
directly, so archives only matter for the npm and PyPI transports.

### Vendoring Skills (Deferred)

Authors may want a self-contained package:

```bash
coding-agents team vendor-skills ./teams/software/team.yaml
coding-agents team vendor-skills ./teams/software/team.yaml --from project
coding-agents team vendor-skills ./teams/software/team.yaml --from user --include company-private-docs
```

The command copies only skills referenced by agents or declared in the
package manifest. It must not blindly copy every visible user skill, must
preview what will be copied, and must not copy from `$CODEX_HOME/skills`
unless the author explicitly opts in.

When vendoring from the project layer, the command may read the external
`skills-lock.json` (read-only) to record the skill's original source and hash
as provenance instead of an unknown local copy.

## Installing Packages

First-release install surface:

```bash
coding-agents team install ./local-package
coding-agents team install git:https://github.com/acme/software-team@v1.4.2
coding-agents team list
coding-agents team update
coding-agents team update acme/software-team
coding-agents team uninstall acme/software-team
```

npm and PyPI arrive later as transport adapters over the same package shape:

```bash
coding-agents team install npm:@acme/coding-agents-software-team@1.4.2
coding-agents team install pypi:acme-coding-agents-software-team==1.4.2
```

Installed packages are not copied into project or user skill folders. The
installer never writes inside an installed package directory after unpacking,
so package integrity hashes stay verifiable. Skill dependencies live next to
packages, not inside them:

```text
.coding-agents/
  packages/
    acme/
      software-team/
        coding-agents-package.yaml
        teams/software/team.yaml
  skills/
    langchain-rag/
      SKILL.md
  team-lock.json
```

Install semantics:

- Installing is idempotent. Reinstalling the same resolved identity verifies
  hashes and rewrites the same lockfile entry.
- Installing a different version replaces the package directory and its
  lockfile entry.
- `team update` re-resolves the requested source for one named package or for
  every locked package, reinstalls when the resolved identity changed, and
  rewrites the affected lockfile entries and skill dependencies. A changed
  integrity hash invalidates prior trust, as described below.
- `team uninstall` removes the package directory, its lockfile entry, and any
  installed skill dependency no remaining locked package uses.
- `team list` prints locked packages, exported teams, risk flags, and trust
  status.

## Skill Dependency Model

Teams can use skills from several places:

- skills bundled in `<team-dir>/skills/` inside the package;
- skills declared as package dependencies and installed next to the package;
- project skills in `<cli-cwd>/.agents/skills`;
- user skills in `$CODEX_HOME/skills`.

The package manifest declares only what cannot be derived from disk:

```yaml
skills:
  dependencies:
    - id: langchain-rag
      source: git:https://github.com/acme/agent-skills.git
      ref: v2.0.0
  external:
    - id: company-private-docs
      install_hint: npx skills add acme/agent-skills
```

`dependencies` means the installer fetches the skill into
`.coding-agents/skills/<id>/` and pins it in the lockfile.

The skill store is shared across packages and keyed by skill id. Packages
that pin the same id at the same resolved commit share one copy. If an
install would pin an id that another installed package has locked at a
different commit, the installer fails before touching the workspace and
names the conflicting package; uninstalling a package keeps skills that
other packages still lock.

`external` means the skill is intentionally not bundled or fetched. The
installer and validator verify that the skill resolves from the project or
user layers, or emit a diagnostic naming the missing skill and its
`install_hint`. Entries are skill ids, optionally with an `install_hint`.
External skills carry no version constraints in the first release.

This split is also the boundary with the external `skills` CLI: `external`
skills are the ones users manage themselves, typically with `npx skills add`,
in the layers that tool already targets.

### Resolution Layer

Installed skill dependencies join the existing source layering through one
new package layer in `SkillSourceResolver`. Layers from lowest to highest
priority:

1. `$CODEX_HOME/skills` (user)
2. `<cli-cwd>/.agents/skills` (project)
3. `.coding-agents/skills`, restricted to the dependency ids locked for the
   loaded package (package layer)
4. `<team-dir>/skills` (team)
5. configured `skill_sources`, in declaration order

The package layer applies only when the loaded team belongs to an installed
package. It reuses `ResolvedSkillSource` with `allowed_skill_ids`, so one
shared store serves every package without leaking skills across packages.

The package layer sits above the project layer on purpose: a locked
dependency must not be silently shadowed by an unrelated project skill with
the same id. The team layer stays highest because bundled skills are the
author's most specific choice.

Skills are never copied into each exported team's `skills/` directory.

## Versioning

Team packages are versioned at the package level with semantic versions.

`team.yaml` keeps its existing `schema_version` field for config-format
compatibility. It does not carry the package release version.

Version authority depends on the distribution source:

- Git: the requested tag or commit is authoritative for reproducibility, and
  the package manifest version is metadata. Installing tag `v1.4.2` with a
  manifest version of `1.4.1` warns loudly and records both in the lockfile.
- Local path: the manifest version is metadata, and reproducibility comes
  from a content hash in the lockfile.
- npm and PyPI (later): the registry package version is authoritative, and a
  manifest mismatch fails the install.

Packages that export multiple teams have one package version. A future
manifest version can add optional team-level versions if a real need appears;
the first design avoids that extra axis.

## Lockfile

`coding-agents` owns `.coding-agents/team-lock.json`. It records the exact
installed package graph: the installer's resolved snapshot, not the author's
declaration.

It is unrelated to the repository-root `skills-lock.json`, which belongs to
the external `skills` CLI and tracks project and user skills. The two files
have different owners and never share entries.

Example:

```json
{
  "schema_version": 1,
  "generated_by": "coding-agents 0.3.0",
  "packages": [
    {
      "name": "acme/software-team",
      "version": "1.4.2",
      "source": "git:https://github.com/acme/software-team",
      "requested": "v1.4.2",
      "resolved": "7f3c9a6d4e...",
      "integrity": "sha256-...",
      "installed_path": ".coding-agents/packages/acme/software-team",
      "teams": [
        {
          "id": "software",
          "path": "teams/software/team.yaml"
        }
      ],
      "risk_flags": ["stdio_mcp", "shell"],
      "dependencies": {
        "skills": [
          {
            "id": "langchain-rag",
            "source": "git:https://github.com/acme/agent-skills",
            "requested": "v2.0.0",
            "resolved": "91aa12...",
            "integrity": "sha256-...",
            "installed_path": ".coding-agents/skills/langchain-rag"
          }
        ]
      }
    }
  ]
}
```

Risk flags are derived by scanning each exported team definition, never
declared by the author:

- `custom_tools`: the team declares `custom_tools` factories.
- `stdio_mcp`: an `mcp_servers` entry uses `transport: stdio`.
- `remote_mcp`: an `mcp_servers` entry uses an HTTP-style transport.
- `shell`: a toolset exposes `execute` and `defaults.execution_backend` can
  resolve to `local`.

The lockfile should contain:

- package name and version;
- source requested by the user;
- resolved immutable identity, such as a Git commit or, later, an npm tarball
  integrity or PyPI file hash;
- exported team ids and paths;
- installed skill dependencies with their own resolved refs and hashes;
- compatibility metadata needed for validation;
- derived risk flags;
- install paths, project-relative.

The lockfile must not contain:

- API keys;
- environment values;
- user-specific absolute home paths;
- generated conversation state;
- runtime checkpoints;
- mutable branch names as the only resolved identity;
- trust decisions.

## Trust And Security

Package installation does not run package lifecycle scripts.

Resolving and locking a package never implies trust. Trust is a separate,
user-local decision:

- Trust decisions live in a user-local trust store, for example
  `$CODEX_HOME/coding-agents/trust.json`, keyed by package name and integrity
  hash.
- Trust is never written to `team-lock.json`. The lockfile is committed and
  shared; one user's trust decision must not enable executable surfaces for
  everyone who pulls the repository.
- A changed package content hash invalidates prior trust.

The installer surfaces derived risk flags before any trust prompt:

- `custom_tools`: imports Python modules from the package or environment.
- `stdio_mcp`: runs a local command as an MCP server.
- `shell`: gives one or more agents access to local shell execution.
- `remote_mcp`: sends data to a remote MCP server.

### Runtime Enforcement

Install-time prompts alone are not enough. Instantiation imports custom tool
factories and starts MCP servers immediately, so an untrusted package team
must be stopped before instantiation, not after.

When a team file resolves to a path inside `.coding-agents/packages/`, the
runtime checks the trust store first:

- trusted: the team instantiates normally;
- untrusted with risk flags: instantiation fails with a diagnostic listing
  the flags and the command that grants trust;
- no risk flags: no trust decision is required.

Studio and the CLI share this gate. Teams outside installed packages keep
today's behavior: local configuration is trusted by ownership.

## Runtime Behavior Of Installed Teams

An installed package team loads through the standard `team.yaml` path; no
parallel loading pipeline exists. Existing semantics apply unchanged:

- `working_directory: "."` resolves from the launch current working
  directory, so an installed software team operates on the user's project.
  That is the intended behavior.
- Relative checkpointer paths resolve from the launch current working
  directory, outside the installed package.
- `<team-dir>/skills` resolves inside the installed package and keeps working
  for bundled skills.

The only package-specific runtime additions are the package skill layer and
the trust gate described above.

## Studio Discovery

Studio discovers installed package teams in addition to existing project and
built-in teams.

Sources:

1. project-local teams (existing):

   ```text
   <launcher-cwd>/.coding-agents/teams/<team-name>/team.yaml
   ```

2. installed package teams, read from `team-lock.json` exports;

3. built-in repository teams (existing):

   ```text
   <coding-agents-root>/teams/<team-name>/team.yaml
   ```

Package discovery is lockfile-driven, not glob-driven. Discovery must not
scan `.coding-agents/packages/` for `team.yaml` files: only exported teams
are discoverable, so packages can contain internal fixtures or examples
without leaking them into Studio. `TeamDiscoveryService` gains one package
source backed by the lockfile.

Descriptors for installed package teams extend the existing descriptor fields
(team id, description, team file, source, conversation availability,
participants) with:

- package name, version, and source;
- lock status: `locked`, or `missing` when the installed path is gone;
- trust status;
- missing `requires.env` names, surfaced as warnings in the UI.

Duplicate team ids block only the colliding teams. Discovery excludes every
team involved in a collision, reports each collision with all declaring
files, and keeps the remaining teams available. No colliding team wins by
priority, so package teams never silently override project or built-in
teams. This replaces the current behavior, documented in
`docs/webapp-studio-team-discovery.md`, where one duplicate id blocks all
discovery; that behavior does not scale once installed packages make
collisions more likely. Studio surfaces the collision diagnostics in the UI.

## CLI Integration

The current CLI takes `team_file` as a positional argument with one `webapp`
early dispatch. `coding-agents team install ...` would parse `team` as a team
file today, so the package commands require restructuring the CLI into
argparse subcommands first:

- `coding-agents run <team_file> [...]`: today's behavior. The bare
  `coding-agents <team_file>` form stays supported for backward
  compatibility.
- `coding-agents webapp [...]`: existing dispatch, unchanged.
- `coding-agents team <subcommand> [...]`: the commands in this document.

The restructuring also replaces the outdated CLI section in `README.md`.

## MVP Implementation Slices

1. Restructure the CLI into subcommands (`run` default, `webapp`, `team`) and
   update `README.md`.
2. Define and document `coding-agents-package.yaml`, parsed with the existing
   `YamlParser` and validated with `packaging` specifiers.
3. Add `team validate` for local package directories.
4. Add `team install` for local paths and Git, writing
   `.coding-agents/team-lock.json`, plus `team list`, `team update`, and
   `team uninstall`.
5. Install package skill dependencies from Git into `.coding-agents/skills/`
   and add the package layer to `SkillSourceResolver`.
6. Add the user-local trust store and the instantiation gate.
7. Add lockfile-driven package teams to `TeamDiscoveryService`, extend the
   Studio descriptor, and change duplicate handling to block only the
   colliding teams.
8. Later: `team init`, `team vendor-skills`, `team pack`, and the npm and
   PyPI transport adapters.

## Resolved Questions

- Skill dependencies are stored outside installed packages and joined through
  a resolver layer. Copying them into each exported team would break package
  integrity verification and duplicate files.
- Trust decisions live in a user-local trust store, never in the committed
  lockfile.
- External skills are ids with an optional `install_hint`; no version
  constraints in the first release.
- Bundled skills are derived from disk. The validator requires every
  agent-selected skill to be bundled on disk, a declared dependency, or a
  declared external skill.
- User-global installs are out of the first release, so the lockfile shape
  stays project-scoped for now.
- Duplicate team ids block only the colliding teams instead of blocking all
  discovery. No colliding team wins by priority, nothing is silently
  overridden, and unrelated teams stay usable. Team ids are not qualified or
  namespaced, because the team id doubles as the default root thread id for
  checkpoints.
- Missing `requires.env` values never block validation, install, or
  instantiation. They produce warnings in the CLI console and in the Studio
  UI.
- `team update` ships in the first release alongside `team install`,
  `team list`, and `team uninstall`.

## Open Questions

None currently. Earlier open questions are resolved above.
