# Product Brief

Status: approved for implementation entry

## Problem

The project is a development-agent team built on LangChain Deep Agents. It should help a human decision maker shape, plan, implement, review, test, and document software work through a governed multi-agent workflow.

The observed V0 code already exists largely as a Python package and CLI under `coding_agents/`. The workflow artifacts have been reconciled with the current implementation state, governance tests pass locally, and the human decision maker approved broad implementation entry for bounded, task-scoped tasks on 2026-05-25.

## Target Users

- Human decision makers who want a coordinated AI development team rather than a single ad hoc coding agent.
- Engineering-manager agent operators who need clear workflow state, gates, and delegation rules.
- Specialist agent contributors who need scoped responsibilities and durable artifacts to coordinate work.

## Goals

- Provide a governed agent workflow with explicit shaping and implementation modes.
- Keep product, architecture, planning, and readiness state in versioned artifacts under `docs/agent-workflow/`.
- Support an engineering-manager Deep Agent as the primary interface and coordinator.
- Support resident product-analyst and software-architect conversations through manager-only tools.
- Support scoped disposable agents for scout, developer, review, QA, devops, security, and technical writing work.
- Make readiness-gate status visible before any implementation-mode work is assigned.

## Non-Goals

- Do not claim release readiness, delivery readiness, production readiness, or external distribution readiness until CI and DEC-0006 are complete or explicitly accepted as release risks.
- Do not treat the existing V0 code as production-ready without CI and runtime compatibility validation.
- Do not allow broad implementation-mode write access before scoped task ownership is defined.
- Do not implement a web UI in V0; web UI is the next product step after local-first V0.
- Do not implement multi-feature-stream coordination in the MVP.
- Do not distribute V0 externally; V0 is for local/repository use until tests, CI, runtime support, and API boundaries are validated.
- Do not introduce a persistent StoreBackend beyond the documented SQLite/Postgres/memory checkpointing options for V0.
- Do not expand implementation scope beyond bounded, task-scoped work without a new readiness or scope decision.

## MVP Scope

V0 MVP is a single-feature-stream development-agent workflow with:

- Engineering-manager Deep Agent and CLI entrypoint, with CLI as the only V0 user-facing entrypoint.
- Minimal first-party Python API consisting of `AgentTeamConfig` and `create_development_team_agent` for CLI and future first-party entrypoints.
- Resident product-analyst and software-architect tools restricted to manager use.
- Checkpointing options using SQLite, Postgres, or memory backends.
- Scout subagent for safe repo-local codebase reconnaissance; unrestricted shell execution is not part of the V0 product contract.
- Disposable implementation-mode specialist agents: developer, code-reviewer, QA, devops, security-reviewer, and technical-writer.
- Tavily-backed `web_search` and `fetch_url` tools.
- Artifact templates and living workflow docs under `docs/agent-workflow/`.
- Explicit shaping/implementation mode separation and documented readiness gate.

## Current State Summary

- Code exists largely as a Python package and CLI under `coding_agents/`.
- Core agent roles and web tools are represented.
- Workflow artifacts have been moved from placeholders to an implementation-entry-approved baseline.
- Broad implementation mode is approved for bounded, task-scoped tasks, but runtime activation still requires the machine-readable readiness gate to be updated by a permitted process.

## Open Questions / Deferred Decisions

- Which Python runtime range will be ratified by the DEC-0006 compatibility review before release readiness.
- Which permitted process or human edit will record the approval in `readiness-gate.yaml`, since current agent write permissions denied that update.
- Which automated tests and CI checks are required before V0 can be considered delivery-ready or production-ready.
- How the approved implementation-mode task-scoped write allowlists will be implemented and verified.
- How the approved coded readiness guard will be implemented and bootstrapped before broader implementation work.
