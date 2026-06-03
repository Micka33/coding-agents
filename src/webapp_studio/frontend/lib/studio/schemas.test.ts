import { describe, expect, it } from "vitest"

import { StudioApiClient, normalizeStudioApiBaseUrl } from "@/lib/studio/api-client"
import { loadInitialStudioData } from "@/lib/studio/data-loader"
import { loadStudioMock, readFixture } from "@/lib/studio/fixtures"
import { studioReducer } from "@/lib/studio/reducer"
import {
  GeneratedUiSpecSchema,
  GeneratedUiPatchPayloadSchema,
  CheckpointResumeRequestSchema,
  QueueUpdatedPayloadSchema,
  StreamFramePayloadSchema,
  StudioEnvelopeSchema,
  StudioErrorSchema,
  StudioStateSchema,
} from "@/lib/studio/schemas"
import { toJsonRenderSpec } from "@/lib/studio/generated-ui"

const capabilities = {
  streaming: "available",
  queue_control: "degraded",
  interrupts: "degraded",
  checkpoints: "degraded",
  branching: "degraded",
  time_travel: "degraded",
  generated_ui: "degraded",
} as const

describe("studio fixture contracts", () => {
  it("validates shared backend fixtures in TypeScript", () => {
    const state = StudioStateSchema.parse(readFixture("studio_state.json"))

    expect(state.team_id).toBe("team")
    expect(state.history.checkpoints[0]?.source).toBe("langgraph_sqlite")
    expect(state.history.checkpoints[0]?.summary.agent_id).toBe("agent")
    expect(state.history.branches[0]?.head_checkpoint_id).toBe("checkpoint_01")
    expect(state.participant_aliases.agent).toEqual(["lead"])
    expect(state.conversation.events[0]?.metadata.generated_ui_ids).toEqual(["generated_ui_01"])
    expect(GeneratedUiSpecSchema.parse(readFixture("generated_ui_spec.json")).status).toBe("valid")
    expect(CheckpointResumeRequestSchema.parse(readFixture("checkpoint_resume_request.json")).mode).toBe("resume")
    expect(CheckpointResumeRequestSchema.parse(readFixture("checkpoint_resume_edit_request.json")).mode).toBe("edit")
    expect(CheckpointResumeRequestSchema.parse(readFixture("checkpoint_resume_regenerate_request.json")).mode).toBe("regenerate")
    expect(
      GeneratedUiPatchPayloadSchema.parse({
        spec_id: "generated_ui_01",
        patch: {
          op: "replace",
          path: "/root",
          value: "metric_01",
        },
      }).patch.op
    ).toBe("replace")
    expect(StudioErrorSchema.parse(readFixture("studio_error.json")).code).toBe("unsupported_feature")
    expect(StudioEnvelopeSchema(StudioStateSchema.partial()).parse(readFixture("studio_envelope.json")).schema_version).toBe("studio.v1")
    expect(StreamFramePayloadSchema.parse(readFixture("stream_frame.json")).cursor).toBe("event_seq:1")
    expect(QueueUpdatedPayloadSchema.parse({ items: state.queue }).items).toEqual(state.queue)
  })

  it("builds the mocked studio snapshot from shared fixtures", () => {
    const fixture = loadStudioMock()

    expect(fixture.state.generated_ui).toHaveLength(1)
    expect(fixture.generatedUi).toHaveLength(2)
    expect(fixture.liveApi).toBe(false)
  })

  it("accepts only generated UI catalog components", () => {
    const fixture = loadStudioMock()
    const invalidAction = GeneratedUiSpecSchema.parse({
      ...fixture.generatedUi[0],
      id: "generated_ui_unregistered_action",
      elements: {
        action_01: {
          component: "action",
          props: {
            label: "Unsafe action",
          },
          on: {
            press: {
              action: "unregistered_action",
            },
          },
        },
      },
      actions: {},
      root: "action_01",
    })

    const actionBinding = toJsonRenderSpec(fixture.generatedUi[0]).spec
      ?.elements.action_01.on?.press

    expect(toJsonRenderSpec(fixture.generatedUi[0]).spec?.root).toBe("stack_01")
    expect(actionBinding).toMatchObject({
      action: "open_task_details",
      confirm: {
        title: "Open task details?",
      },
    })
    expect(toJsonRenderSpec(fixture.generatedUi[1]).errors[0]).toContain("unknown-panel")
    expect(toJsonRenderSpec(invalidAction).errors[0]).toContain("not registered")
  })
})

describe("studio API loading", () => {
  it("normalizes launcher and API endpoint base URLs", () => {
    expect(normalizeStudioApiBaseUrl("http://127.0.0.1:8765")).toBe(
      "http://127.0.0.1:8765/api/studio/v1"
    )
    expect(normalizeStudioApiBaseUrl("http://127.0.0.1:8765/api/studio/v1/")).toBe(
      "http://127.0.0.1:8765/api/studio/v1"
    )
  })

  it("loads live state when STUDIO_API_BASE_URL is configured", async () => {
    const previousFetch = globalThis.fetch
    const previousApiBaseUrl = process.env.STUDIO_API_BASE_URL
    const state = StudioStateSchema.parse(readFixture("studio_state.json"))
    const response = {
      schema_version: "studio.v1",
      request_id: "req_test",
      capabilities,
      data: state,
      errors: [],
    }
    const requests: string[] = []

    globalThis.fetch = async (input) => {
      requests.push(String(input))
      return new Response(JSON.stringify(response), { status: 200 })
    }
    process.env.STUDIO_API_BASE_URL = "http://127.0.0.1:8765"

    try {
      const data = await loadInitialStudioData()

      expect(data.state.team_id).toBe("team")
      expect(data.generatedUi).toHaveLength(0)
      expect(data.liveApi).toBe(true)
      expect(requests).toEqual(["http://127.0.0.1:8765/api/studio/v1/state"])
    } finally {
      globalThis.fetch = previousFetch
      restoreStudioApiBaseUrl(previousApiBaseUrl)
    }
  })

  it("falls back to fixtures when STUDIO_API_BASE_URL is not configured", async () => {
    const previousApiBaseUrl = process.env.STUDIO_API_BASE_URL
    delete process.env.STUDIO_API_BASE_URL

    try {
      const data = await loadInitialStudioData()

      expect(data.generatedUi).toHaveLength(2)
    } finally {
      restoreStudioApiBaseUrl(previousApiBaseUrl)
    }
  })

  it("surfaces studio API errors from the envelope", async () => {
    const previousFetch = globalThis.fetch
    const error = {
      schema_version: "studio.v1",
      request_id: "req_error",
      capabilities,
      data: {},
      errors: [
        {
          code: "invalid_request",
          message: "bad request",
          field: null,
          retryable: false,
          details: {},
        },
      ],
    }

    globalThis.fetch = async () => new Response(JSON.stringify(error), { status: 400 })

    try {
      await expect(new StudioApiClient("http://127.0.0.1:8765/api/studio/v1").state()).rejects.toThrow(
        "bad request"
      )
    } finally {
      globalThis.fetch = previousFetch
    }
  })

  it("posts live mutations through the typed API client", async () => {
    const previousFetch = globalThis.fetch
    const state = StudioStateSchema.parse(readFixture("studio_state.json"))
    const appendResult = readFixture("append_message_result.json")
    const joinResult = {
      run_id: "run_01",
      cursor: "stream_00000001",
      replay_available: true,
      stream_url: "/api/studio/v1/stream?run_id=run_01",
    }
    const changesResult = {
      supported: true,
      changes: [
        {
          id: "change_1",
          path: "src/app.tsx",
          status: "modified",
          source: "git",
          agent_id: null,
          event_id: null,
          diff_url: "/api/studio/v1/changes/change_1/diff",
        },
      ],
    }
    const changeDiffResult = {
      change_id: "change_1",
      path: "src/app.tsx",
      diff: "@@ -1 +1 @@",
    }
    const terminalSession = {
      session_id: "term_1",
      cwd: "/tmp/project",
      status: "running",
      created_at: "2026-06-02T10:17:06Z",
      columns: 100,
      rows: 30,
    }
    const terminalOutput = {
      session_id: "term_1",
      cursor: 1,
      chunks: [{ cursor: 1, stream: "stdout", text: "ready\n" }],
      status: "running",
    }
    const requests: Array<{
      body: string | undefined
      method: string | undefined
      url: string
    }> = []

    globalThis.fetch = async (input, init) => {
      requests.push({
        body: typeof init?.body === "string" ? init.body : undefined,
        method: init?.method,
        url: String(input),
      })
      const url = String(input)
      const data = url.endsWith("/messages")
        ? appendResult
        : url.endsWith("/session/conversation")
          ? {
              session: {
                team_id: state.team_id,
                conversation_id: "thread-2",
                team_file: "/tmp/team.yaml",
                launcher_cwd: "/tmp/project",
                resolved_root_dir: "/tmp/project",
                checkpointer: {
                  backend: "memory",
                  sqlite_path: null,
                  storage_id: "memory:test-store",
                },
                loaded_at: "2026-06-02T10:17:06Z",
              },
              state,
            }
        : url.endsWith("/changes")
          ? changesResult
        : url.includes("/changes/")
          ? changeDiffResult
        : url.includes("/terminal/sessions/") && url.includes("/output")
          ? terminalOutput
        : url.includes("/terminal/sessions")
          ? terminalSession
        : url.includes("/runs/")
          ? joinResult
        : url.endsWith("/branches")
          ? state.history.branches[0]
          : url.includes("/branches/")
            ? state.history.branches
            : url.includes("/queue")
              ? []
              : url.includes("/interrupts/")
                ? state
                : state
      return new Response(
        JSON.stringify({
          schema_version: "studio.v1",
          request_id: "req_test",
          capabilities,
          data,
          errors: [],
        }),
        { status: 200 }
      )
    }

    try {
      const client = new StudioApiClient("http://127.0.0.1:8765/api/studio/v1")

      await client.appendMessage("@agent next")
      await client.appendMessage("@agent file", [
        {
          filename: "notes.txt",
          mediaType: "text/plain",
          type: "file",
          url: "data:text/plain;base64,aGVsbG8=",
        },
      ])
      await client.updateRuntime({ mention_hook_enabled: false })
      await client.updateRuntime({ max_cascade_turns: null })
      await client.switchConversation("thread-2")
      await client.stopAgent("agent")
      await client.joinRun("run_01")
      await client.cancelQueueItem("queue_thread_agent")
      await client.clearQueue("pending")
      await client.createBranch({ label: "Alternative", checkpointId: "checkpoint_01" })
      await client.switchBranch("branch_main")
      await client.resumeCheckpoint("checkpoint_01")
      await client.resumeInterrupt("interrupt_01", { decision: "respond", response: "ok" })
      await client.changes()
      await client.changeDiff("/api/studio/v1/changes/change_1/diff")
      await client.createTerminalSession()
      await client.terminalOutput("term_1", 0)
      await client.sendTerminalInput("term_1", "pwd\n")
      await client.resizeTerminal("term_1", 120, 40)
      await client.terminateTerminal("term_1")

      expect(requests).toEqual([
        {
          body: JSON.stringify({
            content: "@agent next",
            author_id: "human",
            attachments: [],
            wait: false,
          }),
          method: "POST",
          url: "http://127.0.0.1:8765/api/studio/v1/messages",
        },
        {
          body: JSON.stringify({
            content: "@agent file",
            author_id: "human",
            attachments: [
              {
                content_base64: "aGVsbG8=",
                filename: "notes.txt",
                media_type: "text/plain",
              },
            ],
            wait: false,
          }),
          method: "POST",
          url: "http://127.0.0.1:8765/api/studio/v1/messages",
        },
        {
          body: JSON.stringify({ mention_hook_enabled: false }),
          method: "PATCH",
          url: "http://127.0.0.1:8765/api/studio/v1/runtime",
        },
        {
          body: JSON.stringify({ max_cascade_turns: null }),
          method: "PATCH",
          url: "http://127.0.0.1:8765/api/studio/v1/runtime",
        },
        {
          body: JSON.stringify({ conversation_id: "thread-2" }),
          method: "PUT",
          url: "http://127.0.0.1:8765/api/studio/v1/session/conversation",
        },
        {
          body: undefined,
          method: "POST",
          url: "http://127.0.0.1:8765/api/studio/v1/agents/agent/stop",
        },
        {
          body: undefined,
          method: "POST",
          url: "http://127.0.0.1:8765/api/studio/v1/runs/run_01/join",
        },
        {
          body: undefined,
          method: "DELETE",
          url: "http://127.0.0.1:8765/api/studio/v1/queue/queue_thread_agent",
        },
        {
          body: JSON.stringify({ scope: "pending" }),
          method: "POST",
          url: "http://127.0.0.1:8765/api/studio/v1/queue/clear",
        },
        {
          body: JSON.stringify({
            checkpoint_id: "checkpoint_01",
            label: "Alternative",
          }),
          method: "POST",
          url: "http://127.0.0.1:8765/api/studio/v1/branches",
        },
        {
          body: undefined,
          method: "POST",
          url: "http://127.0.0.1:8765/api/studio/v1/branches/branch_main/switch",
        },
        {
          body: JSON.stringify({
            mode: "resume",
          }),
          method: "POST",
          url: "http://127.0.0.1:8765/api/studio/v1/checkpoints/checkpoint_01/resume",
        },
        {
          body: JSON.stringify({
            decision: "respond",
            response: "ok",
            edited_payload: {},
          }),
          method: "POST",
          url: "http://127.0.0.1:8765/api/studio/v1/interrupts/interrupt_01/resume",
        },
        {
          body: undefined,
          method: undefined,
          url: "http://127.0.0.1:8765/api/studio/v1/changes",
        },
        {
          body: undefined,
          method: undefined,
          url: "http://127.0.0.1:8765/api/studio/v1/changes/change_1/diff",
        },
        {
          body: undefined,
          method: "POST",
          url: "http://127.0.0.1:8765/api/studio/v1/terminal/sessions",
        },
        {
          body: undefined,
          method: undefined,
          url: "http://127.0.0.1:8765/api/studio/v1/terminal/sessions/term_1/output?cursor=0",
        },
        {
          body: JSON.stringify({ data: "pwd\n" }),
          method: "POST",
          url: "http://127.0.0.1:8765/api/studio/v1/terminal/sessions/term_1/input",
        },
        {
          body: JSON.stringify({ columns: 120, rows: 40 }),
          method: "POST",
          url: "http://127.0.0.1:8765/api/studio/v1/terminal/sessions/term_1/resize",
        },
        {
          body: undefined,
          method: "DELETE",
          url: "http://127.0.0.1:8765/api/studio/v1/terminal/sessions/term_1",
        },
      ])
    } finally {
      globalThis.fetch = previousFetch
    }
  })
})

function restoreStudioApiBaseUrl(value: string | undefined) {
  if (value === undefined) {
    delete process.env.STUDIO_API_BASE_URL
    return
  }
  process.env.STUDIO_API_BASE_URL = value
}

describe("studio reducer", () => {
  it("updates runtime settings and appends optimistic messages", () => {
    const fixture = loadStudioMock()
    const toggled = studioReducer(fixture.state, {
      type: "runtime.updated",
      runtime: {
        mention_hook_enabled: false,
      },
    })
    const next = studioReducer(toggled, {
      type: "message.optimistic_append",
      authorId: "human",
      content: "@agent follow up",
    })

    expect(toggled.runtime.mention_hook_enabled).toBe(false)
    expect(next.conversation.events.at(-1)?.mentions).toEqual(["agent"])
    expect(
      studioReducer(next, { type: "state.replaced", state: fixture.state })
        .conversation.events
    ).toHaveLength(fixture.state.conversation.events.length)
  })

  it("replaces matching optimistic events with streamed backend events", () => {
    const fixture = loadStudioMock()
    const optimistic = studioReducer(fixture.state, {
      type: "message.optimistic_append",
      authorId: "human",
      content: "@agent follow up",
    })
    const streamed = studioReducer(optimistic, {
      type: "conversation.event.appended",
      event: {
        ...optimistic.conversation.events.at(-1)!,
        id: "event_backend",
        metadata: {},
      },
    })

    expect(streamed.conversation.events).toHaveLength(
      optimistic.conversation.events.length
    )
    expect(streamed.conversation.events.at(-1)?.id).toBe("event_backend")
    expect(streamed.conversation.events.at(-1)?.metadata.optimistic).toBeUndefined()
  })

  it("reconciles optimistic events by client message id before content fallback", () => {
    const fixture = loadStudioMock()
    const first = studioReducer(fixture.state, {
      type: "message.optimistic_append",
      authorId: "human",
      clientMessageId: "client_1",
      content: "@agent same",
    })
    const second = studioReducer(first, {
      type: "message.optimistic_append",
      authorId: "human",
      clientMessageId: "client_2",
      content: "@agent same",
    })
    const streamed = studioReducer(second, {
      type: "conversation.event.appended",
      event: {
        ...second.conversation.events.at(-1)!,
        id: "event_backend",
        metadata: {
          client_message_id: "client_2",
        },
      },
    })
    const failed = studioReducer(second, {
      type: "message.optimistic_failed",
      clientMessageId: "client_1",
    })

    expect(streamed.conversation.events).toHaveLength(
      second.conversation.events.length
    )
    expect(streamed.conversation.events.at(-2)?.metadata.client_message_id).toBe(
      "client_1"
    )
    expect(streamed.conversation.events.at(-1)?.id).toBe("event_backend")
    expect(failed.conversation.events.at(-2)?.metadata.optimistic_status).toBe(
      "failed"
    )
  })

  it("applies validated generated UI patches to reducer state", () => {
    const fixture = loadStudioMock()
    const patched = studioReducer(fixture.state, {
      type: "generated_ui.patch",
      payload: {
        spec_id: "generated_ui_01",
        patch: {
          op: "replace",
          path: "/elements/metric_01/props/value",
          value: 4,
        },
      },
    })
    const metric = patched.generated_ui[0]?.elements.metric_01

    expect(metric?.props?.value).toBe(4)
    expect(patched.generated_ui[0]?.status).toBe("valid")
  })

  it("ignores generated UI patches with unsafe pointer roots", () => {
    const fixture = loadStudioMock()
    const patched = studioReducer(fixture.state, {
      type: "generated_ui.patch",
      payload: {
        spec_id: "generated_ui_01",
        patch: {
          op: "add",
          path: "/__proto__/polluted",
          value: true,
        },
      },
    })

    expect(patched.generated_ui[0]).toEqual(fixture.state.generated_ui[0])
    expect(({} as Record<string, unknown>).polluted).toBeUndefined()
  })

  it("upserts streamed run summaries", () => {
    const fixture = loadStudioMock()
    const next = studioReducer(fixture.state, {
      type: "run.upserted",
      run: {
        id: "run_completed",
        conversation_id: fixture.state.conversation_id,
        agent_id: "agent",
        status: "completed",
        created_at: "2026-06-01T10:00:01Z",
        updated_at: "2026-06-01T10:00:02Z",
        completed_at: "2026-06-01T10:00:02Z",
        checkpoint_id: null,
        cursor: "stream_00000002",
        metadata: {
          delivery_id: "delivery_01",
        },
      },
    })

    expect(next.runs[0]?.id).toBe("run_completed")
    expect(next.runs).toHaveLength(fixture.state.runs.length + 1)
  })

  it("applies streamed delivery and queue updates", () => {
    const fixture = loadStudioMock()
    const delivery = {
      ...fixture.state.conversation.deliveries[0]!,
      id: "delivery_streamed",
      status: "failed" as const,
      error: "boom",
    }
    const queued = {
      id: "queue_failed_delivery_streamed",
      conversation_id: fixture.state.conversation_id,
      agent_id: "agent",
      status: "failed" as const,
      position: null,
      enqueued_at: "2026-06-01T10:00:01Z",
      updated_at: "2026-06-01T10:00:02Z",
      message_event_id: "event_01",
      can_cancel: false,
      error: "boom",
    }

    const withDelivery = studioReducer(fixture.state, {
      type: "conversation.delivery.updated",
      delivery,
    })
    const withQueue = studioReducer(withDelivery, {
      type: "queue.updated",
      queue: [queued],
    })

    expect(withDelivery.conversation.deliveries.at(-1)?.id).toBe("delivery_streamed")
    expect(withQueue.queue).toEqual([queued])
  })

  it("applies streamed private activity and checkpoint updates", () => {
    const fixture = loadStudioMock()
    const message = {
      type: "ai",
      name: "agent",
      content: "Working privately",
      tool_calls: null,
    }
    const checkpoint = {
      ...fixture.state.history.checkpoints[0]!,
      id: "checkpoint_streamed",
      seq: 2,
    }

    const withPrivateMessage = studioReducer(fixture.state, {
      type: "activity.private_message.appended",
      payload: {
        agent_id: "agent",
        thread_id: "thread:mention:agent",
        message,
      },
    })
    const withSecondMessage = studioReducer(withPrivateMessage, {
      type: "activity.private_message.appended",
      payload: {
        agent_id: "agent",
        thread_id: "thread:mention:agent",
        message: {
          ...message,
          content: "Still working privately",
        },
      },
    })
    const withCheckpoint = studioReducer(withSecondMessage, {
      type: "checkpoint.observed",
      checkpoint,
    })

    expect(withPrivateMessage.activity.private_threads[0]?.messages).toEqual([message])
    expect(withSecondMessage.activity.private_threads[0]?.messages).toHaveLength(2)
    expect(withCheckpoint.history.checkpoints.at(-1)?.id).toBe("checkpoint_streamed")
  })
})
