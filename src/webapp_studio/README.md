# Webapp Studio

`webapp_studio` is the proposed next-generation replacement for `src/webapp`.
The existing app is a small Python-served static conversation room. This new
surface is scoped as a FastAPI backend API app managed with `uv` plus a Next.js,
shadcn/ui, Tailwind and AI Elements frontend: public conversation, agent
activity, tool traces, files, approvals, queues, history, and generated UI in
one coherent local studio.

This directory currently contains the project scope and implementation plan.
No runtime behavior has been changed yet.

Start with [PROJECT_PLAN.md](PROJECT_PLAN.md).
