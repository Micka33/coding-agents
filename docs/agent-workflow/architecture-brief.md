# Architecture Brief

Status: approved for implementation entry

## Context

V0 already exists in code as a reusable Python package plus a minimal CLI under
`coding_agents/`. The workflow artifacts previously lagged behind the implementation. They have
now been reconciled and approved as the implementation-entry baseline for bounded,
task-scoped work.

This document records the observed implementation state so follow-up
implementation work can be planned against reality rather than the old
placeholders.

The human decision maker approved broad implementation mode on 2026-05-25 for
bounded, task-scoped tasks. Runtime implementation still requires the
machine-readable `readiness-gate.yaml` to record that approval; the current agent
write attempt was denied by tool permissions.

## Constraints

- Keep implementation lightweight for local development.
- Preserve product and architecture conversation history across CLI restarts.
- Keep repository artifacts as the durable source of truth.
- Provide a path to shared or production deployments.
- Do not rely on documentation alone when the human asks where implementation
  stands; use codebase reconnaissance.
- Assign implementation work only after the machine-readable readiness gate records
  full approval and each task has a bounded brief with explicit write scope.
- CI and DEC-0006 are release-readiness blockers, not implementation-entry blockers,
  by human decision on 2026-05-25.

## Observed Implementation Snapshot

| Component | Observed state | Status | Notes |
| --- | --- | --- | --- |
| Reusable Python package | Code exists under `coding_agents/` | Implemented | V0 is structured as an importable module rather than a one-off script. |
| CLI | Minimal interactive CLI exists | Implemented | CLI is the local entrypoint for the package. |
| Engineering manager Deep Agent | Present | Implemented | Main interface and coordinator for the agent team. |
| Resident product analyst and software architect | Present through manager-only tools | Implemented | Product and architecture collaborators are resident teammates rather than stateless task subagents. |
| Stable resident thread IDs | Defined for product and architecture residents | Implemented | Uses `<manager-thread-id>:resident:product-analyst` and `<manager-thread-id>:resident:software-architect`. |
| Checkpointers | SQLite, Postgres, and memory options exist | Implemented | SQLite is the local durable default; Postgres supports shared/production deployment; memory is useful for tests. |
| Scout subagent | Present | Implemented | Used for codebase reconnaissance before status, readiness, progress, or gap analysis answers. |
| Tavily tools | `web_search` and `fetch_url` available | Implemented | Used when current external documentation or source verification is needed. |
| Workflow artifacts | Files exist under `/docs/agent-workflow/` and have been reconciled with observed V0 state | Approved for implementation entry | Core artifacts capture the 2026-05-25 human approval for bounded, task-scoped implementation entry; machine-readable YAML recording remains pending by permitted process. |
| Permissions by mode | Mode concept exists with hardened enforcement | Implemented / statically inspected and tested | Scout-backed static inspection reports shaping writes are explicit workflow-artifact files only; implementation writes require task-scoped literal paths and safe filesystem handling. |
| Implementation subagent prompts/wiring | Developer/reviewer/QA/devops/security/writer wiring exists | Implemented / statically inspected and tested; gated | Scout-backed static inspection reports runtime construction gates implementation subagents behind machine-readable readiness approval. |
| Readiness gate enforcement | Machine-readable guard exists | Implemented / statically inspected and tested | `readiness-gate.yaml` defaults unapproved and implementation mode fails closed unless full approval metadata is present; local unittest validation passed on 2026-05-25. |
| Tests and CI | `unittest` suite present; CI not observed | Tests passing locally; CI missing | Local validation passed with `uv run --project / python -m unittest discover -s tests`; result: exit code 0, `Ran 64 tests in 0.297s`, `OK`. |
| Python runtime floor | Python `>=3.14` risk observed | Partially implemented / risky | May reduce adoption or conflict with available environments; requires explicit ratification or adjustment. |

## Validation Evidence

Current evidence combines scout-backed static inspection and local test execution:

- Scout-backed inspection confirms the readiness guard, implementation subagent
  gating, task-scoped write allowlists, safe path checks, protected readiness/secret
  paths, and no-shell scout behavior are present in code.
- Automated validation passed on 2026-05-25 with `uv run --project / python -m unittest discover -s tests`.
- Result: exit code 0, `Ran 64 tests in 0.297s`, `OK`.
- This supports `implemented / statically inspected and tested` for DEC-0004,
  DEC-0005, and DEC-0007 governance controls.
- Human approval for broad implementation mode was recorded in Markdown artifacts
  on 2026-05-25, but `readiness-gate.yaml` still requires update by a permitted
  process before runtime implementation mode will pass.

## Current Architecture

- `coding_agents/` is the reusable Python package boundary.
- The CLI wraps the package for local interactive use.
- The engineering manager is the primary Deep Agent and the default human-facing
  interface.
- Product and architecture collaborators are resident agents contacted through
  manager-only tools, not disposable subagents.
- Resident product and architecture threads use stable IDs derived from the
  manager thread ID:

  ```text
  <manager-thread-id>:resident:product-analyst
  <manager-thread-id>:resident:software-architect
  ```

- LangGraph checkpointers provide conversation continuity:
  - SQLite for default local durability.
  - Postgres for shared or production deployments.
  - In-memory for tests or temporary sessions.
- The scout is a disposable reconnaissance subagent. It should gather codebase
  facts and return compressed context; it must not own product or architecture
  decisions. In the hardened V0 implementation, scout has no shell/`execute` tool
  and `grep` is Python literal search.
- Implementation-mode agents are available for developer, code review, QA,
  DevOps, security, and documentation work, but should only be activated after
  readiness approval.
- Local command execution is an explicit implementation-mode profile. When
  enabled, the manager graph and implementation specialists receive the Deep
  Agents `execute` tool against the host machine; scout, shaping mode, and
  resident product/architecture agents remain without general shell execution.
- `/docs/agent-workflow/` remains the durable source of truth for product,
  architecture, planning, readiness, and decision artifacts.

## Module Boundaries and Contracts

### CLI Boundary

The CLI should remain a thin entrypoint that configures and runs the reusable
package. It should not become the primary owner of product, architecture, or
workflow policy.

For V0, the CLI is the only user-facing entrypoint officially supported. A web UI
is the expected next product step after V0, not part of the V0 delivery shape.

### Package Boundary

The `coding_agents/` package owns agent construction, tool wiring, checkpointer
configuration, prompts, and mode-aware permissions.

The V0 public Python API is intentionally minimal and first-party only:

- `AgentTeamConfig`
- `create_development_team_agent`

This surface exists so the CLI and future first-party entrypoints, especially the
planned web UI, have a stable construction seam. It is not an external SDK
commitment for V0.

All other package modules and symbols are internal by default unless a later
decision explicitly promotes them to public API.

### Engineering Manager Contract

The engineering manager owns orchestration, artifact updates, readiness
enforcement, delegation, and final synthesis. It must route specialist questions
through artifacts or the human rather than allowing implementation agents to make
undocumented product or architecture assumptions.

### Resident Agent Contract

The product analyst and software architect are contacted through manager-only
resident tools. Their conversation state may be checkpointed, but durable project
truth must still be written to versioned artifacts.

### Checkpointer Contract

Checkpointing preserves working conversation history. It does not replace
approved repository artifacts. SQLite files are local working memory; Postgres is
reserved for shared or production deployments; in-memory state is disposable.

### Scout Contract

The scout performs fast codebase reconnaissance using scoped read tools and
returns compressed facts. It should separate observed codebase facts from
interpretation and should not make product or architecture decisions.

### Implementation Subagent Contract

Developer and review subagents require a complete task brief, explicit files or
modules in scope, files or modules out of scope, constraints, and acceptance
criteria. Their write scopes should be task-scoped rather than broad.

### Artifact and Permission Contract

During shaping mode, writes are limited to explicit workflow artifact files under
`/docs/agent-workflow/`; the machine-readable readiness gate is not writable by
agent tools. During implementation mode, write permissions are explicitly granted
per task and only after machine-readable readiness approval. Implementation write
scopes use literal exact files or existing directories, not globs.

## Gaps

| Gap | Status | Impact | Proposed response |
| --- | --- | --- | --- |
| Product artifacts approved for implementation entry | Approved | Problem, users, MVP, non-goals, and acceptance criteria are documented and accepted by the human decision maker for bounded implementation entry. | Keep scope bounded and update artifacts when decisions change. |
| Readiness gate enforcement validated locally | Implemented / statically inspected and tested; YAML recording pending | Scout-backed inspection reports the DEC-0004 guard is implemented and fails closed; local unittest suite passed on 2026-05-25; human approval is recorded in Markdown artifacts but not yet in YAML. | Update `readiness-gate.yaml` through a permitted process before runtime implementation mode. |
| Tests and CI status | Tests passing locally; CI missing / release blocker | Local validation passed with `uv run --project / python -m unittest discover -s tests`; result: exit code 0, `Ran 64 tests in 0.297s`, `OK`; CI is still missing. | Add CI before release readiness. |
| Implementation write-scope enforcement validated locally | Implemented / statically inspected and tested | Scout-backed inspection reports DEC-0005 literal write scopes and safe filesystem protections are implemented; local unittest suite passed on 2026-05-25. | Use bounded task briefs and explicit write scopes for every implementation task. |
| Python `>=3.14` adoption risk | Release blocker / risky | Runtime files currently use Python `>=3.14`; DEC-0006 requires compatibility review before release readiness but not before implementation entry. | Ratify the runtime floor or lower it before release readiness. |
| Top-level docs may lag workflow decisions | Follow-up | README and `docs/development-agent-team-architecture.md` may need updates after workflow decisions are finalized. | Update after readiness/gate decisions are finalized or explicit docs scope is reopened. |

## Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Documentation and code drift | High | Require scout reconnaissance for status/gap questions and update artifacts when decisions change. |
| Machine-readable gate recording pending | High | Record the 2026-05-25 human approval in `readiness-gate.yaml` through a permitted process before runtime implementation mode. |
| CI missing after local validation | High | Add CI before release readiness so validation is repeatable. |
| Python `>=3.14` runtime floor limits adoption | Medium | Perform compatibility review and ratify or adjust the supported Python range. |
| SQLite treated as source of truth | Medium | Keep decisions and requirements in versioned artifacts; treat checkpoint files as working memory only. |
| Scout reports are compressed | Medium | Follow up with direct reads for high-risk or disputed claims. |
| Postgres setup requires credentials and infrastructure | Low / Medium | Keep Postgres configurable and document required deployment settings separately. |

## Architecture Decisions Referenced

- DEC-0001: SQLite checkpointing for resident agent memory — approved and
  observed as implemented.
- DEC-0002: Scout subagent for codebase reconnaissance — approved and observed
  as implemented.
- DEC-0003: Ratify reusable Python package plus CLI as the V0 delivery shape —
  approved with a minimal first-party API boundary and CLI-only user entrypoint for V0.
- DEC-0004: Machine-enforce readiness before implementation mode — approved; implemented / statically inspected and tested.
- DEC-0005: Tighten implementation-mode write scopes — approved; implemented / statically inspected and tested with literal-only write scopes and safe filesystem protections.
- DEC-0006: Ratify or adjust the Python runtime floor — approved; Python `>=3.14` remains an unresolved release risk until compatibility review ratifies or changes it.
- DEC-0007: Explicit command execution profiles — approved; implemented / statically inspected and tested.
- DEC-0008: Approve broad implementation entry for bounded task-scoped work — approved by the human decision maker on 2026-05-25; machine-readable gate recording pending by permitted process.
