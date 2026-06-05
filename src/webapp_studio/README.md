# Webapp Studio

`webapp_studio` is the proposed next-generation replacement for `src/webapp`.
The existing app is a small Python-served static conversation room. This new
surface is scoped as a FastAPI backend API app managed with `uv` plus a Next.js,
shadcn/ui, Tailwind and AI Elements frontend: public conversation, agent
activity, tool traces, files, approvals, queues, history, and generated UI in
one coherent local studio.

This directory now contains the project scope plus the first implementation
slices: Pydantic contracts, shared JSON fixtures, a FastAPI backend shell, typed
compatibility controller methods, SSE stream-buffer primitives, a fixture-backed
Next.js studio frontend, and a local two-process development launcher.

One-command local studio launch:

```bash
uv run webapp-studio --port 8765 --frontend-port 3765
```

The launcher discovers Studio conversation teams from the current working
directory and the built-in repository teams, starts the FastAPI backend first,
waits for `/health`, then starts the Next.js frontend with
`STUDIO_API_BASE_URL` pointed at the backend.

The explicit team launch remains available for compatibility and debugging:

```bash
uv run webapp-studio team.yaml --thread-id existing-thread --port 8765 --frontend-port 3765
```

The launcher preserves the current webapp CLI arguments: optional `team.yaml`,
`--thread-id`, `--host`, `--port`, `--var`, `--config`, API-key overrides, and
env-file controls.

Current backend command shape:

```bash
uv run python -m src.webapp_studio.backend.server --port 8765
```

Start with [PROJECT_PLAN.md](PROJECT_PLAN.md).
