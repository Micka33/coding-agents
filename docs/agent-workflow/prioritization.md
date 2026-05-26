# Prioritization

Status: approved for implementation entry

## Candidate Scope

| Item | Impact | Effort | Risk | Priority | Notes |
| --- | --- | --- | --- | --- | --- |
| Align workflow artifacts with observed V0 state | High | Low | Low | P0 | Required before meaningful readiness review. |
| Run/verify tests for core agent construction, CLI, tools, safe filesystem, and artifact templates | High | Medium | Medium | completed | Local unittest suite passed on 2026-05-25 on Python 3.11, 3.12, 3.13, and 3.14 with `Ran 82 tests`, `OK`. |
| Add CI for test/package/smoke checks | High | Medium | Medium | completed | `.github/workflows/ci.yml` validates tests, wheel build, clean wheel install, and CLI smoke on Python 3.11 through 3.14. |
| Validate implementation write protections | High | Medium | High | P0 | DEC-0005 implementation is statically inspected and locally tested; repo-wide default writes are allowed only after gate approval and protected paths remain denied. |
| Record readiness-gate approval in machine-readable gate | High | Low | Medium | completed | Human approved broad implementation entry on 2026-05-25; `readiness-gate.yaml` records `full_implementation` approval. |
| Run Python runtime compatibility review | Medium | Low | Medium | completed | DEC-0006 ratifies Python `>=3.11,<4.0`; metadata, lockfile, docs, and CI are aligned. |
| Validate coded readiness-gate enforcement | High | Medium | Medium | P0 | DEC-0004 implementation is statically inspected and locally tested. |
| Maintain no-shell scout and hardened path/error protections | High | Low | Medium | P0 | Scout shell execution has been removed; keep this invariant and validate with tests/security review. |
| Expand implementation-mode specialist behavior | Medium | High | High | P2 | Defer until scope controls, tests, and CI exist. |
| Multi-feature-stream support | Low | High | High | Later | Out of MVP. |
| Persistent StoreBackend beyond checkpointing | Low | High | Medium | Later | Deferred; artifacts remain durable source of truth. |

## Readiness Decision

Human decision recorded on 2026-05-25: approve broad implementation mode for bounded, task-scoped work. This is an implementation-entry decision, not a release-readiness decision:

- Passing local tests support marking DEC-0004/DEC-0005/DEC-0006/DEC-0007 governance controls as tested readiness evidence.
- CI workflow is present for hosted release validation; a hosted CI run remains required external release evidence.
- DEC-0006 Python runtime review is complete and aligned to `>=3.11,<4.0`.
- `readiness-gate.yaml` records `full_implementation` approval.
- No artifact should claim delivery readiness, release readiness, production readiness, or external distribution readiness until final review, hosted CI evidence, and explicit release approval are complete.

## MVP Cut

MVP should include only the minimum needed to operate a single-feature-stream governed agent team safely:

- Engineering-manager Deep Agent and CLI.
- Resident product and architecture agents via manager-only tools.
- SQLite/Postgres/memory checkpointing options.
- Scout and implementation-mode specialist definitions.
- Web tools and artifact templates.
- Implementation-entry-approved artifacts for product, requirements, prioritization, task breakdown, and readiness gate, with machine-readable gate recording complete.
- Tests and CI validating core package/CLI behavior before delivery-ready or production-ready claims.
- Documented implementation-mode write protections, including repo-wide default writes after gate approval, protected file denies, and optional explicit write restrictions.

## Deferred Work

- Web UI after local-first V0 is validated.
- Multi-feature-stream orchestration.
- Production/shared deployment hardening beyond documented Postgres checkpointing option.
- External package distribution until hosted CI, release approval, and API boundaries are validated for distribution.
- Persistent StoreBackend or long-term memory beyond repository artifacts.
- Additional readiness automation beyond the DEC-0004 fail-closed runtime guard.
- Broad, unbounded implementation-mode automation beyond narrowly scoped task briefs.
- Major dependency expansion unrelated to the V0 workflow.
