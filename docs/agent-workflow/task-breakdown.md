# Task Breakdown

Status: approved implementation tasks completed locally; release readiness not claimed

## Current Position

The human decision maker approved broad implementation mode on 2026-05-25 for
bounded, task-scoped tasks. The machine-readable `readiness-gate.yaml` records
that approval.

The codebase already contains a broad V0 implementation as a Python package and
CLI under `coding_agents/`. This task breakdown now separates:

- completed shaping and governance validation work;
- implementation/quality tasks eligible after machine-readable gate approval;
- release-readiness evidence that must be validated before delivery-ready,
  release-ready, production-ready, or external distribution claims.

## Status Legend

- `completed`: done as a docs-only shaping update.
- `pending`: still needed in shaping artifacts.
- `approved / task brief required`: authorized for implementation entry, but not assignable until a bounded brief is defined.
- `blocked`: cannot start until a dependency or other approval is complete.

## Component Implementation Status

| Area | Status | Notes |
| --- | --- | --- |
| Reusable Python package under `coding_agents/` | Implemented | Existing V0 module boundary. |
| Minimal CLI | Implemented | Local interactive entrypoint exists. |
| Engineering-manager Deep Agent | Implemented | Main coordinator exists. |
| Resident product analyst/software architect tools | Implemented | Manager-only resident collaborator tools exist. |
| SQLite/Postgres/memory checkpointers | Implemented | Local, shared/production, and disposable/test options exist. |
| Stable resident thread IDs | Implemented | Product and architecture residents have stable derived thread IDs. |
| Scout subagent | Implemented | Reconnaissance role exists. |
| Implementation subagent prompts/wiring | Implemented / statically inspected and tested; gated | Scout reports implementation subagents are registered only after implementation-mode readiness approval. |
| Tavily tools | Implemented | Web search/fetch tools exist. |
| Workflow artifacts | Approved for implementation entry | Files exist and capture the human decision approving bounded implementation entry; `readiness-gate.yaml` records the approval. |
| Permissions by mode | Implemented / statically inspected and tested | Shaping mode remains docs-only for writes; implementation writes are repo-wide by default after gate approval except protected readiness/secret paths; optional `--write-path` restrictions remain available. |
| Readiness gate enforcement | Implemented / statically inspected and tested; human-approved | Human approved broad implementation entry on 2026-05-25; `readiness-gate.yaml` records `approved: true` with `approval_scope: full_implementation`. |
| Tests and CI | CI workflow added; tests passing locally | `.github/workflows/ci.yml` runs tests, wheel build, clean wheel install, and CLI `--init-only` smoke on Python 3.11, 3.12, 3.13, and 3.14. Local validation passed on all four versions with `Ran 82 tests`, `OK`. |
| Python runtime support | Ratified and aligned | DEC-0006 ratifies `>=3.11,<4.0`; `pyproject.toml`, `.python-version`, `uv.lock`, docs, and CI are aligned. |

## Shaping Tasks

| ID | Task | Owner Role | Dependencies | Acceptance Criteria | Status |
| --- | --- | --- | --- | --- | --- |
| DOC-001 | Reconcile architecture, decision, task, and readiness artifacts with observed V0 implementation | software-architect | Observed implementation summary from engineering manager | `architecture-brief.md`, `decision-log.md`, `task-breakdown.md`, and `readiness-gate.md` reflect implemented/partial/missing status, risks, decisions, and proposed tasks | completed |
| SHAPE-001 | Replace product placeholders with real product context | product-analyst | Human/product input or existing validated context | `product-brief.md` documents problem, target users, goals, non-goals, MVP scope, and open questions | completed |
| SHAPE-002 | Replace requirements placeholders with acceptance criteria | product-analyst | SHAPE-001 | `requirements.md` documents functional requirements, non-functional requirements, edge cases, and core acceptance criteria | completed |
| SHAPE-003 | Prioritize MVP and deferred work | product-analyst + engineering-manager | SHAPE-001, SHAPE-002 | `prioritization.md` identifies candidate scope, MVP cut, deferred work, and rationale | completed |
| ARCH-001 | Ratify or revise proposed architecture decisions | software-architect + engineering-manager + human | Updated `decision-log.md` | DEC-0003 through DEC-0008 are approved, revised, or explicitly deferred | completed |
| PLAN-001 | Reconcile observed code facts into official readiness artifacts | engineering-manager + scout | Updated artifacts | `architecture-brief.md`, `decision-log.md`, `readiness-gate.md`, and this task breakdown separate observed code facts from readiness claims and record material mismatches | completed |
| PLAN-002 | Prepare readiness approval packet | engineering-manager | SHAPE-001 through SHAPE-003, ARCH-001, PLAN-001 | Human can review clear go/no-go status, unresolved questions, risks, and proposed implementation tasks | completed |

## Approved Implementation and Quality Tasks

Broad implementation mode is approved for bounded work. The implementation and
quality tasks below received bounded briefs during the 2026-05-25 autonomous
implementation pass. CI and DEC-0006 have been implemented and locally validated;
release-ready or production-ready claims still require review of the final change
set and, for external release evidence, a passing hosted CI run.

| ID | Task | Owner Role | Dependencies | Acceptance Criteria | Status |
| --- | --- | --- | --- | --- | --- |
| DEV-001 | Implement machine-enforced readiness gate | developer + engineering-manager | DEC-0004 approved; limited governance implementation authorized by human on 2026-05-24 | Implementation mode fails closed when readiness is not approved; gate state is machine-readable or otherwise checkable by the manager; denial messages identify missing gate items; tests cover approved, unapproved, missing, and invalid states | implemented / statically inspected and tested |
| DEV-002 | Tighten implementation-mode write protections | developer + engineering-manager | DEC-0005 approved; DEV-001 or equivalent guard; limited governance implementation authorized by human on 2026-05-24 | Implementation mode allows repo-wide writes by default after gate approval while protecting `readiness-gate.yaml` and secret-like paths; optional `--write-path` restrictions remain literal and safe; tests cover broad default, restricted runs, and protected denies | implemented / statically inspected and tested |
| QA-001 | Add automated tests for agent-team wiring | qa-engineer + developer | Stable package APIs; DEC-0001 and DEC-0002 retained | Tests cover manager construction, resident product/architecture tools, stable thread IDs, SQLite/memory checkpointers, scout wiring, Tavily tool registration, artifact templates, and mode permissions | completed / tested |
| DEVOPS-001 | Add CI for tests and packaging checks | devops-engineer | Test command defined | CI runs on pull requests or equivalent checks; package installs in a clean environment; CLI smoke test runs; failures block release readiness | completed / locally validated |
| ARCH-002 | Run Python runtime compatibility review | software-architect + devops-engineer | DEC-0006 approved; implementation-entry approved | Compatibility review documents dependency and environment support; package metadata, `.python-version`, docs, and CI match the ratified Python version or range; CI tests the ratified version or range | completed / aligned and tested locally |
| QA-002 | Validate CLI smoke path | qa-engineer + developer | CLI entrypoint stable | CLI starts in a clean environment, initializes the selected checkpointer, and reaches a safe interactive prompt without requiring implementation-mode approval | completed / tested |
| SEC-001 | Review tool and permission boundaries | security-reviewer | DEV-002 design available | Review covers scout read-only behavior, Tavily tools, filesystem write protections, destructive operation protections, and secret handling; findings are triaged before release readiness | completed / reviewed with residual risks documented |
| WRITER-001 | Update user-facing usage docs after gate decisions | technical-writer | SHAPE-001 through SHAPE-003; ARCH-001; relevant implementation tasks complete | README or equivalent docs describe installation, CLI use, checkpointer configuration, mode rules, and limitations consistent with code and decisions | completed |

## 2026-05-25 Implementation Pass Evidence

The approved autonomous implementation pass completed DEVOPS-001, ARCH-002,
QA-001, QA-002, SEC-001, and WRITER-001 without modifying
`docs/agent-workflow/readiness-gate.yaml`.

Implemented changes:

- added GitHub Actions CI in `.github/workflows/ci.yml` for Python 3.11, 3.12,
  3.13, and 3.14;
- ratified and aligned Python runtime support to `>=3.11,<4.0` in
  `pyproject.toml`, `.python-version`, `uv.lock`, CI, and docs;
- added tests for resident tools, stable thread IDs, scout wiring, checkpointers,
  Tavily tools, artifact templates, console script metadata, and CLI prompt smoke;
- hardened secret handling for common secret-like filenames and shell output
  redaction;
- updated README and architecture documentation for current usage, CI, runtime,
  mode rules, and limitations.

Validation evidence recorded locally:

- `uv lock --check` succeeded under `requires-python = ">=3.11,<4.0"`.
- `uv run --python 3.11 python -m unittest discover -s tests` passed with
  `Ran 82 tests`, `OK`.
- `uv run --python 3.12 python -m unittest discover -s tests` passed with
  `Ran 82 tests`, `OK`.
- `uv run --python 3.13 python -m unittest discover -s tests` passed with
  `Ran 82 tests`, `OK`.
- `uv run --python 3.14 python -m unittest discover -s tests` passed with
  `Ran 82 tests`, `OK`.
- A clean Python 3.11 wheel install, package import, and `coding-agents
  --init-only` smoke path passed locally.

Release readiness remains **not claimed** in this artifact. A hosted CI run should
be used as external release evidence before any release-ready, production-ready,
or external distribution claim.

## DEC-0004/DEC-0005 Corrective Security Pass

The corrective security pass has been implemented, statically inspected, and
validated by the local unittest suite on 2026-05-25. It:

- removed `scout.execute` instead of attempting broad shell command validation;
- closed case-variant bypasses for readiness and secret deny paths;
- rejects symlink components and verifies resolved containment for artifact dirs
  and write protections;
- validates `artifacts_dir` after resolution, not by string checks alone;
- redacts secrets from startup/runtime exception output.

Historical validation evidence for that corrective pass: `uv run --project / python -m unittest discover -s tests` exited 0 with `Ran 64 tests in 0.297s`, `OK`.

This pass did not introduce new dependencies, change runtime metadata, broaden
implementation mode, or add new scout command capabilities.

## Implementation Ordering Recommendation

1. Use the current baseline recorded in `architecture-brief.md`, `decision-log.md`, `readiness-gate.md`, and this task breakdown.
2. Require a bounded task brief before assigning any implementation specialist.
3. Use the completed CI and DEC-0006 work as release evidence only after final review and hosted CI validation.
4. Rerun scout-backed reconnaissance and update the official artifacts when code changes.
5. Update user-facing documentation after behavior and runtime support are stable.
