# OpenSpec Studio Developer Experience

This team is designed for Studio chat first, not for one-shot batch generation.
The user should be able to open the studio from the project they want to shape,
talk to `openspec-guide`, and let the team gradually turn a product idea into
small OpenSpec changes that a junior developer or coding agent can implement in
order.

## Launch Model

Run the studio from the target project root so `working_directory: "."` resolves
to the project that should receive OpenSpec files:

```bash
uv run webapp-studio /Users/mickael/Documents/github/coding-agents/teams/openspec/team.yaml --thread-id openspec
```

The team owns the target project workspace. On the first substantive turn it
must ensure OpenSpec is initialized in that target project with Codex support:

```bash
openspec init . --tools codex --force --profile core
```

If `openspec/config.yaml` already exists but the Codex OpenSpec skills are
missing, stale, or incomplete, the team refreshes generated instructions with:

```bash
openspec update . --force
```

The expected target-project instruction files are:

- `.codex/skills/openspec-explore/SKILL.md`
- `.codex/skills/openspec-propose/SKILL.md`
- `.codex/skills/openspec-apply-change/SKILL.md`
- `.codex/skills/openspec-archive-change/SKILL.md`

The user should not need to install or copy those files manually. The
conversation team creates or refreshes them as part of preparing the target
project for the OpenSpec flow.

## Conversation Experience

The default chat target is `openspec-guide`. The user can speak naturally:

- "I want to build a customer health scoring platform."
- "Make this more enterprise-ready."
- "Turn the current agreement into a change."
- "Review whether the written spec matches what we discussed."

The guide should first make the idea sharper: users, jobs, scope, non-goals,
technical constraints, risks, and success criteria. It asks decision-critical
questions when needed, but makes conservative assumptions when the request is
clear enough to proceed. The conversation should feel like a product and
architecture working session, not a form-filling wizard.

## Change Generation Rhythm

The guide may create changes at the end of discovery or periodically when a
coherent implementation slice has emerged. It should not wait for a complete
company roadmap. It should split oversized ideas into multiple OpenSpec changes
and generate the next smallest useful change.

For each change:

1. Create or select a kebab-case change name.
2. Use `openspec status --change <name> --json` for artifact state.
3. Use `openspec instructions <artifact> --change <name> --json` before writing
   each artifact.
4. Write `proposal.md`, specs, `design.md`, then `tasks.md` according to
   OpenSpec dependency state.
5. Run `openspec validate <name> --type change --strict --json`.
6. Ask `change-reviewer` to compare the files against the agreed conversation.

The guide must not declare a change ready until OpenSpec validation passes and
the reviewer returns `Approved`.

## Agent Responsibilities

`openspec-guide` is the Studio-facing facilitator. It owns conversation flow,
target-project OpenSpec initialization, scope slicing, agent delegation, and the
final readiness report.

`product-strategist` is a resident advisor for users, workflows, product
outcomes, edge cases, acceptance criteria, and non-goals. It helps the guide
elaborate vague ideas and avoid building the wrong slice.

`architecture-advisor` is a resident advisor for module boundaries, data
ownership, APIs, security, reliability, observability, scaling path,
dependencies, migration, and rollback. It keeps the specification technically
implementable without overengineering the first change.

`change-writer` is a disposable subagent that writes or revises OpenSpec
artifacts from the guide's explicit brief. It follows OpenSpec instructions and
does not invent scope.

`change-reviewer` is the alignment gate. It reads the artifacts, runs OpenSpec
status and strict validation, checks whether the content matches the user's
agreed intent, and returns `Approved`, `Needs User Decision`, or `Blocked`.
Anything that changes scope or contradicts the conversation must go back to the
user with options.

## Readiness Bar

A generated change is ready only when the target project contains OpenSpec and
Codex OpenSpec skills, all required artifacts are done, strict validation has no
issues, tasks are small and ordered, and the reviewer approved alignment with
the conversation.
