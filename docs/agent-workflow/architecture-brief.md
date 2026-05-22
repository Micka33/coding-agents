# Architecture Brief

Status: draft

## Context

V0 already exists in code as a reusable Python package plus a minimal CLI under
`coding_agents/`. The workflow artifacts previously lagged behind the implementation. They have
now been reconciled into draft form, but they still need human validation before
readiness approval.

This document records the observed implementation state so shaping, readiness,
and follow-up implementation work can be planned against reality rather than the
old placeholders.

Current operating mode remains shaping mode. During shaping mode, changes are
limited to `/docs/agent-workflow/`; implementation code changes require readiness
gate approval.

## Constraints

- Keep implementation lightweight for local development.
- Preserve product and architecture conversation history across CLI restarts.
- Keep repository artifacts as the durable source of truth.
- Provide a path to shared or production deployments.
- Do not rely on documentation alone when the human asks where implementation
  stands; use codebase reconnaissance.
- Do not assign implementation work until the readiness gate is approved by the
  human.
- In shaping mode, update only files under `/docs/agent-workflow/`.

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
| Workflow artifacts | Files exist under `/docs/agent-workflow/` and have been reconciled with observed V0 state | Partially implemented | Core artifacts now contain draft content, but remain unapproved and require human validation. |
| Permissions by mode | Mode concept exists | Partially implemented | Shaping mode is docs-only; implementation-mode write permissions appear broad and need tighter task-scoped controls. |
| Implementation subagent prompts/wiring | Developer/reviewer/QA/devops/security/writer wiring exists | Partially implemented | Wiring exists, but readiness and quality gates are not yet fully enforced. |
| Readiness gate enforcement | Documentation exists only | Missing in code | No observed machine-enforced readiness gate. |
| Tests and CI | Not observed | Missing | Lack of automated validation is a release and regression risk. |
| Python runtime floor | Python `>=3.14` risk observed | Partially implemented / risky | May reduce adoption or conflict with available environments; requires explicit ratification or adjustment. |

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
  decisions.
- Implementation-mode agents are available for developer, code review, QA,
  DevOps, security, and documentation work, but should only be activated after
  readiness approval.
- `/docs/agent-workflow/` remains the durable source of truth for product,
  architecture, planning, readiness, and decision artifacts.

## Module Boundaries and Contracts

### CLI Boundary

The CLI should remain a thin entrypoint that configures and runs the reusable
package. It should not become the primary owner of product, architecture, or
workflow policy.

### Package Boundary

The `coding_agents/` package owns agent construction, tool wiring, checkpointer
configuration, prompts, and mode-aware permissions. Public package contracts
should stay stable enough for the CLI and tests to exercise the same behavior.

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

During shaping mode, writes are limited to `/docs/agent-workflow/`. During
implementation mode, write permissions should be explicitly granted per task and
only after human approval of the readiness gate.

## Gaps

| Gap | Status | Impact | Proposed response |
| --- | --- | --- | --- |
| Product artifacts are draft and unapproved | Partial | Problem, users, MVP, non-goals, and acceptance criteria are now documented in draft form but have not been validated by the human decision maker. | Review and approve, revise, or explicitly defer open product questions. |
| Readiness gate is not machine-enforced | Missing | Developers could be activated or broad writes allowed before approval. | Add a machine-readable gate and runtime guard before implementation mode. |
| Tests and CI are absent | Missing | Agent wiring, permissions, checkpointers, and CLI behavior can regress silently. | Add unit/smoke tests and CI before release readiness. |
| Implementation-mode writes are broad | Partial | Increases risk of unintended changes by implementation subagents. | Introduce task-scoped allowlists and stricter mode guards. |
| Python `>=3.14` adoption risk | Partial / risky | Users may not have the required runtime; dependency support may lag. | Ratify the runtime floor or lower it after compatibility review. |
| Artifact state lags code state | Partial | Planning and readiness answers can contradict the implementation. | Keep this architecture brief, decision log, task breakdown, and readiness gate synchronized with observed code. |

## Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Documentation and code drift | High | Require scout reconnaissance for status/gap questions and update artifacts when decisions change. |
| Missing readiness gate enforcement | High | Implement a coded gate before allowing implementation-mode delegation. |
| Broad implementation write permissions | High | Use task-scoped write allowlists and role-specific permission profiles. |
| No automated tests or CI | High | Add tests for package construction, CLI startup, checkpointers, resident tools, scout wiring, mode permissions, and artifact templates. |
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
  proposed to ratify an observed implementation.
- DEC-0004: Machine-enforce readiness before implementation mode — proposed.
- DEC-0005: Tighten implementation-mode write scopes — proposed.
- DEC-0006: Ratify or adjust the Python runtime floor — proposed.
