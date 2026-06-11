import {
  act,
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
import { RightInspector } from "@/components/studio/right-inspector"
import { StudioSidebar } from "@/components/studio/studio-sidebar"
import { emptyStudioState, StudioWorkspace } from "@/components/studio/studio-workspace"
import { ToolCallList } from "@/components/studio/tool-call-list"
import { TooltipProvider } from "@/components/ui/tooltip"
import type { StudioApiClient } from "@/lib/studio/api-client"
import { loadStudioMock } from "@/lib/studio/fixtures"
import type { StudioState, StudioTeamDescriptor } from "@/lib/studio/schemas"
import { studioToolCallsFromValue } from "@/lib/studio/tool-calls"

afterEach(() => {
  vi.useRealTimers()
})

describe("rich markdown rendering", () => {
  function renderRichMarkdown(
    content: string,
    props: Omit<ComponentProps<typeof RichMarkdown>, "content"> = {}
  ) {
    return render(
      <TooltipProvider>
        <RichMarkdown content={content} {...props} />
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

  it("toggles code block wrapping without changing copied code", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    })

    const code = "project\n  src\n    really-long-output-line"
    renderRichMarkdown(["```text", code, "```"].join("\n"))

    const wrapButton = await screen.findByRole("button", {
      name: "Disable code wrapping",
    })
    const block = wrapButton.closest("[data-code-wrap]")

    expect(block).toHaveAttribute("data-code-wrap", "true")

    fireEvent.click(wrapButton)

    expect(block).toHaveAttribute("data-code-wrap", "false")
    expect(
      screen.getByRole("button", { name: "Enable code wrapping" })
    ).toHaveAttribute("aria-pressed", "false")

    fireEvent.click(screen.getByRole("button", { name: "Copy code block" }))

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(code))
  })

  it("can render code blocks unwrapped by default", async () => {
    renderRichMarkdown(["```text", "a very long line", "```"].join("\n"), {
      defaultCodeWrap: false,
    })

    const wrapButton = await screen.findByRole("button", {
      name: "Enable code wrapping",
    })

    expect(wrapButton.closest("[data-code-wrap]")).toHaveAttribute(
      "data-code-wrap",
      "false"
    )
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

describe("right inspector preformatted output", () => {
  it("toggles diff wrapping and copies the raw diff", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    })

    const diff = [
      "diff --git a/src/app.ts b/src/app.ts",
      "+project",
      "+  src",
      "+    really-long-output-line",
    ].join("\n")
    const apiClient = {
      changeDiff: vi.fn().mockResolvedValue({
        change_id: "change_1",
        diff,
        path: "src/app.ts",
      }),
    } as unknown as StudioApiClient
    const { state } = loadStudioMock()

    render(
      <TooltipProvider>
        <RightInspector
          apiClient={apiClient}
          changes={{
            changes: [
              {
                agent_id: "developer",
                diff_url: "/api/studio/v1/changes/change_1/diff",
                event_id: "event_1",
                id: "change_1",
                path: "src/app.ts",
                source: "workspace",
                status: "modified",
              },
            ],
            supported: true,
          }}
          files={[]}
          generatedUi={[]}
          onClose={() => undefined}
          onViewChange={() => undefined}
          placement="side"
          session={null}
          state={state}
          view={{ kind: "changes" }}
        />
      </TooltipProvider>
    )

    await waitFor(() => expect(apiClient.changeDiff).toHaveBeenCalled())
    expect(
      screen.getByText((content) => content.includes("diff --git"))
    ).toBeInTheDocument()

    const wrapButton = await screen.findByRole("button", {
      name: "Enable line wrapping",
    })
    const block = wrapButton.closest("[data-preformatted-wrap]")

    expect(block).toHaveAttribute("data-preformatted-wrap", "false")

    fireEvent.click(wrapButton)

    expect(block).toHaveAttribute("data-preformatted-wrap", "true")
    expect(
      screen.getByRole("button", { name: "Disable line wrapping" })
    ).toHaveAttribute("aria-pressed", "true")

    fireEvent.click(screen.getByRole("button", { name: "Copy diff output" }))

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(diff))
  })

  it("does not iframe files without an available preview url", () => {
    const { state } = loadStudioMock()

    render(
      <TooltipProvider>
        <RightInspector
          apiClient={null}
          changes={null}
          files={[
            {
              added_by: "human",
              download_url: "/api/studio/v1/files/file_01/download",
              event_id: "event_01",
              event_seq: 1,
              filename: "SKILL.md",
              id: "file_01",
              media_type: null,
              preview_mode: null,
              preview_url: null,
              size_bytes: 10738,
            },
          ]}
          generatedUi={[]}
          onClose={() => undefined}
          onViewChange={() => undefined}
          placement="side"
          session={null}
          state={state}
          view={{ kind: "files" }}
        />
      </TooltipProvider>
    )

    expect(screen.getByText("Preview is not available for this file type.")).toBeInTheDocument()
    expect(screen.queryByTitle("SKILL.md")).not.toBeInTheDocument()
  })

  it("renders text file previews as raw text instead of an iframe", async () => {
    const previousFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response("# skill\n\nDo not render this as Markdown.")
    ) as typeof fetch
    const { state } = loadStudioMock()

    try {
      render(
        <TooltipProvider>
          <RightInspector
            apiClient={null}
            changes={null}
            files={[
              {
                added_by: "human",
                download_url: "/api/studio/v1/files/file_01/download",
                event_id: "event_01",
                event_seq: 1,
                filename: "SKILL.md",
                id: "file_01",
                media_type: "text/markdown",
                preview_mode: "text",
                preview_url: "/api/studio/v1/files/file_01/preview",
                size_bytes: 38,
              },
            ]}
            generatedUi={[]}
            onClose={() => undefined}
            onViewChange={() => undefined}
            placement="side"
            session={null}
            state={state}
            view={{ kind: "files" }}
          />
        </TooltipProvider>
      )

      const rawPreview = await screen.findByLabelText("Raw preview for SKILL.md")

      expect(rawPreview).toHaveTextContent("# skill")
      expect(rawPreview).toHaveTextContent("Do not render this as Markdown.")
      expect(screen.queryByRole("heading", { name: "skill" })).not.toBeInTheDocument()
      expect(screen.queryByTitle("SKILL.md")).not.toBeInTheDocument()
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/studio/v1/files/file_01/preview")
    } finally {
      globalThis.fetch = previousFetch
    }
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

  it("labels package teams, disables missing ones, and surfaces trust and env notices", () => {
    const fixture = loadStudioMock()
    const packaged: StudioTeamDescriptor = {
      team_id: "software",
      description: "Packaged team",
      team_file: "/repo/.coding-agents/packages/acme/software-team/teams/software/team.yaml",
      source: "package",
      conversation_available: true,
      participants: [],
      participant_aliases: {},
      package_name: "acme/software-team",
      package_version: "1.0.0",
      package_source: "git:https://example.test/repo.git",
      lock_status: "locked",
      trust_status: "untrusted",
      risk_flags: ["shell", "stdio_mcp"],
      missing_required_env: ["PACKAGE_TOKEN"],
      warnings: ["Required environment variable 'PACKAGE_TOKEN' is not set."],
    }
    const missing: StudioTeamDescriptor = {
      team_id: "gone",
      description: null,
      team_file: "/repo/.coding-agents/packages/acme/gone/teams/gone/team.yaml",
      source: "package",
      conversation_available: false,
      participants: [],
      participant_aliases: {},
      package_name: "acme/gone",
      lock_status: "missing",
      trust_status: "not_required",
      risk_flags: [],
      missing_required_env: [],
      warnings: [],
    }
    const state: StudioState = {
      ...fixture.state,
      team_id: "software",
      conversation_id: "",
    }

    renderSidebar({
      state,
      teams: { status: "ready", teams: [packaged, missing], duplicate_ids: [] },
    })

    const select = screen.getByLabelText(/Team/) as HTMLSelectElement
    const options = within(select).getAllByRole("option") as HTMLOptionElement[]
    expect(options.map((option) => option.textContent)).toEqual([
      "software · acme/software-team",
      "gone · acme/gone (missing)",
    ])
    expect(options[1]).toBeDisabled()

    const notices = screen.getByTestId("team-package-notices")
    expect(notices).toHaveTextContent("Untrusted package (shell, stdio_mcp)")
    expect(notices).toHaveTextContent("coding-agents team trust acme/software-team")
    expect(notices).toHaveTextContent("Required environment variable 'PACKAGE_TOKEN' is not set.")
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
            archived_at: null,
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
            archived_at: null,
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
            archived_at: null,
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

  it("pairs tool result messages with activity tool calls", () => {
    const state = stateWithAgentActivity()
    state.activity.private_threads = [
      {
        agent_id: "agent",
        thread_id: "thread:mention:agent",
        messages: [
          {
            type: "ai",
            name: "agent",
            content: "",
            tool_calls: [
              {
                id: "call_time",
                name: "get_current_time",
                args: { timezone: "Europe/Paris" },
              },
            ],
          },
          {
            type: "tool",
            name: "get_current_time",
            content: "2026-06-11T12:09:04+02:00",
            tool_call_id: "call_time",
            tool_calls: [],
          },
          {
            type: "ai",
            name: "agent",
            content: "12:09 PM",
            tool_calls: [],
          },
          {
            type: "tool",
            name: "get_current_time",
            content: "orphan result",
            tool_call_id: "call_orphan",
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

    const completedAction = screen.getByRole("button", {
      name: /Open action get_current_time .*Europe\/Paris/,
    })

    expect(completedAction).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "1 action effectuée" })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "1 action en cours" })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText("2026-06-11T12:09:04+02:00")
    ).not.toBeInTheDocument()
    expect(screen.getByText("orphan result")).toBeInTheDocument()

    fireEvent.click(completedAction)

    expect(
      screen.getAllByText("2026-06-11T12:09:04+02:00").length
    ).toBe(1)
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
            archived_at: null,
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
            archived_at: null,
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
  it("hydrates and persists branch UI state through the live backend callback", async () => {
    vi.useFakeTimers()
    const fixture = loadStudioMock()
    const onPersistUiState = vi.fn()
    const state: StudioState = {
      ...fixture.state,
      ui_state: {
        ...fixture.state.ui_state,
        draft_content: "restored backend draft",
      },
    }

    renderChatPanel({
      liveApi: true,
      onPersistUiState,
      state,
    })

    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
    expect(textarea).toHaveValue("restored backend draft")

    fireEvent.change(textarea, {
      target: { value: "next backend draft" },
    })
    await vi.advanceTimersByTimeAsync(400)

    expect(onPersistUiState).toHaveBeenLastCalledWith({
      branchId: "branch_main",
      draftContent: "next backend draft",
      editingEventId: null,
      outboxState: [],
    })
  })

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
          onPersistUiState={() => undefined}
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
          onPersistUiState={() => undefined}
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
          onPersistUiState={() => undefined}
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

describe("studio workspace responsive layout", () => {
  it("keeps the composer mounted when the layout crosses the narrow breakpoint", () => {
    const media = installMatchMedia(false)
    const fixture = loadStudioMock()
    localStorage.clear()

    try {
      render(
        <TooltipProvider>
          <StudioWorkspace
            generatedUi={[]}
            initialState={fixture.state}
            liveApi={false}
          />
        </TooltipProvider>
      )

      const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
      fireEvent.change(textarea, {
        target: {
          selectionEnd: 14,
          selectionStart: 14,
          value: "draft survives",
        },
      })

      media.setMatches(true)

      expect(screen.getByLabelText("Message")).toBe(textarea)
      expect(textarea).toHaveValue("draft survives")
    } finally {
      media.restore()
    }
  })

  it("collapses the inspector shell instead of unmounting it", () => {
    const media = installMatchMedia(false)
    const fixture = loadStudioMock()
    localStorage.clear()

    try {
      render(
        <TooltipProvider>
          <StudioWorkspace
            generatedUi={[]}
            initialState={fixture.state}
            liveApi={false}
          />
        </TooltipProvider>
      )

      const grid = screen.getByTestId("studio-layout-grid")
      const shell = screen.getByTestId("right-inspector-shell")
      expect(grid.className).toContain("transition-[grid-template-columns]")
      expect(shell).toHaveAttribute("aria-hidden", "true")
      expect(shell).toHaveClass("opacity-0")

      fireEvent.click(screen.getByRole("button", { name: "Files" }))

      expect(shell).toHaveAttribute("aria-hidden", "false")
      expect(shell).toHaveClass("opacity-100")
      fireEvent.click(screen.getByRole("button", { name: "Close inspector" }))

      expect(shell).toHaveAttribute("aria-hidden", "true")
      expect(shell).toHaveClass("opacity-0")
      expect(screen.queryByRole("button", { name: "Close inspector" })).not.toBeInTheDocument()
    } finally {
      media.restore()
    }
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
  it("suggests selected team agents before the first message creates a conversation", () => {
    const team: StudioTeamDescriptor = {
      team_id: "openspec",
      description: "OpenSpec team",
      team_file: "/repo/teams/openspec/team.yaml",
      source: "builtin",
      conversation_available: true,
      participants: ["openspec-guide", "product-strategist"],
      participant_aliases: {
        "openspec-guide": ["guide"],
        "product-strategist": ["product"],
      },
      risk_flags: [],
      missing_required_env: [],
      warnings: [],
    }
    localStorage.clear()

    renderChatPanel({ state: emptyStudioState(team) })

    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
    fireEvent.change(textarea, {
      target: {
        selectionEnd: 5,
        selectionStart: 5,
        value: "@prod",
      },
    })

    expect(screen.getByRole("option", { name: "@product-strategist" })).toBeInTheDocument()
    expect(screen.queryByRole("option", { name: "@openspec-guide" })).not.toBeInTheDocument()
  })

  it("opens the hidden file input from the attach file button", () => {
    const fixture = loadStudioMock()
    const clickDescriptor = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "click"
    )
    const inputClick = vi.fn()
    localStorage.clear()

    try {
      Object.defineProperty(HTMLInputElement.prototype, "click", {
        configurable: true,
        value: inputClick,
      })

      renderChatPanel({ state: fixture.state })
      fireEvent.click(screen.getByRole("button", { name: "Attach file" }))

      expect(inputClick).toHaveBeenCalledOnce()
    } finally {
      if (clickDescriptor) {
        Object.defineProperty(HTMLInputElement.prototype, "click", clickDescriptor)
      } else {
        delete (HTMLInputElement.prototype as Partial<HTMLInputElement>).click
      }
    }
  })

  it("keeps participant mention tags visible on mobile", () => {
    const fixture = loadStudioMock()
    localStorage.clear()

    renderChatPanel({ state: fixture.state })

    const tag = screen.getByRole("button", { name: "Mention agent" })
    expect(tag.parentElement).toHaveClass("flex", "flex-wrap")
    expect(tag.parentElement).not.toHaveClass("hidden")
  })

  it("submits selected local attachments with the draft", async () => {
    const fixture = loadStudioMock()
    const createObjectUrlDescriptor = Object.getOwnPropertyDescriptor(
      URL,
      "createObjectURL"
    )
    const revokeObjectUrlDescriptor = Object.getOwnPropertyDescriptor(
      URL,
      "revokeObjectURL"
    )
    const onSubmitDraft = vi.fn()
    localStorage.clear()

    try {
      Object.defineProperty(URL, "createObjectURL", {
        configurable: true,
        value: vi.fn(() => "data:text/plain;base64,aGVsbG8="),
      })
      Object.defineProperty(URL, "revokeObjectURL", {
        configurable: true,
        value: vi.fn(),
      })

      renderChatPanel({ onSubmitDraft, state: fixture.state })

      fireEvent.change(screen.getByLabelText("Upload files"), {
        target: {
          files: [new File(["hello"], "hello.txt", { type: "text/plain" })],
        },
      })
      fireEvent.change(screen.getByLabelText("Message"), {
        target: {
          selectionEnd: 15,
          selectionStart: 15,
          value: "with attachment",
        },
      })
      fireEvent.click(screen.getByRole("button", { name: "Send message" }))

      await waitFor(() =>
        expect(onSubmitDraft).toHaveBeenCalledWith(
          "with attachment",
          [
            expect.objectContaining({
              filename: "hello.txt",
              mediaType: "text/plain",
              type: "file",
              url: "data:text/plain;base64,aGVsbG8=",
            }),
          ],
          [],
          expect.any(String)
        )
      )
    } finally {
      if (createObjectUrlDescriptor) {
        Object.defineProperty(URL, "createObjectURL", createObjectUrlDescriptor)
      } else {
        delete (URL as Partial<typeof URL>).createObjectURL
      }
      if (revokeObjectUrlDescriptor) {
        Object.defineProperty(URL, "revokeObjectURL", revokeObjectUrlDescriptor)
      } else {
        delete (URL as Partial<typeof URL>).revokeObjectURL
      }
    }
  })

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
    const option = await screen.findByRole("option", { name: /@agent/ })
    fireEvent.mouseDown(option)

    expect(textarea).toHaveValue("@agent ")
  })

  it("keeps the active autocomplete option visible during keyboard navigation", async () => {
    const fixture = loadStudioMock()
    const scrollIntoViewDescriptor = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollIntoView"
    )
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    })
    localStorage.clear()

    try {
      renderChatPanel({
        state: {
          ...fixture.state,
          participant_aliases: {},
          participants: Array.from({ length: 12 }, (_, index) => `agent-${index}`),
        },
      })

      const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
      fireEvent.change(textarea, {
        target: {
          selectionEnd: 1,
          selectionStart: 1,
          value: "@",
        },
      })
      await screen.findByRole("option", { name: "@agent-0" })

      scrollIntoView.mockClear()
      fireEvent.keyDown(textarea, { key: "ArrowDown" })

      await waitFor(() =>
        expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" })
      )
      expect(screen.getByRole("option", { name: "@agent-1" })).toHaveAttribute(
        "aria-selected",
        "true"
      )
    } finally {
      if (scrollIntoViewDescriptor) {
        Object.defineProperty(
          HTMLElement.prototype,
          "scrollIntoView",
          scrollIntoViewDescriptor
        )
      } else {
        delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView
      }
    }
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

  it("selects workspace files from the reference autocomplete and submits their paths", async () => {
    const fixture = loadStudioMock()
    const onSearchWorkspaceFiles = vi.fn().mockResolvedValue([
      {
        filename: "app.ts",
        media_type: "text/plain",
        path: "src/app.ts",
        size_bytes: 12,
      },
    ])
    const onSubmitDraft = vi.fn()
    localStorage.clear()

    renderChatPanel({
      onSearchWorkspaceFiles,
      onSubmitDraft,
      state: fixture.state,
    })

    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
    fireEvent.change(textarea, {
      target: {
        selectionEnd: 4,
        selectionStart: 4,
        value: "@src",
      },
    })
    const option = await screen.findByRole("option", { name: /src\/app\.ts/ })
    fireEvent.mouseDown(option)

    await waitFor(() => {
      expect(textarea).toHaveValue("@{src/app.ts} ")
      const chip = screen.getByRole("button", { name: "Remove workspace file src/app.ts" })
      expect(chip).toBeInTheDocument()
      expect(chip.parentElement).toHaveClass("hidden", "sm:flex")
      expect(chip.compareDocumentPosition(textarea) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
        Node.DOCUMENT_POSITION_FOLLOWING
      )
    })

    fireEvent.click(screen.getByRole("button", { name: "Send message" }))

    await waitFor(() => {
      expect(onSearchWorkspaceFiles).toHaveBeenCalledWith("src")
      expect(onSubmitDraft).toHaveBeenCalledWith(
        "@{src/app.ts}",
        [],
        ["src/app.ts"],
        expect.stringMatching(/^client_/)
      )
    })
  })

  it("drops workspace chips and submit paths when the marker is deleted", async () => {
    const fixture = loadStudioMock()
    const onSearchWorkspaceFiles = vi.fn().mockResolvedValue([
      {
        filename: "app.ts",
        media_type: "text/plain",
        path: "src/app.ts",
        size_bytes: 12,
      },
    ])
    const onSubmitDraft = vi.fn()
    localStorage.clear()

    renderChatPanel({
      onSearchWorkspaceFiles,
      onSubmitDraft,
      state: fixture.state,
    })

    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
    fireEvent.change(textarea, {
      target: {
        selectionEnd: 4,
        selectionStart: 4,
        value: "@src",
      },
    })
    fireEvent.mouseDown(await screen.findByRole("option", { name: /src\/app\.ts/ }))

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Remove workspace file src/app.ts" })).toBeInTheDocument()
    )

    fireEvent.change(textarea, {
      target: {
        selectionEnd: 5,
        selectionStart: 5,
        value: "hello",
      },
    })

    expect(screen.queryByRole("button", { name: "Remove workspace file src/app.ts" })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Send message" }))

    await waitFor(() =>
      expect(onSubmitDraft).toHaveBeenCalledWith(
        "hello",
        [],
        [],
        expect.stringMatching(/^client_/)
      )
    )
  })

  it("removes the workspace marker when its chip is removed", async () => {
    const fixture = loadStudioMock()
    const onSearchWorkspaceFiles = vi.fn().mockResolvedValue([
      {
        filename: "app.ts",
        media_type: "text/plain",
        path: "src/app.ts",
        size_bytes: 12,
      },
    ])
    localStorage.clear()

    renderChatPanel({
      onSearchWorkspaceFiles,
      state: fixture.state,
    })

    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
    fireEvent.change(textarea, {
      target: {
        selectionEnd: 4,
        selectionStart: 4,
        value: "@src",
      },
    })
    fireEvent.mouseDown(await screen.findByRole("option", { name: /src\/app\.ts/ }))

    const chip = await screen.findByRole("button", { name: "Remove workspace file src/app.ts" })
    fireEvent.click(chip)

    expect(textarea).toHaveValue("")
    expect(screen.queryByRole("button", { name: "Remove workspace file src/app.ts" })).not.toBeInTheDocument()
  })

  it("renders restored workspace chips from draft markers", async () => {
    const fixture = loadStudioMock()
    const onSearchWorkspaceFiles = vi.fn().mockResolvedValue([
      {
        filename: "app.ts",
        media_type: "text/plain",
        path: "src/app.ts",
        size_bytes: 12,
      },
    ])
    const state: StudioState = {
      ...fixture.state,
      ui_state: {
        ...fixture.state.ui_state,
        draft_content: "please review @{src/app.ts}",
      },
    }
    localStorage.clear()

    renderChatPanel({
      liveApi: true,
      onSearchWorkspaceFiles,
      state,
    })

    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
    await waitFor(() => {
      expect(textarea).toHaveValue("please review @{src/app.ts}")
      expect(screen.getByRole("button", { name: "Remove workspace file src/app.ts" })).toBeInTheDocument()
    })
    await waitFor(() => expect(onSearchWorkspaceFiles).toHaveBeenCalledWith("src/app.ts"))
  })

  it("preserves selected workspace files when submit fails", async () => {
    const fixture = loadStudioMock()
    const onSearchWorkspaceFiles = vi.fn().mockResolvedValue([
      {
        filename: "notes.md",
        media_type: "text/markdown",
        path: "docs/notes.md",
        size_bytes: 20,
      },
    ])
    localStorage.clear()

    renderChatPanel({
      onSearchWorkspaceFiles,
      onSubmitDraft: async () => {
        throw new Error("offline")
      },
      state: fixture.state,
    })

    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
    fireEvent.change(textarea, {
      target: {
        selectionEnd: 5,
        selectionStart: 5,
        value: "@docs",
      },
    })
    fireEvent.mouseDown(await screen.findByRole("option", { name: /docs\/notes\.md/ }))
    fireEvent.click(screen.getByRole("button", { name: "Send message" }))

    await waitFor(() => {
      expect(textarea).toHaveValue("@{docs/notes.md} ")
      expect(screen.getByRole("button", { name: "Remove workspace file docs/notes.md" })).toBeInTheDocument()
    })
  })

  it("does not insert stale file references when Enter is pressed after autocomplete closes", async () => {
    const fixture = loadStudioMock()
    const onSearchWorkspaceFiles = vi.fn().mockResolvedValue([
      {
        filename: "app.ts",
        media_type: "text/plain",
        path: "src/app.ts",
        size_bytes: 12,
      },
    ])
    localStorage.clear()

    renderChatPanel({
      onSearchWorkspaceFiles,
      state: fixture.state,
    })

    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement
    fireEvent.change(textarea, {
      target: {
        selectionEnd: 1,
        selectionStart: 1,
        value: "@",
      },
    })
    await screen.findByRole("option", { name: /src\/app\.ts/ })

    fireEvent.change(textarea, {
      target: {
        selectionEnd: 5,
        selectionStart: 5,
        value: "hello",
      },
    })
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument())

    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true })

    expect(textarea).toHaveValue("hello")
    expect(screen.queryByRole("button", { name: "Remove workspace file src/app.ts" })).not.toBeInTheDocument()
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
        onPersistUiState={() => undefined}
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
      onNewChat={() => undefined}
      onDraftTeamChange={() => undefined}
      onToggleCollapsed={() => undefined}
      session={null}
      teams={null}
      {...props}
    />
  )
}

function installMatchMedia(matches: boolean) {
  const descriptor = Object.getOwnPropertyDescriptor(window, "matchMedia")
  let currentMatches = matches
  const listeners = new Set<() => void>()
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn((query: string): MediaQueryList => ({
      addEventListener: (_event: string, listener: () => void) => {
        listeners.add(listener)
      },
      addListener: (listener: () => void) => {
        listeners.add(listener)
      },
      dispatchEvent: () => true,
      matches: currentMatches,
      media: query,
      onchange: null,
      removeEventListener: (_event: string, listener: () => void) => {
        listeners.delete(listener)
      },
      removeListener: (listener: () => void) => {
        listeners.delete(listener)
      },
    } as unknown as MediaQueryList)),
  })
  return {
    restore() {
      if (descriptor) {
        Object.defineProperty(window, "matchMedia", descriptor)
      } else {
        delete (window as Partial<Window>).matchMedia
      }
    },
    setMatches(nextMatches: boolean) {
      currentMatches = nextMatches
      act(() => {
        for (const listener of listeners) {
          listener()
        }
      })
    },
  }
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
    const pendingAction = screen.getByRole("button", {
      name: /Open action custom_tool/,
    })

    expect(completedGroup).toHaveAttribute("aria-expanded", "false")
    expect(pendingAction).toHaveAttribute("aria-expanded", "false")
    expect(
      screen.queryByRole("button", { name: "1 action en cours" })
    ).not.toBeInTheDocument()
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

  it("uses matching tool messages to complete pending tool calls", () => {
    render(
      <ToolCallList
        resultByToolCallId={
          new Map([["call_time", "2026-06-11T12:09:04+02:00"]])
        }
        value={[
          {
            id: "call_time",
            name: "get_current_time",
            args: { timezone: "Europe/Paris" },
          },
          {
            id: "call_missing",
            name: "get_current_time",
            args: { timezone: "UTC" },
          },
        ]}
      />
    )

    const completedAction = screen.getByRole("button", {
      name: /Open action get_current_time .*Europe\/Paris/,
    })
    const pendingAction = screen.getByRole("button", {
      name: /Open action get_current_time .*UTC/,
    })

    expect(completedAction).toBeInTheDocument()
    expect(pendingAction).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "1 action effectuée" })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "1 action en cours" })
    ).not.toBeInTheDocument()

    fireEvent.click(completedAction)

    expect(screen.getByText("2026-06-11T12:09:04+02:00")).toBeInTheDocument()
  })
})
