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
} from "@/lib/studio/schemas"
import { StudioApiClient } from "@/lib/studio/api-client"
import { studioReducer } from "@/lib/studio/reducer"
import { useStudioStream } from "@/lib/studio/use-studio-stream"

type StudioWorkspaceProps = {
  initialState: StudioState
  generatedUi: GeneratedUiSpec[]
  liveApi: boolean
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
}: StudioWorkspaceProps) {
  const [state, dispatch] = useReducer(studioReducer, initialState)
  const [changes, setChanges] = useState<StudioChanges | null>(null)
  const [conversationList, setConversationList] = useState<ConversationList | null>(null)
  const [files, setFiles] = useState<StudioFileItem[]>([])
  const [inspectorView, setInspectorView] = useState<InspectorView>({ kind: "empty" })
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [leftWidth, setLeftWidth] = usePersistentNumber(LEFT_WIDTH_KEY, 288, LEFT_MIN, LEFT_MAX)
  const [rightWidth, setRightWidth] = usePersistentNumber(RIGHT_WIDTH_KEY, 420, RIGHT_MIN, RIGHT_MAX)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [session, setSession] = useState<StudioSession | null>(null)
  const [isPending, startTransition] = useTransition()
  const visibleGeneratedUi = liveApi ? state.generated_ui : generatedUi
  const stateFiles = useMemo(
    () => filesFromState(state),
    [state]
  )
  const apiClient = useMemo(
    () => (liveApi ? new StudioApiClient() : null),
    [liveApi]
  )
  const streamStatus = useStudioStream(liveApi, dispatch, setOperationError)
  const narrowLayout = useMediaQuery("(max-width: 900px)")

  useEffect(() => {
    if (!apiClient) {
      return
    }
    let cancelled = false
    Promise.all([
      apiClient.session(),
      apiClient.conversations(),
      apiClient.files(),
      apiClient.changes(),
    ])
      .then(([nextSession, nextConversations, nextFiles, nextChanges]) => {
        if (cancelled) {
          return
        }
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
  }, [apiClient, state.conversation_id])

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
    const [nextSession, nextConversations, nextFiles, nextChanges] = await Promise.all([
      apiClient.session(),
      apiClient.conversations(),
      apiClient.files(),
      apiClient.changes(),
    ])
    setSession(nextSession)
    setConversationList(nextConversations)
    setFiles(nextFiles.files)
    setChanges(nextChanges)
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
      await apiClient!.appendMessage(content, draftFiles, clientMessageId)
      dispatch({ type: "state.replaced", state: await apiClient!.state() })
      await refreshAuxiliaryData()
    } catch (error) {
      dispatch({ type: "message.optimistic_failed", clientMessageId })
      setOperationError(
        error instanceof Error ? error.message : "Studio API request failed."
      )
      throw error
    }
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
    if (narrowLayout) {
      setMobileSidebarOpen(false)
    }
  }

  const leftColumn = leftCollapsed ? SIDEBAR_RAIL : leftWidth
  const inspectorOpen = inspectorView.kind !== "empty"
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
    onSwitchConversation: handleSwitchConversation,
    session,
    state,
  }
  const inspector = (
    <RightInspector
      apiClient={apiClient}
      changes={changes}
      files={files.length ? files : stateFiles}
      generatedUi={visibleGeneratedUi}
      onClose={() => setInspectorView({ kind: "empty" })}
      onViewChange={handleOpenInspector}
      session={session}
      state={state}
      view={inspectorView}
    />
  )

  if (narrowLayout) {
    return (
      <main className="relative h-svh min-h-svh overflow-hidden bg-background">
        <div
          className="grid h-full min-h-0"
          style={{
            gridTemplateColumns: `${SIDEBAR_RAIL}px minmax(0,1fr)`,
          }}
        >
          <StudioSidebar
            {...sidebarProps}
            collapsed
            onToggleCollapsed={() => setMobileSidebarOpen(true)}
          />

          <div className="relative min-h-0 min-w-0">
            {operationError ? (
              <div className="absolute left-3 right-3 top-3 z-20 flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 shadow" role="alert">
                <CircleAlertIcon className="size-4 shrink-0" />
                <span>{operationError}</span>
              </div>
            ) : null}
            <ChatPanel
              busy={isPending}
              changes={changes}
              liveApi={liveApi}
              onEditMessage={handleEditMessage}
              onOpenInspector={handleOpenInspector}
              onPersistUiState={handlePersistUiState}
              onSubmitDraft={handleSubmitDraft}
              onSwitchBranch={handleSwitchBranch}
              session={session}
              state={state}
              streamStatus={streamStatus}
            />
          </div>
        </div>

        {mobileSidebarOpen ? (
          <div
            aria-label="Sidebar drawer"
            className="absolute inset-0 z-40 bg-black/20"
            onClick={() => setMobileSidebarOpen(false)}
            role="presentation"
          >
            <div
              className="h-full max-w-[518px] bg-background shadow-2xl"
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
        ) : null}

        {inspectorOpen ? (
          <div
            className="absolute inset-x-0 bottom-0 z-30 bg-background shadow-2xl"
            style={{ height: "min(76svh, 44rem)" }}
          >
            {inspector}
          </div>
        ) : null}
      </main>
    )
  }

  return (
    <main className="h-svh min-h-svh overflow-hidden bg-background">
      <div
        className="grid h-full min-h-0"
        style={{
          gridTemplateColumns: `${leftColumn}px 6px minmax(24rem,1fr) 6px ${rightWidth}px`,
        }}
      >
        <StudioSidebar
          {...sidebarProps}
          collapsed={leftCollapsed}
          onToggleCollapsed={() => setLeftCollapsed((value) => !value)}
        />

        <Splitter disabled={leftCollapsed} label="Resize sidebar" onMouseDown={(event) => beginResize("left", event)} />

        <div className="relative min-h-0 min-w-0">
          {operationError ? (
            <div className="absolute left-3 right-3 top-3 z-20 flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 shadow" role="alert">
              <CircleAlertIcon className="size-4 shrink-0" />
              <span>{operationError}</span>
            </div>
          ) : null}
          <ChatPanel
            busy={isPending}
            changes={changes}
            liveApi={liveApi}
            onEditMessage={handleEditMessage}
            onOpenInspector={handleOpenInspector}
            onPersistUiState={handlePersistUiState}
            onSubmitDraft={handleSubmitDraft}
            onSwitchBranch={handleSwitchBranch}
            session={session}
            state={state}
            streamStatus={streamStatus}
          />
        </div>

        <Splitter label="Resize inspector" onMouseDown={(event) => beginResize("right", event)} />

        {inspector}
      </div>
    </main>
  )
}

function Splitter({
  disabled,
  label,
  onMouseDown,
}: {
  disabled?: boolean
  label: string
  onMouseDown: (event: ReactMouseEvent<HTMLDivElement>) => void
}) {
  return (
    <div
      aria-disabled={disabled}
      aria-label={label}
      className={`h-full border-x bg-muted/30 ${disabled ? "cursor-default" : "cursor-col-resize hover:bg-muted"}`}
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
    event.attachments.map((attachment) => ({
      id: attachment.id,
      filename: attachment.filename,
      media_type: attachment.media_type,
      size_bytes: attachment.size_bytes,
      added_by: attachment.added_by,
      event_id: event.id,
      event_seq: event.seq,
      preview_url: `/api/studio/v1/files/${attachment.id}/preview`,
      download_url: `/api/studio/v1/files/${attachment.id}/download`,
    }))
  )
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}
