# coding-agents

A reusable Python module and minimal CLI for a development-agent team built on
LangChain Deep Agents.

## V0 scope

- `engineering-manager` as the main Deep Agent
- resident product and architecture agents with checkpointed thread memory
- `scout` subagent for fast codebase reconnaissance before status/progress
  answers
- specialist subagents for development, review, QA, DevOps, security, and
  documentation after readiness approval
- web tools powered by Tavily: `web_search` and `fetch_url`
- shaping mode by default
- implementation mode only after readiness approval
- workflow artifacts in `docs/agent-workflow/`
- versioned files plus checkpointed thread state for V0 memory

Resident product and architecture memory survives CLI restarts through the local
SQLite LangGraph checkpointer by default. A Postgres checkpointer adapter is also
available for shared deployments, and an in-memory backend is available for tests
or disposable sessions.

See [Development Agent Team Architecture](docs/development-agent-team-architecture.md)
for the full specification.

## Runtime support

V0 supports Python `>=3.11,<4.0`. The CI matrix validates Python 3.11, 3.12,
3.13, and 3.14. The local `.python-version` is `3.11` so contributor defaults
exercise the supported floor.

## Installation and setup

Install locked dependencies with `uv`:

```bash
uv sync --locked
```

Set a model API key before starting the interactive agent. Set `TAVILY_API_KEY`
when you want the web tools to work:

```bash
export OPENAI_API_KEY="..."
export TAVILY_API_KEY="..."  # optional until web tools are used
```

Start the CLI through the package script:

```bash
uv run coding-agents
```

The legacy launcher is also available:

```bash
uv run python main.py
```

## Configuration

You can configure defaults in `.env` or through CLI flags:

```bash
CODING_AGENTS_MODEL=openai:gpt-5.5
CODING_AGENTS_REASONING_EFFORT=xhigh
CODING_AGENTS_SCOUT_MODEL=openai:gpt-5.5
CODING_AGENTS_SCOUT_REASONING_EFFORT=medium
CODING_AGENTS_CHECKPOINTER=sqlite
CODING_AGENTS_SQLITE_CHECKPOINT_PATH=.coding-agents/checkpoints.sqlite
CODING_AGENTS_EXECUTION=none
```

When an OpenAI model is used with `CODING_AGENTS_REASONING_EFFORT`, the module
uses the OpenAI Responses API and requests reasoning summaries with
`reasoning.summary=auto` so reasoning and function tools can work together and
summaries can be persisted in checkpointed messages.

### Checkpointers

SQLite is the default local backend:

```bash
uv run coding-agents --checkpointer sqlite
```

Use memory for disposable smoke tests or local experiments:

```bash
uv run coding-agents --checkpointer memory
```

Postgres checkpointing is available when needed:

```bash
CODING_AGENTS_CHECKPOINTER=postgres
CODING_AGENTS_POSTGRES_URL=postgresql://user:password@host:5432/dbname
uv run coding-agents --checkpointer postgres
```

### Threads

Use the same thread id to continue a previous conversation. The CLI restores the
visible user/manager transcript before showing the next prompt:

```bash
uv run coding-agents --thread-id feature-shaping
```

### Model and reasoning overrides

```bash
uv run coding-agents --model openai:gpt-5.4
uv run coding-agents --reasoning-effort xhigh
uv run coding-agents --scout-reasoning-effort medium
```

## CLI workflow

Initialize workflow artifacts without starting the agent:

```bash
uv run coding-agents --init-only
```

By default the CLI starts in shaping mode:

```bash
uv run coding-agents --mode shaping
```

Use implementation mode only after `docs/agent-workflow/readiness-gate.yaml`
records full implementation approval:

```bash
uv run coding-agents --mode implementation
```

The CLI prompt is a safe interactive smoke path in shaping mode and does not
require implementation-mode approval. Type `/help` for commands and `/exit` or
`/quit` to stop.

## Execution and write boundaries

Shaping and implementation modes use local command execution by default for
trusted runs:

```bash
uv run coding-agents --mode shaping
uv run coding-agents --mode implementation
```

Disable local command execution when you want a read/write-only session:

```bash
uv run coding-agents --mode shaping --execution none
uv run coding-agents --mode implementation --execution none
```

Local execution exposes Deep Agents' `execute` tool to the engineering-manager
graph. In implementation mode it also exposes `execute` to implementation
specialists. Commands run on this machine with the current user's environment and
permissions; filesystem permissions do not sandbox shell commands. Shell output
is best-effort redacted before it is returned to the agent.

Implementation mode has repo-wide filesystem write access by default after
readiness approval, except for protected files such as the machine-readable
readiness gate and common secret-like paths. Use repeated `--write-path`
arguments only when you want to restrict an implementation run to specific files
or directories:

```bash
uv run coding-agents --mode implementation --write-path coding_agents/ --write-path tests/
```

Scout and resident product/architecture agents remain without general shell
execution. Scout uses scoped read tools and Python literal grep.

## Tests, packaging, and CI

Run the full local unit suite:

```bash
uv run python -m unittest discover -s tests
```

Run the suite against a specific supported Python version:

```bash
uv run --python 3.11 python -m unittest discover -s tests
uv run --python 3.14 python -m unittest discover -s tests
```

Build the wheel:

```bash
uv build --wheel --out-dir dist
```

GitHub Actions CI is defined in `.github/workflows/ci.yml`. It runs on pushes and
pull requests, validates Python 3.11 through 3.14, runs the unit suite, builds the
wheel, installs it in a clean environment, and runs `coding-agents --init-only` as
a CLI smoke check.

## Python API

The V0 first-party API surface is intentionally small:

```python
from coding_agents import AgentTeamConfig, create_development_team_agent

with create_development_team_agent(
    AgentTeamConfig(
        model="openai:gpt-5.5",
        mode="shaping",
        checkpointer_backend="sqlite",
    )
) as agent:
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Shape a new feature"}]},
        config={"configurable": {"thread_id": "feature-shaping"}},
    )
```

## Limitations

- V0 is for local/repository use. It is not a production service or external SDK.
- Do not claim production readiness from local validation alone; use the CI results
  and workflow artifacts as release evidence.
- Local shell execution is intentionally powerful. Use `--execution none` when a
  run must not execute commands.
- Tavily `fetch_url` sends requested URLs and extraction queries to Tavily; avoid
  using it with private URLs or sensitive content unless that is acceptable.
- Secret-file blocking and output redaction are best-effort safeguards, not a
  replacement for avoiding secret reads or secret-printing commands.
