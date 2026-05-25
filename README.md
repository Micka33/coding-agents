# coding-agents

A reusable Python module and minimal CLI for a development-agent team built on
LangChain Deep Agents.

## V0 Scope

- `engineering-manager` as the main Deep Agent
- resident product and architecture agents with SQLite-backed thread memory
- `scout` subagent for fast codebase reconnaissance before status/progress
  answers
- specialist subagents for development, review, QA, DevOps, security, and
  documentation
- web tools powered by Tavily: `web_search` and `fetch_url`
- shaping mode by default
- implementation mode only after readiness approval
- workflow artifacts in `docs/agent-workflow/`
- versioned files plus SQLite checkpointed thread state for V0 memory

Resident product and architecture memory survives CLI restarts through a local
SQLite LangGraph checkpointer. A Postgres checkpointer adapter is also installed
and can be selected for shared or production deployments.

See [Development Agent Team Architecture](docs/development-agent-team-architecture.md)
for the full specification.

## Usage

Set a model API key, then start the CLI:

```bash
export OPENAI_API_KEY="..."
export TAVILY_API_KEY="..."
uv run python main.py
```

You can also configure the model in `.env`:

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

Postgres checkpointing is available when needed:

```bash
CODING_AGENTS_CHECKPOINTER=postgres
CODING_AGENTS_POSTGRES_URL=postgresql://user:password@host:5432/dbname
```

Or use the project script:

```bash
uv run coding-agents
```

The CLI supports multi-line prompts: press `Enter` to add a line, then
`Esc+Enter` to submit.

Use the same thread id to continue a previous conversation. The CLI restores
the visible user/manager transcript before showing the next prompt:

```bash
uv run coding-agents --thread-id feature-shaping
```

Optional model override:

```bash
uv run python main.py --model openai:gpt-5.4
```

Optional reasoning override:

```bash
uv run python main.py --reasoning-effort xhigh
uv run python main.py --scout-reasoning-effort medium
```

Optional checkpointer override:

```bash
uv run python main.py --checkpointer sqlite
uv run python main.py --checkpointer postgres --postgres-checkpoint-url postgresql://...
```

Initialize workflow artifacts without starting the agent:

```bash
uv run python main.py --init-only
```

Use implementation mode only after the readiness gate has been approved:

```bash
uv run python main.py --mode implementation
```

Shaping mode enables local command execution for trusted validation runs by
default:

```bash
uv run python main.py --mode shaping
```

Implementation mode also enables local command execution by default after
readiness approval:

```bash
uv run python main.py --mode implementation
```

Disable local command execution when you want a read/write-only session:

```bash
uv run python main.py --mode shaping --execution none
uv run python main.py --mode implementation --execution none
```

Local execution exposes Deep Agents' `execute` tool to the engineering-manager
graph. In implementation mode it also exposes `execute` to implementation
specialists. In shaping mode, execution is for validation, diagnostics, and
evidence gathering only. Commands run on this machine with the current user's
environment and permissions while filesystem writes remain governed by mode
permissions. Implementation mode has repo-wide write access by default after
readiness approval, except for protected files such as the machine-readable
readiness gate and secret-like paths. Use repeated `--write-path` arguments only
when you want to restrict an implementation run to specific files or directories.
Scout and resident product/architecture agents remain without general shell
execution.

## Python API

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
