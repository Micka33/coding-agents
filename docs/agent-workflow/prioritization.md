# Prioritization

Status: approved for implementation entry

## Candidate Scope

| Item | Impact | Effort | Risk | Priority | Notes |
| --- | --- | --- | --- | --- | --- |
| Align workflow artifacts with observed V0 state | High | Low | Low | P0 | Required before meaningful readiness review. |
| Run/verify tests for core agent construction, CLI, tools, safe filesystem, and artifact templates | High | Medium | Medium | P0 | Local unittest suite passed on 2026-05-25 with `uv run --project / python -m unittest discover -s tests` (`Ran 64 tests`, `OK`). |
| Add CI for lint/type/test checks | High | Medium | Medium | P0 | Required before V0 is represented as delivery-ready or production-ready. |
| Validate task-scoped write-scope enforcement | High | Medium | High | P0 | DEC-0005 implementation is statically inspected and locally tested. |
| Record readiness-gate approval in machine-readable gate | High | Low | Medium | P0 | Human approved broad implementation entry on 2026-05-25; current agent write permissions denied updating `readiness-gate.yaml`, so a permitted process must record `full_implementation` approval before runtime implementation mode is used. |
| Run Python runtime compatibility review | Medium | Low | Medium | P1 | Approved by DEC-0006; Python `>=3.14` remains an unresolved release risk until ratified or changed. |
| Validate coded readiness-gate enforcement | High | Medium | Medium | P0 | DEC-0004 implementation is statically inspected and locally tested. |
| Maintain no-shell scout and hardened path/error protections | High | Low | Medium | P0 | Scout shell execution has been removed; keep this invariant and validate with tests/security review. |
| Expand implementation-mode specialist behavior | Medium | High | High | P2 | Defer until scope controls, tests, and CI exist. |
| Multi-feature-stream support | Low | High | High | Later | Out of MVP. |
| Persistent StoreBackend beyond checkpointing | Low | High | Medium | Later | Deferred; artifacts remain durable source of truth. |

## Readiness Decision

Human decision recorded on 2026-05-25: approve broad implementation mode for bounded, task-scoped work. This is an implementation-entry decision, not a release-readiness decision:

- Passing local tests support marking DEC-0004/DEC-0005/DEC-0007 governance controls as tested readiness evidence.
- Absence of CI remains a release-readiness blocker and a P0 follow-up; it does not block broad implementation entry by explicit human decision.
- DEC-0006 Python runtime review remains a release-readiness blocker and P1/P0-follow-up for release planning; it does not block broad implementation entry by explicit human decision.
- Runtime implementation mode still requires `readiness-gate.yaml` to record `full_implementation` approval through a permitted process.
- No artifact should claim delivery readiness, release readiness, production readiness, or external distribution readiness until release blockers are cleared or explicitly accepted.

## MVP Cut

MVP should include only the minimum needed to operate a single-feature-stream governed agent team safely:

- Engineering-manager Deep Agent and CLI.
- Resident product and architecture agents via manager-only tools.
- SQLite/Postgres/memory checkpointing options.
- Scout and implementation-mode specialist definitions.
- Web tools and artifact templates.
- Implementation-entry-approved artifacts for product, requirements, prioritization, task breakdown, and readiness gate, with machine-readable gate recording still pending by permitted process.
- Documented P0 plan for tests and CI to validate core package/CLI behavior before delivery-ready or production-ready claims.
- Documented write-scope constraints for implementation-mode agents.

## Deferred Work

- Web UI after local-first V0 is validated.
- Multi-feature-stream orchestration.
- Production/shared deployment hardening beyond documented Postgres checkpointing option.
- External package distribution until tests, CI, runtime support, and API boundaries are validated.
- Persistent StoreBackend or long-term memory beyond repository artifacts.
- Additional readiness automation beyond the DEC-0004 fail-closed runtime guard.
- Broad, unbounded implementation-mode automation beyond narrowly scoped task briefs.
- Major dependency expansion unrelated to the V0 workflow.
