"use client"

import { ActivityPanel } from "@/components/studio/activity-panel"
import type { StudioState } from "@/lib/studio/schemas"

const focusedAgentId = "engineering-manager"

const studioState: StudioState = {
  team_id: "software",
  conversation_id: "thread_temp_agent_history",
  participants: [
    "engineering-manager",
    "product-analyst",
    "software-architect",
    "developer",
    "qa-engineer",
  ],
  participant_aliases: {
    "engineering-manager": ["manager", "lead"],
    "product-analyst": ["product"],
    "software-architect": ["architect"],
    "qa-engineer": ["qa"],
  },
  runtime: {
    team_id: "software",
    conversation_id: "thread_temp_agent_history",
    mention_hook_enabled: true,
    max_cascade_turns: null,
  },
  conversation: {
    events: [
      {
        id: "event_human_01",
        team_id: "software",
        conversation_id: "thread_temp_agent_history",
        branch_id: "branch_main",
        logical_message_id: "event_human_01",
        version_parent_event_id: null,
        parent_event_id: null,
        frontier_before_event_id: null,
        frontier_after_event_id: "frontier_event_human_01_after",
        seq: 1,
        created_at: "2026-06-03T09:14:11Z",
        author_id: "human",
        author_kind: "human",
        content:
          "@engineering-manager Create an isolated fake agent history page for improving the Studio activity view.",
        mentions: ["engineering-manager"],
        attachments: [],
        source_thread_id: null,
        source_message_id: null,
        metadata: {},
      },
      {
        id: "event_agent_02",
        team_id: "software",
        conversation_id: "thread_temp_agent_history",
        branch_id: "branch_main",
        logical_message_id: "event_agent_02",
        version_parent_event_id: null,
        parent_event_id: "event_human_01",
        frontier_before_event_id: "frontier_event_human_01_after",
        frontier_after_event_id: "frontier_event_agent_02_after",
        seq: 2,
        created_at: "2026-06-03T09:16:44Z",
        author_id: "engineering-manager",
        author_kind: "agent",
        content:
          "The temporary history route is ready and isolated around the Studio activity renderer.",
        mentions: [],
        attachments: [],
        source_thread_id:
          "thread_temp_agent_history:mention:engineering-manager",
        source_message_id: "msg_final_01",
        metadata: {},
      },
    ],
    deliveries: [
      {
        id: "delivery_engineering_manager",
        team_id: "software",
        conversation_id: "thread_temp_agent_history",
        branch_id: "branch_main",
        agent_id: "engineering-manager",
        run_id: "run_temp_history_01",
        snapshot_seq: 1,
        status: "success",
        created_at: "2026-06-03T09:14:12Z",
        completed_at: "2026-06-03T09:16:44Z",
        error: null,
      },
    ],
    agent_states: [
      {
        team_id: "software",
        conversation_id: "thread_temp_agent_history",
        branch_id: "branch_main",
        agent_id: "engineering-manager",
        last_delivered_seq: 2,
        running: false,
        queued: false,
        queued_after_seq: null,
        current_run_id: null,
        current_snapshot_seq: 1,
        stop_requested: false,
        last_identity_refresh_seq: 0,
        token_estimate_since_identity_refresh: 2840,
      },
      {
        team_id: "software",
        conversation_id: "thread_temp_agent_history",
        branch_id: "branch_main",
        agent_id: "qa-engineer",
        last_delivered_seq: 1,
        running: false,
        queued: false,
        queued_after_seq: null,
        current_run_id: null,
        current_snapshot_seq: null,
        stop_requested: false,
        last_identity_refresh_seq: 0,
        token_estimate_since_identity_refresh: 620,
      },
    ],
    branch_threads: [],
    thread_frontiers: [],
    control_events: [],
    external_side_effects: [],
    runs: [],
  },
  activity: {
    active_agent_ids: [],
    private_threads: [
      {
        agent_id: "engineering-manager",
        thread_id: "thread_temp_agent_history:mention:engineering-manager",
        last_activity_at: "2026-06-03T09:16:44Z",
        messages: [
          {
            type: "system",
            name: null,
            created_at: "2026-06-04T07:14:12Z",
            content:
              "You are engineering-manager. Coordinate resident agents, use tools when useful, and keep public replies short.",
            tool_calls: [],
          },
          {
            type: "human",
            name: "human",
            created_at: "2026-06-04T07:14:22Z",
            content:
              "@engineering-manager Create an isolated fake agent history page for improving the Studio activity view.",
            tool_calls: [],
          },
          {
            type: "thinking",
            name: "engineering-manager",
            created_at: "2026-06-04T07:14:38Z",
            content:
              "Simulated thinking tokens: `think_001 route-scope`, `think_002 inspect-router`, `think_003 map-tools`, `think_004 delegate`, `think_005 verify`, `think_006 final`.",
            tool_calls: [],
          },
          {
            type: "ai",
            name: "engineering-manager",
            created_at: "2026-06-04T07:15:05Z",
            content:
              "Collecting context with every available software-team tool.",
            tool_calls: [
              {
                id: "call_web_search",
                name: "web_search",
                input: { query: "Next.js App Router page route" },
                output: "Found App Router route guidance for page.tsx.",
              },
              {
                id: "call_fetch_url",
                name: "fetch_url",
                input: { url: "https://docs.local/next/app/page" },
                output: "Fetched routing reference and cache notes.",
              },
              {
                id: "call_ls",
                name: "ls",
                input: { path: "src/webapp_studio/frontend/app" },
                output:
                  "app/layout.tsx\napp/page.tsx\napp/globals.css\napp/error.tsx",
              },
              {
                id: "call_read_file",
                name: "read_file",
                input: { path: "app/page.tsx" },
                output:
                  "The Studio page renders fixtures when no API base URL is set.",
              },
              {
                id: "call_glob",
                name: "glob",
                input: { pattern: "components/studio/*.tsx" },
                output:
                  "components/studio/activity-panel.tsx\ncomponents/studio/right-inspector.tsx\ncomponents/studio/tool-call-list.tsx",
              },
              {
                id: "call_grep",
                name: "grep",
                input: { pattern: "Agent activity history" },
                output:
                  "components/studio/activity-panel.tsx renders the focused agent history.",
              },
              {
                id: "call_write_file",
                name: "write_file",
                input: { path: "app/temp-agent-history/page.tsx" },
                output: "Created the temporary isolated route.",
              },
              {
                id: "call_edit_file",
                name: "edit_file",
                input: { path: "app/temp-agent-history/page.tsx" },
                output:
                  "Replaced the bespoke demo UI with the real ActivityPanel renderer.",
              },
              {
                id: "call_execute",
                name: "execute",
                input: {
                  command:
                    "pnpm exec eslint app/temp-agent-history/page.tsx && pnpm exec tsc --noEmit --pretty false",
                },
                output: "Targeted lint and typecheck completed successfully.",
              },
              {
                id: "call_product",
                name: "ask_product_analyst",
                input: {
                  message:
                    "What should this isolated history prove for the product flow?",
                },
                output:
                  "It should make the agent-private activity readable without the rest of the workspace.",
              },
              {
                id: "call_architect",
                name: "ask_software_architect",
                input: {
                  message:
                    "Where should the temporary page live, and how should it be removed later?",
                },
                output:
                  "Keep it in one App Router segment so cleanup is a single directory removal.",
              },
              {
                id: "call_qa",
                name: "ask_qa_engineer",
                input: {
                  message: "How should the isolated page be validated?",
                },
                output:
                  "Run lint, typecheck, and inspect the route with a browser screenshot.",
              },
            ],
          },
          {
            type: "ai",
            name: "engineering-manager",
            created_at: "2026-06-04T07:15:49Z",
            content:
              "Dispatching subagents through the same activity history stream.",
            tool_calls: [
              {
                id: "task_scout",
                name: "task",
                input: {
                  subagent_type: "scout",
                  description:
                    "Map the current Studio route and activity files.",
                },
                output:
                  "The ActivityPanel is the exact renderer used inside the right inspector.",
              },
              {
                id: "task_developer",
                name: "task",
                input: {
                  subagent_type: "developer",
                  description:
                    "Build the temporary route around the existing component.",
                },
                output:
                  "The route now mounts ActivityPanel with focusedAgentId set.",
              },
              {
                id: "task_code_reviewer",
                name: "task",
                input: {
                  subagent_type: "code-reviewer",
                  description: "Check that the blast radius stays temporary.",
                },
                output:
                  "Only app/temp-agent-history/page.tsx is part of this change.",
              },
              {
                id: "task_qa",
                name: "task",
                input: {
                  subagent_type: "qa-engineer",
                  description: "Verify visual rendering and compile checks.",
                },
                output:
                  "The isolated page renders the Studio activity history shape.",
              },
              {
                id: "task_devops",
                name: "task",
                input: {
                  subagent_type: "devops-engineer",
                  description: "Confirm the local route URL.",
                },
                output:
                  "The page is available at /temp-agent-history on the Studio dev server.",
              },
              {
                id: "task_security",
                name: "task",
                input: {
                  subagent_type: "security-reviewer",
                  description: "Review fake trace content.",
                },
                output:
                  "The thinking tokens are synthetic labels, not real chain-of-thought.",
              },
              {
                id: "task_writer",
                name: "task",
                input: {
                  subagent_type: "technical-writer",
                  description: "Summarize the final user-facing message.",
                },
                output:
                  "The final message states the route is ready for improving the activity view.",
              },
            ],
          },
          {
            type: "ai",
            name: "engineering-manager",
            created_at: "2026-06-04T07:16:44Z",
            content: [
              "## Final message",
              "",
              "The temporary page now isolates the same agent history renderer used by Studio, centered on its own route.",
              "",
              "### Highlights",
              "",
              "- Human messages stay aligned to the right.",
              "- Tool calls remain collapsed by default.",
              "- Final answers can render **Markdown** with inline `code`, lists, tables, quotes, links, and fenced blocks.",
              "",
              "> A final response should be readable at a glance, then carry enough structure for careful review.",
              "",
              "### Shell commands",
              "",
              "```bash",
              "cd src/webapp_studio/frontend",
              "pnpm exec vitest run components/studio/rich-rendering.test.tsx",
              "pnpm exec tsc --noEmit --pretty false",
              "```",
              "",
              "### Code sample",
              "",
              "```tsx",
              "export function FinalMessageExample({ content }: { content: string }) {",
              "  return <RichMarkdown content={content} />",
              "}",
              "```",
              "",
              "### Checklist",
              "",
              "- [x] Isolated activity route",
              "- [x] Dense tool-call groups",
              "- [x] Hover actions for human and AI messages",
              "- [ ] Polish final Markdown rendering",
              "",
              "### Results",
              "",
              "| Area | Status | Note |",
              "| --- | --- | --- |",
              "| Layout | Ready | Centered activity history |",
              "| Actions | Ready | Copy for AI, edit for human |",
              "| Markdown | Review | This fixture exercises the final renderer |",
              "",
              "Useful reference: [Markdown Guide](https://www.markdownguide.org/basic-syntax/).",
            ].join("\n"),
            tool_calls: [],
          },
        ],
      },
    ],
  },
  runs: [
    {
      id: "run_temp_history_01",
      conversation_id: "thread_temp_agent_history",
      agent_id: "engineering-manager",
      status: "completed",
      created_at: "2026-06-03T09:14:12Z",
      updated_at: "2026-06-03T09:16:44Z",
      completed_at: "2026-06-03T09:16:44Z",
      checkpoint_id: "checkpoint_temp_history_01",
      cursor: "event_seq:2",
      metadata: { current_snapshot_seq: 1 },
    },
  ],
  queue: [],
  interrupts: [],
  history: {
    current_branch_id: "branch_main",
    checkpoints: [
      {
        id: "checkpoint_temp_history_01",
        thread_id: "thread_temp_agent_history:mention:engineering-manager",
        checkpoint_ns: "",
        parent_checkpoint_id: null,
        seq: 1,
        created_at: "2026-06-03T09:16:44Z",
        source: "fake_studio_fixture",
        metadata: { target_agent_id: "engineering-manager" },
        summary: {
          message_count: 7,
          tool_call_count: 19,
          agent_id: "engineering-manager",
        },
        capabilities: {
          inspect: "available",
          resume: "unsupported",
          branch_from_here: "unsupported",
        },
      },
    ],
    branches: [
      {
        id: "branch_main",
        label: "Main",
        parent_branch_id: null,
        origin_checkpoint_id: null,
        origin_event_id: null,
        origin_logical_message_id: null,
        origin_previous_event_id: null,
        origin_event_seq: null,
        created_at: "2026-06-03T09:14:11Z",
        current: true,
        status: "derived",
        head_checkpoint_id: "checkpoint_temp_history_01",
      },
    ],
  },
  ui_state: {
    team_id: "software",
    conversation_id: "thread_temp_agent_history",
    branch_id: "branch_main",
    participant_id: "human",
    draft_content: "",
    outbox_state: [],
    editing_event_id: null,
    selected_agent_id: null,
    scroll_anchor_event_id: null,
    updated_at: "2026-06-03T09:14:11Z",
  },
  generated_ui: [],
}

export default function Page() {
  return (
    <main className="min-h-screen bg-muted/30 px-4 py-8">
      <div className="mx-auto w-full max-w-xl rounded-md border bg-background p-3 shadow-sm">
        <ActivityPanel
          focusedAgentId={focusedAgentId}
          onAgentSelect={() => undefined}
          onBack={() => undefined}
          state={studioState}
        />
      </div>
    </main>
  )
}
