OpenSpec operating model:
- OpenSpec version investigated locally: `@fission-ai/openspec` 1.3.0.
- `openspec init [path] --tools codex --force --profile core` creates `openspec/config.yaml`, `.codex/skills/openspec-explore/SKILL.md`, `.codex/skills/openspec-propose/SKILL.md`, `.codex/skills/openspec-apply-change/SKILL.md`, `.codex/skills/openspec-archive-change/SKILL.md`, and corresponding Codex command files.
- `openspec init --tools none` creates only the OpenSpec structure/config.
- `openspec update [path] --force` refreshes generated skills and commands for configured tools.
- Core profile workflows are `propose`, `explore`, `apply`, and `archive`. The package also knows expanded workflows (`new`, `continue`, `ff`, `sync`, `bulk-archive`, `verify`, `onboard`), but default guidance should stay on the core flow unless project config says otherwise.
- The default `spec-driven` schema is proposal -> specs and design -> tasks. `apply` is blocked until `tasks` exists.
- `openspec new change <kebab-name> --description "<text>" --schema spec-driven` creates `openspec/changes/<name>/.openspec.yaml` and optional `README.md`; agents write proposal/spec/design/tasks.
- Use `openspec status --change <name> --json` as the source of truth for artifact order, readiness, and missing dependencies.
- Use `openspec instructions <artifact> --change <name> --json` before writing every artifact. Follow its `instruction`, `template`, `outputPath`, `dependencies`, `context`, and `rules`.
- Use `openspec instructions apply --change <name> --json` before implementation. If it reports `state: "blocked"`, do not implement.
- Use `openspec validate <name> --type change --strict --json` before telling the user a change is ready.
- Use `openspec show <name> --json --deltas-only` when debugging parsed delta requirements.
- Use `openspec archive <name> -y` only after implementation is complete and the user wants finalization.

Spec-driven artifact rules:
- `proposal.md` explains why, what changes, new/modified capabilities, and impact. Keep implementation details in design.
- Specs live under `openspec/changes/<name>/specs/<capability>/spec.md`.
- Delta headers must be `## ADDED Requirements`, `## MODIFIED Requirements`, `## REMOVED Requirements`, or `## RENAMED Requirements`.
- Requirements use `### Requirement: <name>`.
- Requirement text uses SHALL/MUST for normative behavior.
- Scenarios use exactly `#### Scenario: <name>` and WHEN/THEN bullets. Every requirement has at least one scenario.
- MODIFIED requirements must copy the full existing requirement block before editing it.
- `design.md` records context, goals/non-goals, decisions with alternatives, risks and mitigations, migration/rollback, and open questions.
- `tasks.md` is the implementation queue. It must use parseable checkboxes (`- [ ] 1.1 ...`) grouped under numbered headings.

Team quality rules:
- This is a Studio conversation team. The default chat target is
  `openspec-guide`; resident advisors can be mentioned directly, and the guide
  coordinates writing and review when a coherent change slice emerges.
- At the start of a substantive target-project session, ensure OpenSpec and the
  Codex OpenSpec skills exist in the target project. If `openspec/config.yaml`
  is missing, run `openspec init . --tools codex --force --profile core`. If
  OpenSpec exists but `.codex/skills/openspec-*` files are missing or stale, run
  `openspec update . --force`. Verify the expected skill files before creating
  or modifying changes.
- Shape before writing. If the user's idea is vague, explore, suggest improvements, identify gaps, and ask only decision-critical questions.
- Make changes small and focused. Prefer several coherent OpenSpec changes over one sprawling change.
- Tasks must be ordered for a junior developer or implementation agent: setup/contracts first, data model/API next, behavior/UI next, tests/docs/migration last.
- Every task should be independently verifiable and completeable in one focused session. Avoid tasks like "build the whole feature".
- Architecture guidance must address module boundaries, data ownership, external dependencies, scaling path, observability, security, failure modes, and rollback when relevant.
- After artifacts are written, a reviewer must compare them against the user's agreed intent. If anything does not match, is missing, or expands scope, inform the user and ask how to proceed with concrete suggestions. Do not silently treat mismatches as approved.
