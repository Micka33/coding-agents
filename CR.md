Code review complete. Reviewers ran across two waves (the second wave + all validators on opus-4.8); 8/8 P0/P1 findings were independently validated against the code.

## Code Review Results

**Scope:** working tree vs HEAD `e6ecf90` (`main`) — 13 modified + 16 new files, ~3.3k lines (new `src/team_packages/**`, `tests/team_packages/**`, `docs/team-package-sharing.md` in scope).
**Intent:** MVP slices 1-7 of `docs/team-package-sharing.md`.
**Mode:** interactive; pre-review tree was dirty, so fixes were applied but not committed.

The design doc is the contract — several P0/P1s are direct violations of its own security promises.

### Applied (safe, verified)

| #   | File                                            | Fix                                                        | Reviewer                           |
| --- | ----------------------------------------------- | ---------------------------------------------------------- | ---------------------------------- |
| A1  | `src/team_packages/installer.py:164`            | Removed unused `installed_path` param from `_team_entries` | maintainability                    |
| A2  | `tests/team_packages/test_team_packages.py:200` | Hoisted inline `import shutil` to module top               | maintainability, project-standards |

Validation: targeted tests green; ruff/pyright clean. Not committed (tree was dirty).

### P0 -- Critical

| #   | File                       | Issue                                                                 | Reviewer                           | Confidence |
| --- | -------------------------- | --------------------------------------------------------------------- | ---------------------------------- | ---------- |
| 1   | `team_instanciator.py:154` | Trust gate reads risk_flags/integrity from lockfile, never re-derives | security, correctness, adversarial | 100        |
| 2   | `installer.py:85`          | `uninstall` rmtrees lockfile `installed_path` with no containment     | adversarial                        | 100        |
| 3   | `installer.py:140`         | Unvalidated skill `id` -> path traversal in rmtree/copytree           | security                           | 75         |
| 4   | `installer.py:93`          | `git clone` of `git:` source, no scheme allowlist -> ext:: RCE        | security                           | 75         |

- **#1** — `_enforce_package_trust` reads `risk_flags`/`integrity` straight from `team-lock.json` and early-returns when risk_flags is empty. A committed lockfile declaring `risk_flags: []` for a shell/`custom_tools`/MCP package instantiates with **no trust prompt**; integrity is never recomputed from disk. Fix: re-derive flags via `PackageRiskScanner` and recompute `ContentHasher` at the gate, fail closed on mismatch.
- **#2** — `absolute_path("")` resolves to the workspace root, `"/"` passes through, `".."` escapes; both `uninstall()` and `_remove_unused_skill_dependencies()` rmtree it with only an `.exists()` check. A crafted lockfile + `team uninstall <name>` deletes arbitrary directories. Fix: recompute from the validated name or assert containment under `.coding-agents/packages`/`/skills`.
- **#3** — skill `id` is validated only as non-empty; `id: ../../x` escapes `.coding-agents/skills` via `_replace_tree` on install of a malicious package. Fix: charset-validate ids and assert containment.
- **#4** — `repo_url` reaches `git clone` with no allowlist/`--`; `git clone "ext::sh -c <cmd>"` is RCE, and `team update` replays the source from the committed lockfile. Fix: allowlist schemes, reject `::`/leading `-`, set `protocol.ext.allow=never`, add `--`.

### P1 -- High

| #   | File                        | Issue                                                                   | Reviewer    | Confidence |
| --- | --------------------------- | ----------------------------------------------------------------------- | ----------- | ---------- |
| 5   | `test_team_packages.py:259` | CLI test writes to real `~/.codex` trust store                          | testing     | 100        |
| 6   | `installer.py:39`           | `install()` mutates disk before lockfile write -> desync/clobber        | reliability | 75         |
| 7   | `lockfile_store.py:30`      | Corrupt `team-lock.json` silently reset -> next write drops all entries | reliability | 75         |
| 8   | `risk_scanner.py:20`        | Shell flag keys on toolset name "shell", not on exposing `execute`      | security    | 75         |

- **#5** — the lifecycle test builds `TeamPackageCli` with no `CODEX_HOME`, so `team trust` writes `acme/software-team` into the dev's real `~/.codex/.../trust.json` (it did during this review). Fix: `patch.dict(os.environ, {"CODEX_HOME": ...})`.
- **#8** — `_shell_can_resolve_to_local` checks for a toolset _named_ `shell`; the design defines the flag as "a toolset exposes `execute`", so a renamed toolset evades the flag (validator confirmed the langchain subagent path builds a real `subprocess.run(shell=True)` tool regardless).

### P2 -- Moderate

| #   | File                               | Issue                                                                                 | Reviewer                                         | Confidence |
| --- | ---------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------ | ---------- |
| 9   | `team_discovery_service.py:34`     | `lock_status: missing` descriptor filtered out by `conversation_available`            | correctness, adversarial, api-contract, testing  | 100        |
| 10  | `server.py:70`                     | `TeamInstanciatorError` (trust gate) -> unhandled 500; escape hatch unreachable in UI | ce-agent-native                                  | 75         |
| 11  | `skill_source_resolver.py:94`      | `allowed_skill_ids` enforced inconsistently across methods                            | maintainability                                  | 75         |
| 12  | `cli.py:31`                        | Catches only `TeamPackageError`; `OSError`/`TeamLoaderError` leak as tracebacks       | reliability                                      | 75         |
| 13  | `installer.py:106`                 | `_split_git_source` drops refs containing `/` (branches, nested tags)                 | adversarial                                      | 75         |
| 14  | `installer.py:140`                 | Shared skill store id-keyed; same-id deps clobber across packages                     | reliability                                      | 75         |
| 15  | `lockfile_store.py:39`             | Lockfile entries untyped `JsonObject`; shape parsing duplicated 6+ sites              | maintainability                                  | 75         |
| 16  | `trust_store.py:21`                | `trust.json` path resolved differently by gate / `team trust` / discovery             | correctness, api-contract, maintainability       | 75         |
| 17  | `team_discovery_service.py:43`     | Package can evict builtin/project team via colliding lockfile id                      | adversarial                                      | 75         |
| 18  | `team_discovery_service.py:171`    | Package trust/risk/missing-env metadata unrendered + untyped in frontend              | ce-agent-native, project-standards, api-contract | 75         |
| 19  | `studio_backend_launcher.py:33`    | Prints blocking "discovery failed" even on `ready` startups                           | api-contract                                     | 75         |
| 20  | `studio_session_controller.py:278` | Colliding explicit team file activates under synthetic id                             | api-contract                                     | 75         |
| 21  | `studio-workspace.tsx:497`         | New banner + `package` source ship with zero frontend tests                           | project-standards, testing                       | 75         |

- **#9** — `_missing_package_descriptor` hardcodes `conversation_available=False` but `discover()` filters on it, so the documented `missing` state never reaches Studio (the helper is dead). **#10** — the trust error is a plain `Exception` with no Studio handler, so the `team trust` instruction is swallowed by a 500. **#16** — gate honours `--config CODEX_HOME` while `team trust` uses env/`~/.codex`, so they can read/write different files. **#17/#18** — package-declared ids can evict builtins, and the promised Studio env/trust warnings are API-only.

### P3 -- Low

| #   | File                            | Issue                                                  | Reviewer                      | Confidence |
| --- | ------------------------------- | ------------------------------------------------------ | ----------------------------- | ---------- |
| 22  | `team_discovery_service.py:106` | `**package` spread silently overrides parsed `team_id` | maintainability, api-contract | 75         |

### Design conformance vs the doc

- **Violated:** risk flags re-derived/never author-declared (#1, #8); changed hash invalidates trust (#1, never recomputed at runtime); `lock_status: missing` surfaced in UI (#9); `requires.env` warnings in Studio UI (#18); "no colliding team wins by priority" (#17).
- **Honored:** lockfile-driven discovery (no globbing), trust never in `team-lock.json`, package skill layer restricted to locked ids, user-local trust store, no lifecycle scripts, `requires.env` never blocks.

### Coverage

- Suppressed to residual (anchor 50): spurious git version warning on SHA installs (`installer.py:230`), absolute non-home path leak into lockfile `source` (`installer.py:212`), `package_for_team_file` first-match (`package_locator.py:16`), non-atomic lockfile write, discovery raising on bad team.yaml, `GIT_TERMINAL_PROMPT` unset.
- Residual risks: copytree/hash dereference symlinks (host-file exfiltration); trust store never prunes old integrity entries; discovery never verifies integrity (tampered flag-free team lists `locked`).
- Learnings: no `docs/solutions/` knowledge base exists.

---

> **Verdict:** Not ready
>
> **Reasoning:** Four validated P0s — committed-lockfile trust bypass (#1), arbitrary directory deletion on uninstall (#2), skill-id path traversal on install (#3), and git ext:: RCE on install/update (#4) — defeat the package trust/integrity model that is this feature's security premise. The build is otherwise green at 100% Python line coverage and the CLI/agent surface is well-built.
>
> **Fix order:** P0 trust/integrity + path-containment + git allowlist (#1-#4) → P1 risk scanning, install atomicity, corrupt-lockfile, test hermeticity (#5-#8) → Studio surfacing + contracts (#9, #10, #16-#18).

Artifacts (per-reviewer JSON, validators, `report.md`, `metadata.json`, `actionable.json`) are in `/tmp/compound-engineering/ce-code-review/20260610-185803-450b41c9/`. The two applied fixes are uncommitted in your working tree alongside your in-flight work.
