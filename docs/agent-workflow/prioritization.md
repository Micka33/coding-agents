# Prioritization

Status: draft

## Candidate Scope

| Item | Impact | Effort | Risk | Priority | Notes |
| --- | --- | --- | --- | --- | --- |
| Align workflow artifacts with observed V0 state | High | Low | Low | P0 | Required before meaningful readiness review. |
| Add/verify tests for core agent construction, CLI, tools, and artifact templates | High | Medium | Medium | P0 | Current gap: no tests observed; code changes require gate approval or explicit shaping exception. |
| Add CI for lint/type/test checks | High | Medium | Medium | P0 | Required before V0 is represented as delivery-ready or production-ready. |
| Define and constrain implementation-mode write scopes | High | Medium | High | P0 | Current implementation-mode scope is too broad for safe delegation. |
| Document readiness-gate status and approval process | High | Low | Medium | P0 | Gate must remain unapproved until human approval. |
| Evaluate Python `>=3.14` requirement | Medium | Low | Medium | P1 | Adoption risk; may be acceptable only for a narrow early-adopter audience. |
| Code readiness-gate enforcement | Medium | Medium | Medium | P1 | Valuable, but documentation-only gate can be V0 if explicitly accepted. |
| Expand implementation-mode specialist behavior | Medium | High | High | P2 | Defer until scope controls, tests, and CI exist. |
| Multi-feature-stream support | Low | High | High | Later | Out of MVP. |
| Persistent StoreBackend beyond checkpointing | Low | High | Medium | Later | Deferred; artifacts remain durable source of truth. |

## MVP Cut

MVP should include only the minimum needed to operate a single-feature-stream governed agent team safely:

- Engineering-manager Deep Agent and CLI.
- Resident product and architecture agents via manager-only tools.
- SQLite/Postgres/memory checkpointing options.
- Scout and implementation-mode specialist definitions.
- Web tools and artifact templates.
- Completed draft artifacts for product, requirements, prioritization, task breakdown, and readiness gate.
- Documented P0 plan for tests and CI to validate core package/CLI behavior before delivery-ready or production-ready claims.
- Documented write-scope constraints for implementation-mode agents.

## Deferred Work

- Multi-feature-stream orchestration.
- Production/shared deployment hardening beyond documented Postgres checkpointing option.
- Persistent StoreBackend or long-term memory beyond repository artifacts.
- Automated readiness-gate enforcement, unless promoted to P0 by the engineering manager or human decision maker.
- Broad implementation-mode automation beyond narrowly scoped task briefs.
- Major dependency expansion unrelated to the V0 workflow.
