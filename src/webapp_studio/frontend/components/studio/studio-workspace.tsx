"use client"

import type { MouseEvent as ReactMouseEvent } from "react"
import {
  useEffect,
  useMemo,
  useReducer,
  useState,
  useSyncExternalStore,
  useTransition,
} from "react"
import type { FileUIPart } from "ai"
import { CircleAlertIcon } from "lucide-react"

import { ChatPanel } from "@/components/studio/chat-panel"
import {
  type InspectorView,
  type OpenInspectorView,
  RightInspector,
} from "@/components/studio/right-inspector"
import { StudioSidebar } from "@/components/studio/studio-sidebar"
import type {
  ConversationList,
  GeneratedUiSpec,
  InterruptRequest,
  StudioChanges,
  StudioFileItem,
  StudioSession,
  StudioState,
  StudioTeamDescriptor,
  StudioTeams,
  StudioWorkspaceFileItem,
} from "@/lib/studio/schemas"
import { StudioApiClient } from "@/lib/studio/api-client"
import { studioReducer } from "@/lib/studio/reducer"
import { useStudioStream } from "@/lib/studio/use-studio-stream"

type StudioWorkspaceProps = {
  initialState: StudioState
  generatedUi: GeneratedUiSpec[]
  liveApi: boolean
  teams?: StudioTeams | null
}

const LEFT_MIN = 238
const LEFT_MAX = 518
const RIGHT_MIN = 318
const RIGHT_MAX = 875
const SIDEBAR_RAIL = 56
const LEFT_WIDTH_KEY = "webapp-studio:v1:panel:left-width"
const RIGHT_WIDTH_KEY = "webapp-studio:v1:panel:right-width"

export function StudioWorkspace({
  initialState,
  generatedUi,
  liveApi,
  teams: initialTeams = null,
}: StudioWorkspaceProps) {
  const [state, dispatch] = useReducer(studioReducer, initialState)
  const [teams, setTeams] = useState<StudioTeams | null>(initialTeams)
  const [changes, setChanges] = useState<StudioChanges | null>(null)
  const [conversationList, setConversationList] = useState<ConversationList | null>(null)
  const [files, setFiles] = useState<StudioFileItem[]>([])
  const [inspectorView, setInspectorView] = useState<InspectorView>({ kind: "empty" })
  const [lastInspectorView, setLastInspectorView] = useState<OpenInspectorView | null>(null)
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [leftWidth, setLeftWidth] = usePersistentNumber(LEFT_WIDTH_KEY, 288, LEFT_MIN, LEFT_MAX)
  const [rightWidth, setRightWidth] = usePersistentNumber(RIGHT_WIDTH_KEY, 420, RIGHT_MIN, RIGHT_MAX)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [session, setSession] = useState<StudioSession | null>(null)
  const [isPending, startTransition] = useTransition()
  const draftMode = state.conversation_id === ""
  const visibleGeneratedUi = liveApi ? state.generated_ui : generatedUi
  const stateFiles = useMemo(
    () => filesFromState(state),
    [state]
  )
  const apiClient = useMemo(
    () => (liveApi ? new StudioApiClient() : null),
    [liveApi]
  )
  const streamStatus = useStudioStream(liveApi && !draftMode, dispatch, setOperationError)
  const narrowLayout = useMediaQuery("(max-width: 900px)")

  useEffect(() => {
    if (!apiClient) {
      return
    }
    let cancelled = false
    const requests = draftMode
      ? Promise.all([
          apiClient.teams(),
          apiClient.session(),
          apiClient.conversations(),
        ]).then(([nextTeams, nextSession, nextConversations]) => ({
          nextTeams,
          nextSession,
          nextConversations,
          nextFiles: { files: [] },
          nextChanges: null,
        }))
      : Promise.all([
          apiClient.teams(),
          apiClient.session(),
          apiClient.conversations(),
          apiClient.files(),
          apiClient.changes(),
        ]).then(([nextTeams, nextSession, nextConversations, nextFiles, nextChanges]) => ({
          nextTeams,
          nextSession,
          nextConversations,
          nextFiles,
          nextChanges,
        }))
    requests
      .then(({ nextTeams, nextSession, nextConversations, nextFiles, nextChanges }) => {
        if (cancelled) {
          return
        }
        setTeams(nextTeams)
        setSession(nextSession)
        setConversationList(nextConversations)
        setFiles(nextFiles.files)
        setChanges(nextChanges)
      })
      .catch((error) => {
        if (!cancelled) {
          setOperationError(error instanceof Error ? error.message : "Studio API request failed.")
        }
      })
    return () => {
      cancelled = true
    }
  }, [apiClient, draftMode, state.conversation_id])

  function replaceStateFromLiveApi(action: () => Promise<StudioState>) {
    if (!apiClient) {
      return
    }
    const previousState = state
    startTransition(async () => {
      try {
        setOperationError(null)
        dispatch({ type: "state.replaced", state: await action() })
        await refreshAuxiliaryData()
      } catch (error) {
        dispatch({ type: "state.replaced", state: previousState })
        setOperationError(
          error instanceof Error ? error.message : "Studio API request failed."
        )
      }
    })
  }

  async function refreshAuxiliaryData() {
    if (!apiClient) {
      return
    }
    const [nextTeams, nextSession, nextConversations] = await Promise.all([
      apiClient.teams(),
      apiClient.session(),
      apiClient.conversations(),
    ])
    setTeams(nextTeams)
    setSession(nextSession)
    setConversationList(nextConversations)
    if (state.conversation_id) {
      const [nextFiles, nextChanges] = await Promise.all([
        apiClient.files(),
        apiClient.changes(),
      ])
      setFiles(nextFiles.files)
      setChanges(nextChanges)
    } else {
      setFiles([])
      setChanges(null)
    }
  }

  function handleRuntimeChange(mentionHookEnabled: boolean) {
    dispatch({
      type: "runtime.updated",
      runtime: {
        mention_hook_enabled: mentionHookEnabled,
      },
    })
    replaceStateFromLiveApi(() =>
      apiClient!.updateRuntime({ mention_hook_enabled: mentionHookEnabled })
    )
  }

  function handleCascadeLimitChange(value: number | null) {
    dispatch({
      type: "runtime.updated",
      runtime: {
        max_cascade_turns: value,
      },
    })
    replaceStateFromLiveApi(() =>
      apiClient!.updateRuntime({ max_cascade_turns: value })
    )
  }

  async function handleSubmitDraft(
    content: string,
    draftFiles: FileUIPart[],
    workspacePaths: string[],
    clientMessageId: string
  ) {
    dispatch({
      type: "message.optimistic_append",
      authorId: "human",
      clientMessageId,
      content,
    })
    if (!apiClient) {
      return
    }
    try {
      setOperationError(null)
      if (draftMode) {
        const result = await apiClient!.createConversation(
          state.team_id,
          content,
          draftFiles,
          workspacePaths,
          clientMessageId
        )
        setSession(result.session)
        dispatch({ type: "state.replaced", state: result.state })
      } else {
        await apiClient!.appendMessage(content, draftFiles, workspacePaths, clientMessageId)
        dispatch({ type: "state.replaced", state: await apiClient!.state() })
      }
      await refreshAuxiliaryData()
    } catch (error) {
      dispatch({ type: "message.optimistic_failed", clientMessageId })
      setOperationError(
        error instanceof Error ? error.message : "Studio API request failed."
      )
      throw error
    }
  }

  async function handleSearchWorkspaceFiles(query: string): Promise<StudioWorkspaceFileItem[]> {
    if (!apiClient) {
      return []
    }
    const result = await apiClient.workspaceFiles(query)
    return result.files
  }

  async function handleEditMessage(messageId: string, content: string) {
    if (!apiClient) {
      return
    }
    try {
      setOperationError(null)
      dispatch({ type: "state.replaced", state: await apiClient.editMessage(messageId, content) })
      await refreshAuxiliaryData()
    } catch (error) {
      setOperationError(
        error instanceof Error ? error.message : "Studio API request failed."
      )
      throw error
    }
  }

  function handlePersistUiState(input: {
    branchId: string
    draftContent: string
    editingEventId: string | null
    outboxState: {
      clientMessageId: string
      content: string
      createdAt: string
      fileNames: string[]
      status: "sending" | "failed"
    }[]
  }) {
    if (!apiClient) {
      return
    }
    apiClient.updateUiState(input).catch((error) => {
      setOperationError(
        error instanceof Error ? error.message : "Studio API request failed."
      )
    })
  }

  function handleStopAgent(agentId: string) {
    replaceStateFromLiveApi(() => apiClient!.stopAgent(agentId))
  }

  function handleCancelQueueItem(queueItemId: string) {
    replaceStateFromLiveApi(async () => {
      await apiClient!.cancelQueueItem(queueItemId)
      return apiClient!.state()
    })
  }

  function handleClearQueue(scope: "failed" | "pending" | "all") {
    replaceStateFromLiveApi(async () => {
      await apiClient!.clearQueue(scope)
      return apiClient!.state()
    })
  }

  function handleCreateBranchFromCheckpoint(checkpointId: string) {
    replaceStateFromLiveApi(async () => {
      await apiClient!.createBranch({
        checkpointId,
        label: `Branch ${state.history.branches.length}`,
      })
      return apiClient!.state()
    })
  }

  function handleSwitchBranch(branchId: string) {
    replaceStateFromLiveApi(async () => {
      await apiClient!.switchBranch(branchId)
      return apiClient!.state()
    })
  }

  function handleSwitchConversation(conversationId: string) {
    if (!apiClient) {
      return
    }
    startTransition(async () => {
      try {
        setOperationError(null)
        const result = await apiClient.switchConversation(conversationId)
        setSession(result.session)
        dispatch({ type: "state.replaced", state: result.state })
        await refreshAuxiliaryData()
      } catch (error) {
        setOperationError(error instanceof Error ? error.message : "Studio API request failed.")
      }
    })
  }

  function handleSwitchTeamConversation(teamId: string, conversationId: string) {
    if (!apiClient) {
      return
    }
    startTransition(async () => {
      try {
        setOperationError(null)
        const result = await apiClient.switchConversation(conversationId, teamId)
        setSession(result.session)
        dispatch({ type: "state.replaced", state: result.state })
        await refreshAuxiliaryData()
      } catch (error) {
        setOperationError(error instanceof Error ? error.message : "Studio API request failed.")
      }
    })
  }

  function handleNewChat() {
    const team = preferredDraftTeam(teams, state.team_id)
    if (!team) {
      return
    }
    setFiles([])
    setChanges(null)
    dispatch({ type: "state.replaced", state: emptyStudioState(team) })
  }

  function handleDraftTeamChange(teamId: string) {
    if (!draftMode) {
      return
    }
    const team = teams?.teams.find((item) => item.team_id === teamId)
    if (team) {
      dispatch({ type: "state.replaced", state: emptyStudioState(team) })
    }
  }

  function handleResumeCheckpoint(checkpointId: string) {
    replaceStateFromLiveApi(() => apiClient!.resumeCheckpoint(checkpointId))
  }

  function handleRegenerateCheckpoint(checkpointId: string) {
    replaceStateFromLiveApi(() =>
      apiClient!.resumeCheckpoint(checkpointId, { mode: "regenerate" })
    )
  }

  function handleEditCheckpoint(checkpointId: string, editedContent: string) {
    replaceStateFromLiveApi(() =>
      apiClient!.resumeCheckpoint(checkpointId, {
        editedContent,
        mode: "edit",
      })
    )
  }

  function handleResumeInterrupt(
    interruptId: string,
    decision: "approve" | "reject" | "edit" | "respond",
    input: {
      response?: string
      editedPayload?: InterruptRequest["payload"]
    } = {}
  ) {
    replaceStateFromLiveApi(() =>
      apiClient!.resumeInterrupt(interruptId, {
        decision,
        response: input.response,
        editedPayload: input.editedPayload,
      })
    )
  }

  function beginResize(side: "left" | "right", startEvent: ReactMouseEvent<HTMLDivElement>) {
    startEvent.preventDefault()
    const startX = startEvent.clientX
    const initial = side === "left" ? leftWidth : rightWidth
    function onMove(event: MouseEvent) {
      const delta = event.clientX - startX
      if (side === "left") {
        setLeftWidth(clamp(initial + delta, LEFT_MIN, LEFT_MAX))
      } else {
        setRightWidth(clamp(initial - delta, RIGHT_MIN, RIGHT_MAX))
      }
    }
    function onUp() {
      window.removeEventListener("mousemove", onMove)
      window.removeEventListener("mouseup", onUp)
    }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
  }

  function handleOpenInspector(view: InspectorView) {
    setInspectorView(view)
    if (view.kind !== "empty") {
      setLastInspectorView(view)
    }
    if (narrowLayout) {
      setMobileSidebarOpen(false)
    }
  }

  function handleRestoreInspector() {
    handleOpenInspector(lastInspectorView ?? fallbackInspectorView(narrowLayout, state))
  }

  const inspectorOpen = inspectorView.kind !== "empty"
  const inspectorPlacement = narrowLayout ? "sheet" : "side"
  const effectiveLeftCollapsed = narrowLayout || leftCollapsed
  const leftColumn = effectiveLeftCollapsed ? SIDEBAR_RAIL : leftWidth
  const leftSplitterColumn = narrowLayout ? 0 : 6
  const rightSplitterColumn = narrowLayout || !inspectorOpen ? 0 : 6
  const rightColumn = narrowLayout || !inspectorOpen ? 0 : rightWidth
  const centerMin = narrowLayout ? "0" : "24rem"
  const gridTemplateColumns = `${leftColumn}px ${leftSplitterColumn}px minmax(${centerMin},1fr) ${rightSplitterColumn}px ${rightColumn}px`
  const sidebarProps = {
    busy: isPending,
    conversationList,
    liveApi,
    onCancelQueueItem: handleCancelQueueItem,
    onCascadeLimitChange: handleCascadeLimitChange,
    onClearQueue: handleClearQueue,
    onCreateBranchFromCheckpoint: handleCreateBranchFromCheckpoint,
    onEditCheckpoint: handleEditCheckpoint,
    onOpenInspector: handleOpenInspector,
    onRegenerateCheckpoint: handleRegenerateCheckpoint,
    onResumeCheckpoint: handleResumeCheckpoint,
    onResumeInterrupt: handleResumeInterrupt,
    onRuntimeChange: handleRuntimeChange,
    onStopAgent: handleStopAgent,
    onSwitchBranch: handleSwitchBranch,
    onSwitchConversation: handleSwitchTeamConversation,
    onNewChat: handleNewChat,
    onDraftTeamChange: handleDraftTeamChange,
    session,
    state,
    teams,
  }
  const inspector = (
    <RightInspector
      apiClient={apiClient}
      changes={changes}
      files={files.length ? files : stateFiles}
      generatedUi={visibleGeneratedUi}
      onClose={() => setInspectorView({ kind: "empty" })}
      onViewChange={handleOpenInspector}
      placement={inspectorPlacement}
      session={session}
      state={state}
      view={inspectorView}
    />
  )
  const duplicateTeamCount = teams?.duplicate_ids.length ?? 0

  return (
    <main className="relative h-svh min-h-svh overflow-hidden bg-background">
      <div
        className="relative grid h-full min-h-0 transition-[grid-template-columns] duration-200 ease-out motion-reduce:transition-none"
        data-testid="studio-layout-grid"
        style={{
          gridTemplateColumns,
        }}
      >
        <StudioSidebar
          {...sidebarProps}
          collapsed={effectiveLeftCollapsed}
          onToggleCollapsed={() => {
            if (narrowLayout) {
              setMobileSidebarOpen(true)
            } else {
              setLeftCollapsed((value) => !value)
            }
          }}
        />

        <Splitter
          disabled={effectiveLeftCollapsed}
          hidden={narrowLayout}
          label="Resize sidebar"
          onMouseDown={(event) => beginResize("left", event)}
        />

        <div className="relative min-h-0 min-w-0">
          {operationError || duplicateTeamCount ? (
            <div className="absolute left-3 right-3 top-3 z-20 grid gap-2">
              {operationError ? (
                <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 shadow" role="alert">
                  <CircleAlertIcon className="size-4 shrink-0" />
                  <span>{operationError}</span>
                </div>
              ) : null}
              {duplicateTeamCount ? (
                <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 shadow" role="status">
                  <CircleAlertIcon className="size-4 shrink-0" />
                  <span>{duplicateTeamCount} duplicate team id collision{duplicateTeamCount === 1 ? "" : "s"} hidden.</span>
                </div>
              ) : null}
            </div>
          ) : null}
          <ChatPanel
            busy={isPending}
            changes={changes}
            inspectorOpen={inspectorOpen}
            inspectorPlacement={inspectorPlacement}
            liveApi={liveApi}
            onEditMessage={handleEditMessage}
            onOpenInspector={handleOpenInspector}
            onPersistUiState={handlePersistUiState}
            onRestoreInspector={handleRestoreInspector}
            onSearchWorkspaceFiles={handleSearchWorkspaceFiles}
            onSubmitDraft={handleSubmitDraft}
            onSwitchBranch={handleSwitchBranch}
            session={session}
            state={state}
            streamStatus={streamStatus}
          />
        </div>

        <Splitter
          disabled={!inspectorOpen}
          hidden={narrowLayout || !inspectorOpen}
          label="Resize inspector"
          onMouseDown={(event) => beginResize("right", event)}
        />

        <div
          aria-hidden={!inspectorOpen}
          className={
            narrowLayout
              ? `absolute inset-x-0 bottom-0 z-30 overflow-hidden bg-background shadow-2xl transition-transform duration-200 ease-out motion-reduce:transition-none ${
                  inspectorOpen ? "translate-y-0" : "pointer-events-none translate-y-full"
                }`
              : `min-h-0 min-w-0 overflow-hidden transition-opacity duration-200 ease-out motion-reduce:transition-none ${
                  inspectorOpen ? "opacity-100" : "pointer-events-none opacity-0"
                }`
          }
          data-testid="right-inspector-shell"
          inert={!inspectorOpen ? true : undefined}
          style={narrowLayout ? { height: "min(76svh, 44rem)" } : undefined}
        >
          {inspector}
        </div>
      </div>

      <div
        aria-hidden={!mobileSidebarOpen}
        aria-label="Sidebar drawer"
        className={`absolute inset-0 z-40 bg-black/20 transition-opacity duration-200 ease-out motion-reduce:transition-none ${
          mobileSidebarOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        inert={!mobileSidebarOpen ? true : undefined}
        onClick={() => setMobileSidebarOpen(false)}
        role="presentation"
      >
        <div
          className={`h-full max-w-[518px] bg-background shadow-2xl transition-transform duration-200 ease-out motion-reduce:transition-none ${
            mobileSidebarOpen ? "translate-x-0" : "-translate-x-full"
          }`}
          onClick={(event) => event.stopPropagation()}
          style={{ width: "min(32rem, calc(100vw - 2rem))" }}
        >
          <StudioSidebar
            {...sidebarProps}
            collapsed={false}
            onToggleCollapsed={() => setMobileSidebarOpen(false)}
          />
        </div>
      </div>
    </main>
  )
}

function Splitter({
  disabled,
  hidden,
  label,
  onMouseDown,
}: {
  disabled?: boolean
  hidden?: boolean
  label: string
  onMouseDown: (event: ReactMouseEvent<HTMLDivElement>) => void
}) {
  return (
    <div
      aria-disabled={disabled}
      aria-hidden={hidden}
      aria-label={label}
      className={`h-full border-x bg-muted/30 transition-opacity duration-200 ease-out motion-reduce:transition-none ${
        disabled ? "cursor-default" : "cursor-col-resize hover:bg-muted"
      } ${hidden ? "pointer-events-none opacity-0" : "opacity-100"}`}
      inert={hidden ? true : undefined}
      onMouseDown={disabled ? undefined : onMouseDown}
      role="separator"
    />
  )
}

function usePersistentNumber(
  key: string,
  fallback: number,
  min: number,
  max: number
) {
  const [value, setValue] = useState(() =>
    readPersistentNumber(key, fallback, min, max)
  )

  useEffect(() => {
    localStorage.setItem(key, String(clamp(value, min, max)))
  }, [key, max, min, value])

  return [value, setValue] as const
}

function readPersistentNumber(
  key: string,
  fallback: number,
  min: number,
  max: number
) {
  if (typeof window === "undefined") {
    return fallback
  }
  const stored = Number(localStorage.getItem(key))
  return Number.isFinite(stored) ? clamp(stored, min, max) : fallback
}

function useMediaQuery(query: string) {
  return useSyncExternalStore(
    (callback) => subscribeToMediaQuery(query, callback),
    () => mediaQuerySnapshot(query),
    () => false
  )
}

function subscribeToMediaQuery(query: string, callback: () => void) {
  const mediaQuery = window.matchMedia(query)
  mediaQuery.addEventListener("change", callback)
  return () => mediaQuery.removeEventListener("change", callback)
}

function mediaQuerySnapshot(query: string) {
  return typeof window !== "undefined" && window.matchMedia(query).matches
}

function filesFromState(state: StudioState): StudioFileItem[] {
  return state.conversation.events.flatMap((event) =>
    event.attachments.map((attachment) => {
      const preview = previewForAttachment(
        attachment.id,
        attachment.filename,
        attachment.media_type,
        attachment.size_bytes
      )
      return {
        id: attachment.id,
        filename: attachment.filename,
        media_type: mediaTypeForAttachment(attachment.filename, attachment.media_type),
        size_bytes: attachment.size_bytes,
        added_by: attachment.added_by,
        event_id: event.id,
        event_seq: event.seq,
        preview_mode: preview.mode,
        preview_url: preview.url,
        download_url: `/api/studio/v1/files/${attachment.id}/download`,
      }
    })
  )
}

const framePreviewMediaTypes = new Set(["application/pdf"])
const framePreviewMediaPrefixes = ["audio/", "image/", "video/"]
const textPreviewLimitBytes = 500 * 1024
type PreviewMode = "iframe" | "text"
const textPreviewMediaTypes = new Set(["application/json"])
const blockedPreviewMediaTypes = new Set(["application/javascript", "image/svg+xml", "text/html", "text/javascript"])
const blockedPreviewSuffixes = [".htm", ".html", ".js", ".mjs", ".svg"]
const filenameMediaTypes = new Map([
  [".markdown", "text/markdown"],
  [".md", "text/markdown"],
  [".mdc", "text/markdown"],
  [".mdown", "text/markdown"],
  [".mkd", "text/markdown"],
])

function previewForAttachment(
  fileId: string,
  filename: string,
  mediaType: string | null,
  sizeBytes: number | null
) {
  const mode = previewModeForAttachment(filename, mediaType, sizeBytes)
  return {
    mode,
    url: mode ? `/api/studio/v1/files/${fileId}/preview` : null,
  }
}

function previewModeForAttachment(
  filename: string,
  mediaType: string | null,
  sizeBytes: number | null
): PreviewMode | null {
  const normalizedMediaType = mediaTypeForAttachment(filename, mediaType)
  const normalizedFilename = filename.toLowerCase()
  if (
    !normalizedMediaType ||
    blockedPreviewMediaTypes.has(normalizedMediaType) ||
    blockedPreviewSuffixes.some((suffix) => normalizedFilename.endsWith(suffix))
  ) {
    return null
  }
  if (isTextPreviewMediaType(normalizedMediaType)) {
    return sizeBytes !== null && sizeBytes <= textPreviewLimitBytes ? "text" : null
  }
  return framePreviewMediaTypes.has(normalizedMediaType) ||
    framePreviewMediaPrefixes.some((prefix) => normalizedMediaType.startsWith(prefix))
    ? "iframe"
    : null
}

function mediaTypeForAttachment(filename: string, mediaType: string | null) {
  const normalizedMediaType = mediaType?.split(";", 1)[0]?.trim().toLowerCase() || null
  return normalizedMediaType ?? filenameMediaTypes.get(fileExtension(filename)) ?? null
}

function fileExtension(filename: string) {
  const dotIndex = filename.lastIndexOf(".")
  return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : ""
}

function isTextPreviewMediaType(mediaType: string) {
  return textPreviewMediaTypes.has(mediaType) || mediaType.startsWith("text/")
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function preferredDraftTeam(teams: StudioTeams | null, currentTeamId: string) {
  if (!teams || teams.status !== "ready") {
    return null
  }
  return (
    teams.teams.find((team) => team.team_id === currentTeamId) ??
    teams.teams[0] ??
    null
  )
}

function fallbackInspectorView(narrowLayout: boolean, state: StudioState): OpenInspectorView {
  if (narrowLayout && state.activity.active_agent_ids.length === 0) {
    return { kind: "files" }
  }
  return { kind: "activity" }
}

export function emptyStudioState(team: StudioTeamDescriptor): StudioState {
  const now = new Date().toISOString()
  return {
    team_id: team.team_id,
    conversation_id: "",
    participants: team.participants,
    participant_aliases: team.participant_aliases,
    runtime: {
      team_id: team.team_id,
      conversation_id: "",
      mention_hook_enabled: true,
      max_cascade_turns: null,
    },
    conversation: {
      events: [],
      deliveries: [],
      runs: [],
      model_attempts: [],
      agent_states: [],
      branch_threads: [],
      thread_frontiers: [],
      control_events: [],
      external_side_effects: [],
    },
    activity: {
      active_agent_ids: [],
      private_threads: [],
    },
    runs: [],
    queue: [],
    interrupts: [],
    history: {
      current_branch_id: "branch_main",
      checkpoints: [],
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
          created_at: now,
          current: true,
          status: "persisted",
          head_checkpoint_id: null,
          archived_at: null,
        },
      ],
    },
    ui_state: {
      team_id: team.team_id,
      conversation_id: "",
      branch_id: "branch_main",
      participant_id: "human",
      draft_content: "",
      outbox_state: [],
      editing_event_id: null,
      selected_agent_id: null,
      scroll_anchor_event_id: null,
      updated_at: now,
    },
    generated_ui: [],
  }
}
