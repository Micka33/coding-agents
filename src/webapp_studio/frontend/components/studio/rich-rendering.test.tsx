import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import type { ComponentProps } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ActivityPanel } from "@/components/studio/activity-panel"
import { ChatPanel } from "@/components/studio/chat-panel"
import { SchemaDisplay } from "@/components/ai-elements/schema-display"
import {
  WebPreview,
  WebPreviewBody,
} from "@/components/ai-elements/web-preview"
import { GeneratedUiPanel } from "@/components/studio/generated-ui-panel"
import { RichMarkdown } from "@/components/studio/rich-markdown"
import { StudioSidebar } from "@/components/studio/studio-sidebar"
import { ToolCallList } from "@/components/studio/tool-call-list"
import { TooltipProvider } from "@/components/ui/tooltip"
import { loadStudioMock } from "@/lib/studio/fixtures"
import type { StudioState } from "@/lib/studio/schemas"
import { studioToolCallsFromValue } from "@/lib/studio/tool-calls"

afterEach(() => {
  vi.useRealTimers()
})

describe("rich markdown rendering", () => {
  function renderRichMarkdown(content: string) {
    return render(
      <TooltipProvider>
        <RichMarkdown content={content} />
      </TooltipProvider>
    )
  }

  it("renders GFM content while skipping raw HTML", () => {
    const { container } = renderRichMarkdown(
      [
        "| Name | Status |",
        "| --- | --- |",
        "| Studio | ready |",
        "",
        "- [x] typed contracts",
        "",
        "[docs](https://example.com)",
        "",
        "<script>alert(1)</script>",
      ].join("\n")
    )

    const link = screen.getByRole("link", { name: "docs" })

    expect(screen.getByRole("table")).toBeInTheDocument()
    expect(screen.getByText("typed contracts")).toBeInTheDocument()
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("rel", "noopener noreferrer")
    expect(container.querySelector("script")).toBeNull()
  })

  it("copies code blocks without line numbers or language labels", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    })

    renderRichMarkdown(["```bash", "pnpm test", "```"].join("\n"))

    fireEvent.click(
      await screen.findByRole("button", { name: "Copy code block" })
    )

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("pnpm test"))
  })

  it("copies tables as spreadsheet-ready TSV", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    })

    renderRichMarkdown(
      ["| Name | Status |", "| --- | --- |", "| Studio | ready |"].join("\n")
    )

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Copy table for spreadsheet",
      })
    )

    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("Name\tStatus\nStudio\tready")
    )
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
          branch_id: "branch_main",
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

  it("renders branches as a parent-child tree and switches from tree items", () => {
    const fixture = loadStudioMock()
    const onSwitchBranch = vi.fn()
    const state: StudioState = {
      ...fixture.state,
      history: {
        ...fixture.state.history,
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
            created_at: "2026-06-03T10:00:00Z",
            current: true,
            status: "derived",
            head_checkpoint_id: null,
          },
          {
            id: "branch_edit_01",
            label: "Edit #1",
            parent_branch_id: "branch_main",
            origin_checkpoint_id: "frontier_event_01_before",
            origin_event_id: "event_01",
            origin_logical_message_id: "event_01",
            origin_previous_event_id: null,
            origin_event_seq: 0,
            created_at: "2026-06-03T10:05:00Z",
            current: false,
            status: "persisted",
            head_checkpoint_id: null,
          },
          {
            id: "branch_edit_02",
            label: "Nested edit",
            parent_branch_id: "branch_edit_01",
            origin_checkpoint_id: "frontier_event_02_before",
            origin_event_id: "event_02",
            origin_logical_message_id: "event_02",
            origin_previous_event_id: "event_01",
            origin_event_seq: 1,
            created_at: "2026-06-03T10:10:00Z",
            current: false,
            status: "persisted",
            head_checkpoint_id: null,
          },
        ],
      },
    }

    renderSidebar({ liveApi: true, onSwitchBranch, state })

    const nested = screen.getByText("Nested edit").closest("[role='treeitem']")
    expect(nested).toHaveAttribute("data-branch-depth", "2")

    fireEvent.click(screen.getByRole("button", { name: "Switch to Nested edit" }))

    expect(onSwitchBranch).toHaveBeenCalledWith("branch_edit_02")
  })
})

function renderActivityPanel(props: ComponentProps<typeof ActivityPanel>) {
  return render(
    <TooltipProvider>
      <ActivityPanel {...props} />
    </TooltipProvider>
  )
}

describe("activity panel navigation", () => {
  it("shows the agent list before an agent is selected", () => {
    const state = stateWithAgentActivity()
    const onAgentSelect = vi.fn()

    renderActivityPanel({
      onAgentSelect,
      onBack: () => undefined,
      state,
    })

    expect(screen.getByRole("heading", { name: "Agents" })).toBeInTheDocument()
    expect(screen.queryByText("Activity History")).not.toBeInTheDocument()
    expect(screen.queryByText("agent history")).not.toBeInTheDocument()

    fireEvent.click(
      screen.getByRole("button", { name: "Open activity for reviewer" })
    )

    expect(onAgentSelect).toHaveBeenCalledWith("reviewer")
  })

  it("shows the selected agent history and filters deliveries", () => {
    const state = stateWithAgentActivity()
    const onBack = vi.fn()

    renderActivityPanel({
      focusedAgentId: "agent",
      onAgentSelect: () => undefined,
      onBack,
      state,
    })

    fireEvent.click(
      screen.getByRole("button", { name: "Back to activity agents" })
    )

    expect(onBack).toHaveBeenCalledOnce()
    expect(screen.queryByText("Activity History")).not.toBeInTheDocument()
    expect(screen.queryByText("observable threads")).not.toBeInTheDocument()
    expect(screen.getByText("agent history")).toBeInTheDocument()
    expect(screen.getByText("older agent history")).toBeInTheDocument()
    expect(screen.getByText("success")).toBeInTheDocument()
    expect(screen.queryByText("reviewer history")).not.toBeInTheDocument()
    expect(
      screen.queryByText("reviewer delivery failed")
    ).not.toBeInTheDocument()

    const historyText =
      screen.getByLabelText("Agent activity history").textContent ?? ""
    expect(historyText.indexOf("agent history")).toBeLessThan(
      historyText.indexOf("older agent history")
    )
  })

  it("shows message timestamps beside actions without today's date", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-06-04T12:00:00Z"))
    const state = stateWithAgentActivity()
    state.activity.private_threads = [
      {
        agent_id: "agent",
        thread_id: "thread:mention:agent",
        last_activity_at: "2026-06-04T10:45:00Z",
        messages: [
          {
            type: "human",
            name: "human",
            created_at: "2026-06-04T10:30:00Z",
            content: "@agent today",
            tool_calls: [],
          },
          {
            type: "ai",
            name: "agent",
            created_at: "2026-06-03T10:45:00Z",
            content: "older final response",
            tool_calls: [],
          },
        ],
      },
    ]

    const { container } = renderActivityPanel({
      focusedAgentId: "agent",
      onAgentSelect: () => undefined,
      onBack: () => undefined,
      state,
    })

    const todayTime = container.querySelector(
      'time[datetime="2026-06-04T10:30:00.000Z"]'
    )
    const olderTime = container.querySelector(
      'time[datetime="2026-06-03T10:45:00.000Z"]'
    )

    expect(todayTime?.textContent).toMatch(/^\d{2}:\d{2}$/)
    expect(olderTime?.textContent).toContain("/")
  })

  it("keeps human activity messages read-only while allowing copy", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    })
    const state = stateWithAgentActivity()
    const activeThread = state.activity.private_threads[0]!
    activeThread.messages = [
      {
        type: "human",
        name: "human",
        content: "@agent please update",
        tool_calls: [],
      },
      ...activeThread.messages,
    ]

    renderActivityPanel({
      focusedAgentId: "agent",
      onAgentSelect: () => undefined,
      onBack: () => undefined,
      state,
    })

    const humanMessage = screen
      .getByText("@agent please update")
      .closest("[data-activity-message]")

    expect(humanMessage).not.toBeNull()
    expect(
      within(humanMessage as HTMLElement).queryByRole("button", {
        name: "Edit human message",
      })
    ).not.toBeInTheDocument()

    fireEvent.click(
      within(humanMessage as HTMLElement).getByRole("button", {
        name: "Copy message",
      })
    )

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("@agent please update")
    })
  })

  it("shows a persistent copy action under the final AI message", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    })
    const finalContent = [
      "## Final Answer",
      "",
      "- Done",
      "",
      "```bash",
      "pnpm test",
      "```",
    ].join("\n")
    const state = stateWithAgentActivity()
    state.activity.private_threads = [
      {
        agent_id: "agent",
        thread_id: "thread:mention:agent",
        last_activity_at: "2026-06-01T10:00:05Z",
        messages: [
          {
            type: "ai",
            name: "agent",
            content: "Working through the request.",
            tool_calls: [
              {
                id: "call_1",
                name: "shell",
                input: { command: "pnpm test" },
                output: "passed",
              },
            ],
          },
          {
            type: "ai",
            name: "agent",
            content: finalContent,
            tool_calls: [],
          },
        ],
      },
    ]

    renderActivityPanel({
      focusedAgentId: "agent",
      onAgentSelect: () => undefined,
      onBack: () => undefined,
      state,
    })

    const finalHeading = screen.getByRole("heading", { name: "Final Answer" })
    const finalMessage = finalHeading.closest("[data-activity-message]")

    expect(finalMessage).not.toBeNull()

    const finalCopyButton = within(finalMessage as HTMLElement).getByRole(
      "button",
      { name: "Copy message" }
    )
    expect(finalCopyButton).toBeVisible()

    fireEvent.click(finalCopyButton)

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(finalContent)
    })
  })
})

describe("chat panel transcript actions", () => {
  it("shows timestamps and supports copy and edit on public human messages", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    const editMessage = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    })
    const fixture = loadStudioMock()
    const state = {
      ...fixture.state,
      conversation: {
        ...fixture.state.conversation,
        events: [
          {
            ...fixture.state.conversation.events[0]!,
            attachments: [],
            author_id: "human",
            author_kind: "human" as const,
            content: "Original public prompt",
            created_at: "2026-06-03T10:30:00Z",
            id: "event_public_human_actions",
            logical_message_id: "event_public_human_actions",
            version_parent_event_id: null,
            parent_event_id: null,
            mentions: [],
            metadata: {},
          },
        ],
      },
    }

    const { container } = renderChatPanel({ onEditMessage: editMessage, state })
    const timestamp = container.querySelector(
      'time[datetime="2026-06-03T10:30:00.000Z"]'
    )
    const humanMessage = screen
      .getByText("Original public prompt")
      .closest("[data-transcript-message]")

    expect(timestamp?.textContent).toContain("/")
    expect(humanMessage).not.toBeNull()

    fireEvent.click(
      within(humanMessage as HTMLElement).getByRole("button", {
        name: "Copy message",
      })
    )
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("Original public prompt")
    })

    fireEvent.click(
      within(humanMessage as HTMLElement).getByRole("button", {
        name: "Edit human message",
      })
    )
    fireEvent.change(screen.getByLabelText("Edited human message"), {
      target: { value: "Edited public prompt" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Save message edit" }))

    await waitFor(() => {
      expect(editMessage).toHaveBeenCalledWith(
        "event_public_human_actions",
        "Edited public prompt"
      )
      expect(screen.queryByText("Original public prompt")).not.toBeInTheDocument()
    })

    const editedMessage = screen
      .getByText("Edited public prompt")
      .closest("[data-transcript-message]")
    expect(editedMessage).not.toBeNull()

    fireEvent.click(
      within(editedMessage as HTMLElement).getByRole("button", {
        name: "Copy message",
      })
    )

    await waitFor(() => {
      expect(writeText).toHaveBeenLastCalledWith("Edited public prompt")
    })
  })

  it("shows a message version selector and switches to the selected branch", () => {
    const switchBranch = vi.fn()
    const fixture = loadStudioMock()
    const state: StudioState = {
      ...fixture.state,
      history: {
        ...fixture.state.history,
        current_branch_id: "branch_main",
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
            created_at: "2026-06-03T10:00:00Z",
            current: true,
            status: "derived",
            head_checkpoint_id: null,
          },
          {
            id: "branch_edit_01",
            label: "Edit #1",
            parent_branch_id: "branch_main",
            origin_checkpoint_id: "frontier_event_01_before",
            origin_event_id: "event_public_human_actions",
            origin_logical_message_id: "event_public_human_actions",
            origin_previous_event_id: null,
            origin_event_seq: 0,
            created_at: "2026-06-03T10:05:00Z",
            current: false,
            status: "persisted",
            head_checkpoint_id: null,
          },
        ],
      },
      conversation: {
        ...fixture.state.conversation,
        events: [
          {
            ...fixture.state.conversation.events[0]!,
            attachments: [],
            author_id: "human",
            author_kind: "human" as const,
            content: "Original public prompt",
            created_at: "2026-06-03T10:30:00Z",
            id: "event_public_human_actions",
            logical_message_id: "event_public_human_actions",
            version_parent_event_id: null,
            parent_event_id: null,
            mentions: [],
            metadata: {},
          },
        ],
      },
    }

    renderChatPanel({
      liveApi: true,
      onSwitchBranch: switchBranch,
      state,
    })

    const humanMessage = screen
      .getByText("Original public prompt")
      .closest("[data-transcript-message]")

    expect(humanMessage).not.toBeNull()
    expect(within(humanMessage as HTMLElement).getByText("v1/2")).toBeInTheDocument()

    fireEvent.click(
      within(humanMessage as HTMLElement).getByRole("button", {
        name: "Next message version",
      })
    )

    expect(switchBranch).toHaveBeenCalledWith("branch_edit_01")
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
    const outboxKey = `webapp-studio:v1:${session.checkpointer.storage_id}:${state.team_id}:${state.conversation_id}:${state.history.current_branch_id}:human:outbox`
    localStorage.clear()

    render(
      <TooltipProvider>
        <ChatPanel
          busy={false}
          changes={null}
          liveApi
          onEditMessage={() => undefined}
          onOpenInspector={() => undefined}
          onSubmitDraft={async () => {
            throw new Error("offline")
          }}
          onSwitchBranch={() => undefined}
          session={session}
          state={state}
          streamStatus="connected"
        />
      </TooltipProvider>
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

  it("keeps drafts isolated by active branch", async () => {
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
    const mainDraftKey = `webapp-studio:v1:${session.checkpointer.storage_id}:${state.team_id}:${state.conversation_id}:branch_main:human:draft`
    const branchDraftKey = `webapp-studio:v1:${session.checkpointer.storage_id}:${state.team_id}:${state.conversation_id}:branch_edit_01:human:draft`
    const branchState: StudioState = {
      ...state,
      history: {
        ...state.history,
        current_branch_id: "branch_edit_01",
        branches: state.history.branches.map((branch) => ({
          ...branch,
          current: branch.id === "branch_edit_01",
        })),
      },
    }
    localStorage.clear()
    localStorage.setItem(branchDraftKey, "branch draft")

    const { rerender } = render(
      <TooltipProvider>
        <ChatPanel
          busy={false}
          changes={null}
          liveApi
          onEditMessage={() => undefined}
          onOpenInspector={() => undefined}
          onSubmitDraft={() => undefined}
          onSwitchBranch={() => undefined}
          session={session}
          state={state}
          streamStatus="connected"
        />
      </TooltipProvider>
    )

    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
    fireEvent.change(textarea, {
      target: { value: "main draft" },
    })

    await waitFor(() => {
      expect(localStorage.getItem(mainDraftKey)).toBe("main draft")
    })

    rerender(
      <TooltipProvider>
        <ChatPanel
          busy={false}
          changes={null}
          liveApi
          onEditMessage={() => undefined}
          onOpenInspector={() => undefined}
          onSubmitDraft={() => undefined}
          onSwitchBranch={() => undefined}
          session={session}
          state={branchState}
          streamStatus="connected"
        />
      </TooltipProvider>
    )

    await waitFor(() => {
      expect(textarea).toHaveValue("branch draft")
      expect(localStorage.getItem(mainDraftKey)).toBe("main draft")
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

    fireEvent.click(
      screen.getByRole("button", { name: "Open file change change_1" })
    )

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
    <TooltipProvider>
      <ChatPanel
        busy={false}
        changes={null}
        liveApi={false}
        onEditMessage={() => undefined}
        onOpenInspector={() => undefined}
        onSubmitDraft={() => undefined}
        onSwitchBranch={() => undefined}
        session={null}
        streamStatus="connected"
        {...props}
      />
    </TooltipProvider>
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

function stateWithAgentActivity(): StudioState {
  const fixture = loadStudioMock()
  const agentState = fixture.state.conversation.agent_states[0]!
  return {
    ...fixture.state,
    participants: ["agent", "reviewer"],
    conversation: {
      ...fixture.state.conversation,
      agent_states: [
        agentState,
        {
          ...agentState,
          agent_id: "reviewer",
          current_run_id: null,
          current_snapshot_seq: null,
          last_delivered_seq: 2,
          queued: false,
          running: false,
        },
      ],
      deliveries: [
        {
          id: "delivery_agent",
          team_id: "team",
          conversation_id: "thread",
          branch_id: "branch_main",
          agent_id: "agent",
          run_id: "run_agent",
          snapshot_seq: 1,
          status: "success",
          created_at: "2026-06-01T10:00:01Z",
          completed_at: "2026-06-01T10:00:02Z",
          error: null,
        },
        {
          id: "delivery_reviewer",
          team_id: "team",
          conversation_id: "thread",
          branch_id: "branch_main",
          agent_id: "reviewer",
          run_id: "run_reviewer",
          snapshot_seq: 2,
          status: "failed",
          created_at: "2026-06-01T10:00:03Z",
          completed_at: "2026-06-01T10:00:04Z",
          error: "reviewer delivery failed",
        },
      ],
    },
    activity: {
      active_agent_ids: ["agent"],
      private_threads: [
        {
          agent_id: "agent",
          thread_id: "thread:mention:agent",
          last_activity_at: "2026-06-01T10:00:05Z",
          messages: [
            {
              type: "ai",
              name: "agent",
              content: "agent history",
              tool_calls: [],
            },
          ],
        },
        {
          agent_id: "agent",
          thread_id: "thread:mention:agent:older",
          last_activity_at: "2026-06-01T10:00:01Z",
          messages: [
            {
              type: "ai",
              name: "agent",
              content: "older agent history",
              tool_calls: [],
            },
          ],
        },
        {
          agent_id: "reviewer",
          thread_id: "thread:mention:reviewer",
          messages: [
            {
              type: "ai",
              name: "reviewer",
              content: "reviewer history",
              tool_calls: [],
            },
          ],
        },
      ],
    },
  }
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

  it("renders compact collapsed action groups", () => {
    render(
      <ToolCallList
        value={[
          {
            id: "call_terminal",
            name: "shell",
            args: {
              command:
                "uv run coverage report --include src/really/long/path/that/should/not/wrap/in/parameters/**/*.ts",
            },
            output: "uv run coverage report",
          },
          {
            id: "call_tests",
            name: "test_results",
            output: { passed: 2, failed: 0, skipped: 1, total: 3 },
          },
          {
            id: "call_pending",
            name: "custom_tool",
            input: { value: true },
          },
        ]}
      />
    )

    const completedGroup = screen.getByRole("button", {
      name: "2 actions effectuées",
    })
    const pendingGroup = screen.getByRole("button", {
      name: "1 action en cours",
    })

    expect(completedGroup).toHaveAttribute("aria-expanded", "false")
    expect(pendingGroup).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByText("uv run coverage report")).not.toBeInTheDocument()

    fireEvent.click(completedGroup)

    const shellAction = screen.getByRole("button", {
      name: /Open action run uv run coverage report/,
    })
    expect(shellAction).toBeInTheDocument()
    expect(
      screen.getByRole("button", {
        name: "Open action 2 passed, 0 failed, 1 skipped",
      })
    ).toBeInTheDocument()
    expect(screen.queryByText("uv run coverage report")).not.toBeInTheDocument()

    fireEvent.click(shellAction)

    expect(screen.getByText("uv run coverage report")).toBeInTheDocument()
    expect(screen.getByText("Result")).toBeInTheDocument()
  })
})
