# Prioritization

Status: draft

## Candidate Scope

| Item | Impact | Effort | Risk | Priority | Notes |
| --- | --- | --- | --- | --- | --- |
| Align workflow artifacts with observed V0 state | High | Low | Low | P0 | Required before meaningful readiness review. |
| Run/verify tests for core agent construction, CLI, tools, safe filesystem, and artifact templates | High | Medium | Medium | P0 | Focused tests now exist; execution still required before validation/release-readiness claims. |
| Add CI for lint/type/test checks | High | Medium | Medium | P0 | Required before V0 is represented as delivery-ready or production-ready. |
| Validate task-scoped write-scope enforcement | High | Medium | High | P0 | DEC-0005 implementation exists pending test execution/final validation. |
| Document readiness-gate status and approval process | High | Low | Medium | P0 | Gate must remain unapproved for broad implementation until human approval is recorded in the machine-readable gate. |
| Run Python runtime compatibility review | Medium | Low | Medium | P1 | Approved by DEC-0006; Python `>=3.14` remains an unresolved release risk until ratified or changed. |
| Validate coded readiness-gate enforcement | High | Medium | Medium | P0 | DEC-0004 implementation exists pending test execution/final validation. |
| Maintain no-shell scout and hardened path/error protections | High | Low | Medium | P0 | Scout shell execution has been removed; keep this invariant and validate with tests/security review. |
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

- Web UI after local-first V0 is validated.
- Multi-feature-stream orchestration.
- Production/shared deployment hardening beyond documented Postgres checkpointing option.
- External package distribution until tests, CI, runtime support, and API boundaries are validated.
- Persistent StoreBackend or long-term memory beyond repository artifacts.
- Additional readiness automation beyond the DEC-0004 fail-closed runtime guard.
- Broad implementation-mode automation beyond narrowly scoped task briefs.
- Major dependency expansion unrelated to the V0 workflow.
