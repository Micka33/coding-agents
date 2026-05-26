# Decision Log

Status: approved decisions with implementation follow-ups locally completed; release readiness not claimed

## Status Legend

- `approved`: decision is accepted as current project direction.
- `proposed`: decision is recommended but still needs explicit approval or
  ratification.
- `implemented`: observed in code.
- `statically inspected`: observed through scout or file inspection; runtime test execution has not been recorded.
- `tested`: passing command output or equivalent execution evidence has been recorded.
- `partial`: partially observed in code or documentation.
- `missing`: not observed in code.
- `approved for implementation entry`: accepted by the human decision maker as the current basis for bounded, task-scoped implementation work.

## Decisions

### DEC-0001: SQLite checkpointing for resident agent memory

Decision status: approved  
Implementation status: implemented

Context:

Product and architecture agents need to stay alive as collaborators. They may
ask follow-up questions, receive clarifications from the engineering manager,
and continue the same shaping discussion later. Stateless Deep Agents subagents
do not preserve that conversational continuity.

Decision:

Use SQLite-backed LangGraph checkpointing as the default V0 persistence layer
for the engineering manager and resident product and architecture agents. Keep a
Postgres checkpoint adapter installed and configurable for future shared or
production deployments. Keep an in-memory option available for tests or
disposable sessions.

Options considered:

- SQLite checkpointer.
- Postgres checkpointer.
- In-memory checkpointer.

Selected option:

- SQLite as the local V0 default, with Postgres available for shared/production
  deployments and memory available for tests.

Rejected options:

- Postgres-only persistence for V0, because it adds unnecessary local setup.
- In-memory-only persistence, because resident collaborators need continuity
  across CLI restarts.

Rationale:

SQLite satisfies the local-first V0 goal without external infrastructure while
still allowing durable resident conversations. Repository artifacts remain the
source of truth for durable decisions.

Consequences:

- Local CLI restarts can preserve resident product and architecture thread
  history.
- The default setup does not require provisioning external infrastructure.
- Postgres can be enabled by configuration when the system needs shared durable
  persistence.
- Versioned repository artifacts remain the source of truth for approved
  decisions and requirements.

### DEC-0002: Scout subagent for codebase reconnaissance

Decision status: approved  
Implementation status: implemented

Context:

The engineering manager may be asked where implementation stands. Answering from
workflow artifacts alone can be misleading when the codebase has advanced beyond
the docs or when docs are stale.

Decision:

Add a disposable `scout` subagent that performs fast codebase reconnaissance and
returns compressed context for handoff to the engineering manager or another
agent. The manager must call the scout for status, progress, readiness, or gap
analysis questions unless the human explicitly asks for docs-only analysis.

Options considered:

- Manager manually reads docs and code with generic filesystem tools.
- Add a read-only status snapshot tool.
- Add a scout subagent with codebase reconnaissance instructions.

Selected option:

- Disposable scout subagent with scoped reconnaissance tools.

Rejected options:

- Docs-only status answers, because they can be stale.
- Manual manager-only reconnaissance as the default, because it increases prompt
  bloat and reduces repeatability.

Rationale:

The scout creates a consistent codebase-fact gathering step while keeping final
interpretation and decision-making with the engineering manager.

Consequences:

- Status answers must compare documented state with actual code state.
- The manager can delegate context-gathering without bloating its own prompt.
- Scout remains disposable and does not own product or architecture decisions.
- Scout has no shell or `execute` tool in the hardened V0 implementation; reconnaissance uses safe file tools and Python literal grep.

### DEC-0003: Ratify reusable Python package plus CLI as the V0 delivery shape

Decision status: approved  
Implementation status: implemented

Context:

The codebase already exists largely as a reusable Python package under
`coding_agents/` plus a minimal interactive CLI. The previous workflow artifacts
did not explicitly record this as the delivery shape or define the V0 public API
boundary.

Decision:

Ratify the reusable Python package under `coding_agents/` plus a minimal CLI as
the V0 delivery shape.

The CLI command is the only user-facing entrypoint officially supported in V0.
The Python package exposes only a minimal first-party integration surface for the
CLI and future first-party entrypoints:

- `AgentTeamConfig`
- `create_development_team_agent`

Everything else in `coding_agents/` is internal by default unless a later
decision explicitly promotes it to public API.

V0 is for local/repository use and is not intended for external distribution. A
web UI is the expected next product step after V0 and should wrap the package
through the minimal public surface rather than importing internal modules.

Options considered:

- One-off script.
- Reusable Python package with CLI.
- Hosted service or web UI.

Selected option:

- Reusable Python package with a minimal CLI as the only V0 user-facing
  entrypoint.
- Minimal first-party Python API: `AgentTeamConfig` and
  `create_development_team_agent`.

Rejected options:

- One-off script, because it would make testing, reuse, and future integrations
  harder.
- Hosted service or web UI for V0, because it adds deployment, auth, and product
  surface area not needed before the local-first V0 is validated.
- External distribution for V0, because package/runtime/API stability has not yet
  been validated through tests, CI, and release hardening.

Rationale:

The package-plus-CLI shape matches the observed implementation, keeps local setup
lightweight, gives the CLI a stable first-party construction seam, and leaves a
clean path for the next-step web UI without turning the whole package into a
public SDK.

Consequences:

- CLI behavior is the V0 user-facing contract.
- `AgentTeamConfig` and `create_development_team_agent` are the only V0 Python
  API contracts.
- Prompts, subagent wiring, resident tools, checkpointers, permissions,
  artifact templates, Tavily wrappers, and other modules remain internal.
- Packaging metadata, runtime version support, and CLI/package smoke tests become
  release-relevant.
- Future UI or service entrypoints should wrap the package through the minimal
  public surface rather than duplicate agent wiring or import internals.

### DEC-0004: Machine-enforce readiness before implementation mode

Decision status: approved

Implementation status: implemented / statically inspected and tested

Context:

The readiness gate was documented before it was coded. The limited governance
implementation now includes a machine-readable readiness artifact and runtime
guard. Broad implementation entry was approved by the human decision maker on
2026-05-25, but runtime implementation mode remains unavailable until the YAML
gate records explicit full implementation approval. A documentation-only
convention is not sufficient for an autonomous agent workflow.

Decision:

Add machine-readable readiness state and runtime enforcement so implementation
mode cannot delegate developer work, activate implementation subagents, or grant
implementation write permissions until the readiness gate is approved.

Use a simple machine-readable readiness artifact, recommended as
`docs/agent-workflow/readiness-gate.yaml`, as the execution source for the guard.
Keep `docs/agent-workflow/readiness-gate.md` as the human-readable view.

The guard must fail closed when readiness is absent, invalid, or not approved.
The guard should block at minimum:

- implementation mode activation;
- delegation to developer, code-reviewer, QA, DevOps, security-reviewer, and
  technical-writer subagents for implementation work;
- write permissions outside `/docs/agent-workflow/`;
- destructive or sensitive operations that would bypass the gate.

This decision approves the architecture direction only. It does not by itself
start implementation mode. When implementation is explicitly authorized, the
readiness guard should be the first governance code task before broader code
work.

Options considered:

- Documentation-only readiness convention.
- Machine-readable readiness file plus runtime guard.
- Manual human approval outside the repository.

Selected option:

- Machine-readable readiness file plus runtime guard.

Rejected options:

- Documentation-only convention, because it is easy to bypass accidentally.
- External-only approval, because it does not give agents a durable source of
  truth inside the repository.

Rationale:

The readiness rule is a core governance control. It should be enforced by code,
not only by instructions. A machine-readable file gives agents and tests a durable
source of truth while the Markdown artifact remains readable for humans.

Consequences:

- The engineering manager must fail closed when readiness is not approved.
- Developer, reviewer, QA, DevOps, security, and writer subagents should only be
  activated for implementation after approval.
- The readiness artifact must be kept synchronized with the machine-readable gate
  representation.
- Tests must cover approved, unapproved, missing, and invalid readiness states.
- The guard implementation becomes the first governance implementation task once
  implementation work is explicitly approved.

Historical validation evidence from the pre-approval corrective pass on 2026-05-25:

- Scout-backed static inspection reported a fail-closed readiness guard,
  implementation subagent gating, and the then-current `readiness-gate.yaml` with
  `approved: false` before broad implementation approval was recorded.
- Automated validation passed with `uv run --project / python -m unittest discover -s tests`.
- Result: exit code 0, `Ran 64 tests in 0.297s`, `OK`.

Current implementation-entry approval is recorded separately in DEC-0008 and in
`docs/agent-workflow/readiness-gate.yaml`.

### DEC-0005: Tighten implementation-mode write protections

Decision status: approved

Implementation status: implemented / statically inspected and tested

Context:

Mode-aware permissions are present. The governance implementation now uses
repo-wide implementation writes by default after machine-readable readiness
approval, while protecting the machine-readable readiness gate and secret-like
paths. Literal `--write-path` restrictions remain available for narrower runs,
and local unittest validation passed on 2026-05-25.

Decision:

Allow repo-wide implementation writes by default after the readiness gate records
full approval. Each developer task brief must still identify files or modules in
scope, files or modules out of scope, constraints, and acceptance criteria before
work is delegated. `--write-path` can restrict a run to exact files or literal
existing directories when a narrower execution profile is useful. Glob patterns
are not accepted for explicit write restrictions because they are harder to
reason about safely.

Implementation subagents may request access to additional files or modules, but
must do so through the engineering manager with a concise justification, the
specific files or paths requested, the reason the current scope is insufficient,
the risk of not granting access, and any safer alternative. The engineering
manager may consult the software architect and product analyst before approving
the expansion, rejecting it, suggesting an alternate solution, splitting the task,
or escalating to the human.

Cross-cutting work should still be split into smaller scoped tasks by default.

Options considered:

- Repo-wide implementation-mode write access after readiness approval.
- Role-scoped write profiles.
- Optional task-scoped write restrictions.

Selected option:

- Repo-wide implementation writes by default after machine-readable readiness
  approval, with protected denies for `readiness-gate.yaml` and secret-like
  paths.
- Optional `--write-path` restrictions, with exact files preferred and literal
  existing directories allowed; glob patterns are disallowed.
- Manager-mediated scope expansion requests, with product/architecture
  consultation when the request may change scope, boundaries, or tradeoffs.
- Cross-cutting tasks split by default unless a broad scope is explicitly
  approved.

Rejected options:

- No implementation writes without explicit `--write-path`, because it prevents
  the approved manager from autonomously executing the implementation backlog.
- Role-only scoping, because two tasks owned by the same role may still require
  different boundaries.

Rationale:

The readiness gate is the human trust boundary. After it records full approval,
the manager should be able to execute the implementation backlog autonomously.
Task scoping is still enforced through briefs, review, tests, and optional
`--write-path` restrictions rather than requiring the human to enumerate paths at
CLI startup.

Consequences:

- Task briefs remain required planning and review inputs.
- The engineering manager must validate scope before delegation.
- Subagents can request additional access, but cannot grant it to themselves.
- Scope expansion decisions must be documented when they change product,
  architecture, planning, or delivery context.
- Tests and docs may be updated as needed for the assigned task, while protected
  readiness/secret paths remain denied.
- Permission enforcement supports repo-wide default writes, optional exact-file
  and literal existing-directory restrictions, and denied protected paths.

Initial validation evidence from the corrective security pass on 2026-05-25:

- Scout-backed static inspection reports repo-wide implementation writes after
  gate approval, optional literal write restrictions, safe path checks, and
  protected readiness/secret path handling.
- Automated validation passed with `uv run --project / python -m unittest discover -s tests`.
- Result: exit code 0, `Ran 64 tests in 0.297s`, `OK`.

SEC-001 follow-up validation as of 2026-05-25:

- Secret-like path protection now includes common credential filenames such as `.netrc`, `.npmrc`, `.pypirc`, `credentials.json`, `secrets.json`, and `application_default_credentials.json` in permissions, safe filesystem access, and scout reconnaissance.
- Local shell output and defensive shell exception messages are best-effort redacted before being returned to agents.
- Local validation passed across Python 3.11 through 3.14 with `Ran 82 tests`, `OK`.

Scope clarification for the limited DEC-0004/DEC-0005 corrective pass:

The following security and correctness fixes are in scope for the limited
DEC-0004/DEC-0005 implementation authorization because they close bypasses of the
readiness gate, artifact integrity, or write protections:

- Remove `scout.execute` from scout tool registration rather than trying to validate arbitrary shell commands in this pass.
- Normalize and compare protected paths using case-insensitive deny checks for
  reserved targets such as `readiness-gate.yaml`, `.env`, and private key files.
- Reject symlink components for artifact directories, workflow artifact files,
  runtime filesystem-tool aliases, and explicit write-restriction paths, then verify containment
  after resolving the final path where applicable.
- Validate `artifacts_dir` by resolved containment, not only by string prefix, and
  fail closed on symlink relocation.
- Add a small internal redaction helper for startup/runtime exception messages so
  DSNs, API keys, and similar secrets are not printed raw.

These fixes do not approve broader implementation mode, new dependencies, runtime
metadata changes, or expanded scout command capabilities. Reintroducing scout
shell execution through new parameterized wrappers or broad command validation is
a separate DEC-0002/scout design decision unless explicitly limited to preserving
DEC-0004/DEC-0005 enforcement.

### DEC-0006: Ratify Python runtime support range

Decision status: approved  
Implementation status: implemented / metadata aligned and locally tested

Context:

A Python `>=3.14` runtime requirement was observed as a potential adoption risk.
Python version support affects contributor setup, CI availability, dependency
compatibility, package usability, and the future web UI. V0 is local/repository
use only and is not intended for external distribution, but runtime support still
matters for contributors and release-readiness claims.

The compatibility review found:

- Scout-backed code inspection found no Python 3.14-specific syntax or API usage.
- The code uses Python 3.10+ syntax such as `X | Y` unions and built-in generics,
  but not `match`, `except*`, `tomllib`, `typing.Self`, or `typing.override`.
- Verified dependency metadata makes `deepagents 0.6.3` the limiting dependency at
  Python `<4.0,>=3.11`; other current dependencies support Python 3.10 or lower
  floors except where they also cap at `<4.0`.
- Initial local validation was on Python 3.14.5; final local validation now covers Python 3.11, 3.12, 3.13, and 3.14.

Decision:

Ratify V0 supported Python runtime as `>=3.11,<4.0`.

Align `pyproject.toml`, `.python-version`, `uv.lock`, CI, and documentation to
this supported range. Use Python 3.11 as the default local floor-development
version in `.python-version`; validate the full supported range through CI.

Options considered:

- Keep Python `>=3.14`.
- Support Python `>=3.10,<4.0`.
- Support Python `>=3.11,<4.0`.
- Support a narrower floor such as Python `>=3.12,<4.0`.

Selected option:

- Python `>=3.11,<4.0`.

Rejected options:

- Keep Python `>=3.14`, because no observed code or dependency requirement
  justifies the restriction and it unnecessarily narrows contributor and CI
  environments.
- Support Python `>=3.10,<4.0`, because `deepagents 0.6.3` requires Python
  `>=3.11`.
- Support Python `>=3.12,<4.0`, because it excludes Python 3.11 without a
  technical requirement.
- Use an unbounded `>=3.11` range, because current core dependencies already cap
  support below Python 4 and the project has not designed or validated Python 4
  compatibility.

Rationale:

Python 3.11 is the actual dependency-constrained floor. Python 3.14 remains in
the supported range, but it is not required by the code or dependencies. The
`>=3.11,<4.0` range improves local contributor compatibility and gives CI a clear
validation contract while matching the current Deep Agents dependency boundary.
The `<4.0` upper bound is explicit because core dependencies already require it
and Python 4 compatibility is outside the V0 design.

Consequences:

- `pyproject.toml` should use `requires-python = ">=3.11,<4.0"`.
- `.python-version` should use `3.11` so the default local development runtime
  exercises the supported floor rather than the newest tested version.
- `uv.lock` must be regenerated after metadata changes and committed with the CI
  update.
- CI must test Python 3.11, 3.12, 3.13, and 3.14 before release-ready claims.
- Documentation must state V0 support as Python 3.11 through Python 3.14 while
  preserving the existing non-goal of external distribution.
- Future use of Python 3.12+, 3.13+, or 3.14+ syntax or APIs requires either
  compatibility guards or a new decision to raise the floor.
- The future web UI should use the same package runtime decision unless a later
  architecture decision splits runtimes deliberately.

Validation evidence as of 2026-05-25:

- `pyproject.toml` uses `requires-python = ">=3.11,<4.0"` and Python 3.11-3.14 classifiers.
- `.python-version` uses `3.11`.
- `uv.lock` resolves under `requires-python = ">=3.11, <4.0"` and `uv lock --check` passed.
- `.github/workflows/ci.yml` validates Python 3.11, 3.12, 3.13, and 3.14.
- Local validation passed on Python 3.11, 3.12, 3.13, and 3.14 with `uv run --python <version> python -m unittest discover -s tests`; each run exited 0 with `Ran 82 tests`, `OK`.
- Clean Python 3.11 wheel install, package import, and `coding-agents --init-only` smoke passed locally.

Hosted CI results should still be recorded as external release evidence before release-ready claims.

### DEC-0007: Default local command execution profiles

Decision status: approved

Implementation status: implemented / statically inspected and tested

Context:

Implementation specialists need to run real development commands: tests,
linters, build commands, database CLIs, and diagnostics. The previous hardened
V0 removed scout shell execution and left the main manager graph on a filesystem
backend without command execution, so agents could add tests but could not run
them.

Decision:

Add an explicit command execution profile. Shaping and implementation runs
default to `local`, which exposes Deep Agents' `execute` tool to the
engineering-manager graph. In implementation mode it also exposes `execute` to
implementation specialists. The human can pass `--execution none` to disable
command execution for a run.

Selected option:

- Default shaping and implementation modes to `execution_backend="local"`.
- Keep scout and resident product/architecture agents without general shell
  execution.
- Preserve safe filesystem handling for file tools even when local shell
  execution is enabled.

Rejected options:

- Reintroduce scout shell execution.
- Add command-specific wrappers such as `run_tests` as the primary execution
  path.
- Require users to opt into local shell execution on every run.

Consequences:

- Local execution is powerful and trusted: commands run on the host machine with
  the current user's environment and permissions.
- Filesystem permissions do not constrain arbitrary shell commands; governance
  comes from explicit mode selection, the readiness gate, role prompts, and the
  option to disable execution with `--execution none`.
- A future sandbox profile can use the same agent-facing `execute` contract
  without changing specialist workflows.

Initial validation evidence from the execution-profile pass on 2026-05-25:

- Scout-backed static inspection reports shaping and implementation modes default
  to local execution for the manager graph, implementation specialists receive
  execution only in implementation mode, and scout still has no `execute` tool.
- Automated validation passed with `uv run --project / python -m unittest discover -s tests`.
- Result: exit code 0, `Ran 64 tests in 0.297s`, `OK`.

### DEC-0008: Approve broad implementation entry for bounded task-scoped work

Decision status: approved

Implementation status: approved for implementation entry; machine-readable gate recorded

Context:

DEC-0004/DEC-0005/DEC-0007 governance controls are implemented, statically inspected, and locally tested. The autonomous implementation pass added CI, resolved DEC-0006 as Python `>=3.11,<4.0`, aligned metadata/lockfile/docs/CI, and locally validated the suite on Python 3.11 through 3.14 with `Ran 82 tests`, `OK`. Hosted CI evidence and final release approval remain separate from implementation-entry approval.

Decision:

Approve entry into broad implementation mode for bounded, task-scoped tasks. Hosted CI evidence, final review, and explicit release approval are separate from implementation-entry approval.

Selected option:

- Proceed with bounded implementation tasks after the machine-readable readiness gate records `full_implementation` approval.
- Require each task to have a complete brief, explicit ownership, files/modules in scope, constraints, and acceptance criteria.
- Keep hosted CI evidence, final review, and explicit release approval visible as requirements before delivery-ready, release-ready, production-ready, or external distribution claims.

Rejected options:

- Block all implementation until CI is added.
- Block all implementation until DEC-0006 runtime metadata, lockfile, CI validation, and documentation alignment are complete.
- Permit unbounded implementation work without task-scoped briefs.

Rationale:

The governance controls needed to safely bound implementation work had passing local validation before broad implementation entry. CI and runtime compatibility affect repeatable release validation and adoption; they were accepted as implementation follow-ups and have now been implemented and locally validated, while hosted CI evidence and explicit release approval remain separate release concerns.

Consequences:

- Broad implementation work is approved only for bounded, task-scoped tasks.
- Runtime implementation mode is enabled by `readiness-gate.yaml`, which records `approved: true`, `approval_scope: full_implementation`, approver, and date.
- CI workflow is present and should be used for hosted release evidence.
- DEC-0006 is ratified as Python `>=3.11,<4.0`; metadata, lockfile, CI matrix, and documentation are aligned.
- No artifact may claim release readiness, production readiness, or external distribution readiness until release blockers are cleared or explicitly accepted.
