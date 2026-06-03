import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ComponentProps } from "react"
import { describe, expect, it, vi } from "vitest"

import { ChatPanel } from "@/components/studio/chat-panel"
import { SchemaDisplay } from "@/components/ai-elements/schema-display"
import { WebPreview, WebPreviewBody } from "@/components/ai-elements/web-preview"
import { GeneratedUiPanel } from "@/components/studio/generated-ui-panel"
import { RichMarkdown } from "@/components/studio/rich-markdown"
import { StudioSidebar } from "@/components/studio/studio-sidebar"
import { ToolCallList } from "@/components/studio/tool-call-list"
import { loadStudioMock } from "@/lib/studio/fixtures"
import { studioToolCallsFromValue } from "@/lib/studio/tool-calls"

describe("rich markdown rendering", () => {
  it("renders GFM content while skipping raw HTML", () => {
    const { container } = render(
      <RichMarkdown
        content={[
          "| Name | Status |",
          "| --- | --- |",
          "| Studio | ready |",
          "",
          "- [x] typed contracts",
          "",
          "[docs](https://example.com)",
          "",
          "<script>alert(1)</script>",
        ].join("\n")}
      />
    )

    const link = screen.getByRole("link", { name: "docs" })

    expect(screen.getByRole("table")).toBeInTheDocument()
    expect(screen.getByText("typed contracts")).toBeInTheDocument()
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("rel", "noopener noreferrer")
    expect(container.querySelector("script")).toBeNull()
  })
})

describe("schema display rendering", () => {
  it("renders highlighted path parameters without injecting raw HTML", () => {
    const { container } = render(
      <SchemaDisplay method="GET" path="/items/{id}<script>alert(1)</script>" />
    )

    expect(screen.getByText("{id}")).toHaveClass("text-blue-600")
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument()
    expect(container.querySelector("script")).toBeNull()
  })
})

describe("web preview rendering", () => {
  it("uses a conservative iframe sandbox by default", () => {
    render(
      <WebPreview defaultUrl="https://example.com">
        <WebPreviewBody />
      </WebPreview>
    )

    expect(screen.getByTitle("Preview")).toHaveAttribute(
      "sandbox",
      "allow-forms allow-popups allow-presentation"
    )
  })
})

describe("generated UI actions", () => {
  it("confirms registered actions and records audit entries", async () => {
    const fixture = loadStudioMock()

    render(<GeneratedUiPanel specs={[fixture.generatedUi[0]]} />)
    fireEvent.click(screen.getByRole("button", { name: "Open task details" }))
    fireEvent.click(await screen.findByRole("button", { name: "Open" }))

    expect(
      await screen.findByLabelText("Generated action audit generated_ui_01")
    ).toBeInTheDocument()
    expect(screen.getByText("open_task_details")).toBeInTheDocument()
    expect(screen.getByText(/task_01/)).toBeInTheDocument()
  })
})

describe("studio sidebar controls", () => {
  it("disables checkpoint branch creation when the capability is unsupported", () => {
    const fixture = loadStudioMock()

    renderSidebar({ liveApi: true, state: fixture.state })

    expect(
      screen.getByRole("button", { name: "Create branch from checkpoint_01" })
    ).toBeDisabled()
  })

  it("disables live mutation controls in fixture mode", () => {
    const fixture = loadStudioMock()
    const state = {
      ...fixture.state,
      queue: [
        {
          id: "queue_thread_agent",
          conversation_id: fixture.state.conversation_id,
          agent_id: "agent",
          status: "pending" as const,
          position: 1,
          enqueued_at: null,
          updated_at: null,
          message_event_id: "event_01",
          can_cancel: true,
          error: null,
        },
      ],
    }

    renderSidebar({ liveApi: false, state })

    expect(screen.getByRole("button", { name: "Clear queue" })).toBeDisabled()
    expect(screen.getByLabelText("Cascade limit")).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Cancel agent queue item" })
    ).toBeDisabled()
    expect(screen.getByRole("button", { name: "Stop agent" })).toBeDisabled()
  })

  it("applies numeric cascade limit changes", () => {
    const fixture = loadStudioMock()
    const onCascadeLimitChange = vi.fn()

    renderSidebar({
      liveApi: true,
      onCascadeLimitChange,
      state: fixture.state,
    })

    fireEvent.change(screen.getByLabelText("Cascade limit"), {
      target: { value: "5" },
    })
    fireEvent.blur(screen.getByLabelText("Cascade limit"))

    expect(onCascadeLimitChange).toHaveBeenCalledWith(5)
  })
})

describe("chat panel local recovery", () => {
  it("persists failed submitted prompts in the per-thread outbox", async () => {
    const fixture = loadStudioMock()
    const state = fixture.state
    const session = {
      team_id: state.team_id,
      conversation_id: state.conversation_id,
      team_file: "/tmp/team.yaml",
      launcher_cwd: "/tmp/project",
      resolved_root_dir: "/tmp/project",
      checkpointer: {
        backend: "memory",
        sqlite_path: null,
        storage_id: "memory:test-store",
      },
      loaded_at: "2026-06-02T10:17:06Z",
    }
    const outboxKey = `webapp-studio:v1:${session.checkpointer.storage_id}:${state.team_id}:${state.conversation_id}:outbox`
    localStorage.clear()

    render(
      <ChatPanel
        busy={false}
        changes={null}
        liveApi
        onOpenInspector={() => undefined}
        onSubmitDraft={async () => {
          throw new Error("offline")
        }}
        session={session}
        state={state}
        streamStatus="connected"
      />
    )

    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "@agent recover me" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Send message" }))

    await waitFor(() => {
      expect(screen.getByText("Unsaved prompt")).toBeInTheDocument()
      const stored = JSON.parse(localStorage.getItem(outboxKey) ?? "[]")
      expect(stored[0]).toMatchObject({
        content: "@agent recover me",
        status: "failed",
      })
    })
  })
})

describe("chat panel transcript affordances", () => {
  it("opens structured file change links in the right inspector", () => {
    const fixture = loadStudioMock()
    const onOpenInspector = vi.fn()
    const state = {
      ...fixture.state,
      conversation: {
        ...fixture.state.conversation,
        events: [
          {
            ...fixture.state.conversation.events[0]!,
            metadata: {
              change_ids: ["change_1"],
            },
          },
        ],
      },
    }

    renderChatPanel({
      changes: {
        supported: true,
        changes: [
          {
            id: "change_1",
            path: "src/app.tsx",
            status: "modified",
            source: "git",
            agent_id: null,
            event_id: fixture.state.conversation.events[0]!.id,
            diff_url: "/api/studio/v1/changes/change_1/diff",
          },
        ],
      },
      onOpenInspector,
      state,
    })

    fireEvent.click(screen.getByRole("button", { name: "Open file change change_1" }))

    expect(onOpenInspector).toHaveBeenCalledWith({
      kind: "changes",
      selectedChangeId: "change_1",
    })
  })
})

describe("chat panel mention autocomplete", () => {
  it("replaces the active mention range at the cursor and preserves suffix text", async () => {
    const fixture = loadStudioMock()
    localStorage.clear()

    renderChatPanel({ state: fixture.state })

    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
    fireEvent.change(textarea, {
      target: {
        selectionEnd: 10,
        selectionStart: 10,
        value: "please @ag then",
      },
    })
    const option = await screen.findByRole("option", { name: /@agent/ })
    fireEvent.mouseDown(option)

    expect(textarea).toHaveValue("please @agent then")
  })

  it("filters aliases but inserts the canonical participant id", async () => {
    const fixture = loadStudioMock()
    localStorage.clear()

    renderChatPanel({
      state: {
        ...fixture.state,
        participant_aliases: {
          ...fixture.state.participant_aliases,
          agent: ["lead"],
        },
      },
    })

    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
    fireEvent.change(textarea, {
      target: {
        selectionEnd: 3,
        selectionStart: 3,
        value: "@le",
      },
    })
    const option = await screen.findByRole("option", { name: /aliases: @lead/ })
    fireEvent.mouseDown(option)

    expect(textarea).toHaveValue("@agent ")
  })

  it("does not trigger mentions inside emails or markdown code", () => {
    const fixture = loadStudioMock()
    localStorage.clear()

    renderChatPanel({ state: fixture.state })

    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
    fireEvent.change(textarea, {
      target: {
        selectionEnd: 8,
        selectionStart: 8,
        value: "email a@",
      },
    })
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()

    fireEvent.change(textarea, {
      target: {
        selectionEnd: 4,
        selectionStart: 4,
        value: "`@ag",
      },
    })
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
  })
})

function renderChatPanel(
  props: Pick<ComponentProps<typeof ChatPanel>, "state"> &
    Partial<ComponentProps<typeof ChatPanel>>
) {
  return render(
    <ChatPanel
      busy={false}
      changes={null}
      liveApi={false}
      onOpenInspector={() => undefined}
      onSubmitDraft={() => undefined}
      session={null}
      streamStatus="connected"
      {...props}
    />
  )
}

function renderSidebar(
  props: Pick<ComponentProps<typeof StudioSidebar>, "state"> &
    Partial<ComponentProps<typeof StudioSidebar>>
) {
  return render(
    <StudioSidebar
      busy={false}
      collapsed={false}
      conversationList={null}
      liveApi
      onCascadeLimitChange={() => undefined}
      onCancelQueueItem={() => undefined}
      onClearQueue={() => undefined}
      onCreateBranchFromCheckpoint={() => undefined}
      onEditCheckpoint={() => undefined}
      onOpenInspector={() => undefined}
      onRegenerateCheckpoint={() => undefined}
      onResumeCheckpoint={() => undefined}
      onResumeInterrupt={() => undefined}
      onRuntimeChange={() => undefined}
      onStopAgent={() => undefined}
      onSwitchBranch={() => undefined}
      onSwitchConversation={() => undefined}
      onToggleCollapsed={() => undefined}
      session={null}
      {...props}
    />
  )
}

describe("tool-call rendering", () => {
  it("normalizes tool calls into specialized activity cards", () => {
    const calls = studioToolCallsFromValue([
      {
        id: "call_terminal",
        name: "terminal_command",
        args: { command: "pytest" },
        output: "159 passed",
      },
      {
        id: "call_tests",
        name: "test_results",
        output: { passed: 2, failed: 1, skipped: 0, total: 3 },
      },
      {
        id: "call_unknown",
        name: "custom_tool",
        input: { value: true },
      },
    ])

    expect(calls.map((call) => call.kind)).toEqual([
      "terminal",
      "test-results",
      "generic",
    ])
    expect(calls.map((call) => call.state)).toEqual([
      "output-available",
      "output-available",
      "input-available",
    ])
  })

  it("renders specialized terminal and test-result cards", () => {
    render(
      <ToolCallList
        value={[
          {
            id: "call_terminal",
            name: "shell",
            output: "uv run coverage report",
          },
          {
            id: "call_tests",
            name: "test_results",
            output: { passed: 2, failed: 0, skipped: 1, total: 3 },
          },
        ]}
      />
    )

    expect(screen.getByText("terminal: shell")).toBeInTheDocument()
    expect(screen.getByText("uv run coverage report")).toBeInTheDocument()
    expect(screen.getByText("test-results: test_results")).toBeInTheDocument()
    expect(screen.getByText("2 passed")).toBeInTheDocument()
    expect(screen.getByText("1 skipped")).toBeInTheDocument()
  })
})
