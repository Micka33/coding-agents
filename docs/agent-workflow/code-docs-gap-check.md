# Code / Docs Gap Check

Status: completed — historical baseline, superseded by limited DEC-0004/DEC-0005 governance implementation

Plan item: PLAN-001

## Summary

A scout-backed read-only reconnaissance pass compared the observed codebase with the current workflow artifacts after ARCH-001. This report is retained as the baseline that justified the limited DEC-0004/DEC-0005 implementation authorization. Its implementation-gap observations are now historical where they refer to missing readiness/write-scope enforcement.

Current status after the limited governance implementation: the main V0 shape remains aligned with approved decisions; DEC-0004 and DEC-0005 are implemented pending test execution/final validation; broad implementation mode remains blocked because the gate is not approved.

## Observed Code Facts

| Area | Evidence | Status |
| --- | --- | --- |
| Package + CLI delivery shape | `pyproject.toml`, `main.py`, `coding_agents/cli.py`, `coding_agents/` | aligned with DEC-0003 |
| V0 public Python API | `coding_agents/__init__.py` exports `AgentTeamConfig` and `create_development_team_agent` | aligned with DEC-0003 |
| SQLite/Postgres/memory checkpointers | `coding_agents/config.py`, `coding_agents/checkpoints.py` | aligned with DEC-0001 |
| Resident product/architecture agents | `coding_agents/resident_agents.py` | aligned with DEC-0001 and architecture brief |
| Scout subagent | `coding_agents/scout.py`, `coding_agents/team.py`, `coding_agents/prompts.py` | aligned with DEC-0002 |
| Tavily tools | `coding_agents/tools.py` | aligned with requirements |
| Shaping write permissions | `coding_agents/permissions.py` allows writes under `/docs/agent-workflow/` in shaping mode | aligned |
| Machine-readable readiness gate | Historical PLAN-001 finding: no `readiness-gate.yaml` observed before limited governance implementation | superseded by DEC-0004 implementation pending validation |
| Runtime readiness guard | Historical PLAN-001 finding: CLI accepted `--mode implementation` without guard | superseded by DEC-0004 implementation pending validation |
| Implementation subagent gating | Historical PLAN-001 finding: implementation subagents were registered before guard | superseded by DEC-0004 implementation pending validation |
| Implementation write permissions | Historical PLAN-001 finding: implementation writes allowed `/**` | superseded by DEC-0005 implementation pending validation |
| Tests | Focused tests added after PLAN-001; execution not yet recorded | missing release-readiness validation |
| CI | no `.github/` or equivalent CI observed | missing release-readiness validation |
| Python runtime | `pyproject.toml`, `.python-version`, and `uv.lock` use Python `>=3.14` / `3.14` | aligned with DEC-0006 as unresolved release risk |

## Material Gaps

| Gap | Classification | Required response |
| --- | --- | --- |
| Historical: no machine-readable readiness artifact or runtime guard | Superseded implementation gap | DEC-0004 implementation exists pending test execution/final validation; broad implementation remains blocked until gate approval. |
| Historical: CLI could select implementation mode without checking readiness | Superseded implementation gap | DEC-0004 runtime guard now exists pending validation. |
| Historical: implementation subagents available before guard | Superseded implementation gap | DEC-0004 runtime gating now exists pending validation. |
| Historical: implementation mode allowed repo-wide writes | Superseded implementation gap | DEC-0005 task-scoped literal write scopes now exist pending validation. |
| Automated tests not executed | Blocker before release readiness | Run unit/smoke tests for manager construction, resident tools, scout, permissions, artifacts, checkpointers, and CLI. |
| No CI observed | Blocker before release readiness | Add CI after test command is defined. |
| Python `>=3.14` is not ratified as final runtime | Blocker before release readiness | Run DEC-0006 compatibility review and align metadata/docs/CI. |
| Top-level README and architecture spec may lag current workflow decisions | Follow-up | Update after readiness/gate decisions are finalized or explicitly reopen docs scope outside `/docs/agent-workflow/`. |

## Documentation Reconciliation

The workflow artifacts were updated to reflect this gap check:

- `task-breakdown.md`: PLAN-001 is marked completed and points to this report.
- `readiness-gate.md`: scout-backed gap check is marked completed; readiness remains failed.
- `requirements.md`: duplicate corrupted tail was removed and readiness/write-scope acceptance criteria were retained.
- `prioritization.md`: readiness-gate enforcement remains P0 governance work, not deferred optional work.
- `architecture-brief.md`: remaining gaps point to specific governance/test/runtime items rather than broad unknown drift.

## Readiness Impact

PLAN-001 is complete after this report and artifact reconciliation.

The readiness gate is still not passed. Broad implementation mode remains blocked until the human explicitly approves it through the machine-readable gate. DEC-0004 and DEC-0005 enforcement has since been implemented and is pending test execution/final validation.
