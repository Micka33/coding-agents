# Product Brief

Status: draft

## Problem

The project is a development-agent team built on LangChain Deep Agents. It should help a human decision maker shape, plan, implement, review, test, and document software work through a governed multi-agent workflow.

The observed V0 code already exists largely as a Python package and CLI under `coding_agents/`, but the workflow artifacts are not yet complete enough to approve implementation mode. The immediate product need is to align the documentation with the current implementation state without claiming readiness-gate approval.

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

- Do not claim the readiness gate is approved until a human explicitly approves it.
- Do not treat the existing V0 code as production-ready without tests, CI, and gate validation.
- Do not allow broad implementation-mode write access before scoped task ownership is defined.
- Do not implement multi-feature-stream coordination in the MVP.
- Do not introduce a persistent StoreBackend beyond the documented SQLite/Postgres/memory checkpointing options for V0.
- Do not expand scope beyond documentation and planning while the project remains in shaping mode.

## MVP Scope

V0 MVP is a single-feature-stream development-agent workflow with:

- Engineering-manager Deep Agent and CLI entrypoint.
- Resident product-analyst and software-architect tools restricted to manager use.
- Checkpointing options using SQLite, Postgres, or memory backends.
- Scout subagent for codebase reconnaissance.
- Disposable implementation-mode specialist agents: developer, code-reviewer, QA, devops, security-reviewer, and technical-writer.
- Tavily-backed `web_search` and `fetch_url` tools.
- Artifact templates and living workflow docs under `docs/agent-workflow/`.
- Explicit shaping/implementation mode separation and documented readiness gate.

## Current State Summary

- Code exists largely as a Python package and CLI under `coding_agents/`.
- Core agent roles and web tools are represented.
- Workflow artifacts have been moved from placeholders to draft state.
- Implementation mode is not approved.

## Open Questions / Deferred Decisions

- Whether Python `>=3.14` is acceptable for target adopters, given adoption risk.
- Which automated tests and CI checks are required before V0 can be considered delivery-ready or production-ready.
- How implementation-mode filesystem write scopes will be constrained and enforced.
- Whether the readiness gate remains documentation-only for V0 or receives coded enforcement before approval.
