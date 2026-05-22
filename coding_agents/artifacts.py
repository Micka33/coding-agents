"""Artifact templates for the development-agent workflow."""

from __future__ import annotations

from pathlib import Path


ARTIFACT_TEMPLATES: dict[str, str] = {
    "product-brief.md": """# Product Brief

Status: draft

## Problem

TBD

## Target Users

TBD

## Goals

- TBD

## Non-Goals

- TBD

## MVP Scope

TBD

## Open Questions

- TBD
""",
    "requirements.md": """# Requirements

Status: draft

## Functional Requirements

- TBD

## Non-Functional Requirements

- TBD

## Edge Cases

- TBD

## Acceptance Criteria

- TBD
""",
    "prioritization.md": """# Prioritization

Status: draft

## Candidate Scope

| Item | Impact | Effort | Risk | Priority | Notes |
| --- | --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD | TBD |

## MVP Cut

TBD

## Deferred Work

- TBD
""",
    "architecture-brief.md": """# Architecture Brief

Status: draft

## Context

TBD

## Constraints

- TBD

## Proposed Architecture

TBD

## Options Considered

| Option | Pros | Cons | Decision |
| --- | --- | --- | --- |
| TBD | TBD | TBD | TBD |

## Risks

- TBD
""",
    "decision-log.md": """# Decision Log

Status: draft

## Decisions

### DEC-0001: TBD

Status: proposed

Context:

Decision:

Options considered:

Consequences:
""",
    "task-breakdown.md": """# Task Breakdown

Status: draft

## Implementation Plan

No developer tasks should be assigned until the readiness gate is approved.

| ID | Task | Owner Role | Dependencies | Acceptance Criteria | Status |
| --- | --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD | draft |
""",
    "readiness-gate.md": """# Readiness Gate

Status: draft

Implementation mode requires explicit human approval.

## Checklist

- [ ] Product problem is clear
- [ ] Target user or usage context is defined
- [ ] MVP is defined
- [ ] Non-goals are documented
- [ ] Core acceptance criteria are documented
- [ ] Major architecture choices are made
- [ ] Major technical risks are identified
- [ ] Open questions are answered or explicitly deferred
- [ ] Task breakdown is clear enough for developer agents
- [ ] Each implementation task has acceptance criteria
- [ ] Human approved the move to implementation mode

## Approval

Approved by:

Date:

Notes:
""",
}


def ensure_agent_workflow_files(
    root_dir: str | Path = ".",
    artifacts_dir: str | Path = "docs/agent-workflow",
) -> list[Path]:
    """Create the V0 workflow artifact files if they do not exist.

    Existing files are left untouched so humans and agents can iterate safely.
    """

    root = Path(root_dir).resolve()
    target_dir = root / artifacts_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    for filename, content in ARTIFACT_TEMPLATES.items():
        path = target_dir / filename
        if path.exists():
            continue
        path.write_text(content, encoding="utf-8")
        created.append(path)

    return created
