"use client"

import type { KeyboardEvent, ReactNode } from "react"
import { useEffect, useId, useMemo, useState } from "react"
import type { FileUIPart } from "ai"
import {
  ActivityIcon,
  AppWindowIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CopyIcon,
  FileTextIcon,
  GitCompareIcon,
  PaperclipIcon,
  PanelBottomOpenIcon,
  PanelRightOpenIcon,
  PencilIcon,
  SendIcon,
  XIcon,
} from "lucide-react"

import {
  Conversation,
  ConversationContent,
} from "@/components/ai-elements/conversation"
import {
  Message,
  MessageContent,
} from "@/components/ai-elements/message"
import {
  PromptInput,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  usePromptInputAttachments,
} from "@/components/ai-elements/prompt-input"
import type { InspectorView } from "@/components/studio/right-inspector"
import { RichMarkdown } from "@/components/studio/rich-markdown"
import { StatusPill } from "@/components/studio/status-pill"
import { Button } from "@/components/ui/button"
import {
  ButtonGroup,
  ButtonGroupText,
} from "@/components/ui/button-group"
import { Textarea } from "@/components/ui/textarea"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { StudioStreamStatus } from "@/lib/studio/use-studio-stream"
import type {
  ConversationEvent,
  StudioChanges,
  StudioSession,
  StudioState,
  StudioWorkspaceFileItem,
} from "@/lib/studio/schemas"

type LocalOutboxItem = {
  clientMessageId: string
  content: string
  createdAt: string
  fileNames: string[]
  status: "sending" | "failed"
  workspaceFiles: StudioWorkspaceFileItem[]
}

type ChatPanelProps = {
  busy: boolean
  changes: StudioChanges | null
  inspectorOpen?: boolean
  inspectorPlacement?: "sheet" | "side"
  liveApi: boolean
  onOpenInspector: (view: InspectorView) => void
  onEditMessage: (messageId: string, content: string) => Promise<void> | void
  onPersistUiState: (input: {
    branchId: string
    draftContent: string
    editingEventId: string | null
    outboxState: LocalOutboxItem[]
  }) => void
  onSubmitDraft: (
    content: string,
    files: FileUIPart[],
    workspacePaths: string[],
    clientMessageId: string
  ) => Promise<void> | void
  onRestoreInspector?: () => void
  onSearchWorkspaceFiles?: (query: string) => Promise<StudioWorkspaceFileItem[]> | StudioWorkspaceFileItem[]
  onSwitchBranch: (branchId: string) => Promise<void> | void
  session: StudioSession | null
  state: StudioState
  streamStatus: StudioStreamStatus
}

type AgentReferenceOption = {
  aliases: string[]
  kind: "agent"
  participant: string
}

type FileReferenceOption = {
  file: StudioWorkspaceFileItem
  kind: "file"
}

type ReferenceOption = AgentReferenceOption | FileReferenceOption

type TranscriptTimestamp = {
  dateTime: string
  label: string
  title: string
}

type MessageVersionOption = {
  branchId: string
  current: boolean
  label: string
}

export function ChatPanel({
  busy,
  changes,
  inspectorOpen = false,
  inspectorPlacement = "side",
  liveApi,
  onOpenInspector,
  onEditMessage,
  onPersistUiState,
  onRestoreInspector,
  onSearchWorkspaceFiles,
  onSubmitDraft,
  onSwitchBranch,
  session,
  state,
  streamStatus,
}: ChatPanelProps) {
  const draftStorageKey = draftKey(session, state)
  const outboxStorageKey = outboxKey(session, state)
  const draftMode = state.conversation_id === ""
  const branchUiState = uiStateForCurrentBranch(state)
  const uiStateHydrationKey = branchUiState
    ? `${branchUiState.conversation_id}:${branchUiState.branch_id}:${branchUiState.participant_id}`
    : null
  const [draft, setDraft] = useState("")
  const [loadedDraftKey, setLoadedDraftKey] = useState<string | null>(null)
  const [outbox, setOutbox] = useState<LocalOutboxItem[]>([])
  const [loadedOutboxKey, setLoadedOutboxKey] = useState<string | null>(null)
  const [editingEventId, setEditingEventId] = useState<string | null>(null)
  const [loadedUiStateKey, setLoadedUiStateKey] = useState<string | null>(null)
  const [selectionEnd, setSelectionEnd] = useState(0)
  const [referenceIndex, setReferenceIndex] = useState(0)
  const [dismissedReferenceKey, setDismissedReferenceKey] = useState<string | null>(null)
  const [workspaceFileOptions, setWorkspaceFileOptions] = useState<StudioWorkspaceFileItem[]>([])
  const [workspaceFileOptionsQuery, setWorkspaceFileOptionsQuery] = useState<string | null>(null)
  const [workspaceFileError, setWorkspaceFileError] = useState<{ message: string; query: string } | null>(null)
  const [selectedWorkspaceFiles, setSelectedWorkspaceFiles] = useState<StudioWorkspaceFileItem[]>([])
  const [activityExpanded, setActivityExpanded] = useState(false)
  const referenceListId = useId()
  const activeAgents = useMemo(
    () => state.conversation.agent_states.filter((agent) => agent.running || agent.queued),
    [state.conversation.agent_states]
  )
  const referenceQuery = activeReferenceQuery(draft, selectionEnd)
  const referenceQueryKey = referenceQuery?.key ?? null
  const referenceQueryText = referenceQuery?.query ?? ""
  const visibleWorkspaceFileOptions =
    workspaceFileOptionsQuery === referenceQueryText ? workspaceFileOptions : []
  const visibleWorkspaceFileError =
    workspaceFileError?.query === referenceQueryText ? workspaceFileError.message : null
  const agentOptions =
    referenceQueryKey && dismissedReferenceKey !== referenceQueryKey
      ? agentOptionsForState(state, referenceQueryText.toLowerCase()).slice(0, 8)
      : []
  const referenceOptions: ReferenceOption[] = [
    ...agentOptions,
    ...visibleWorkspaceFileOptions
      .filter((file) => !selectedWorkspaceFiles.some((selected) => selected.path === file.path))
      .slice(0, 8)
      .map((file): FileReferenceOption => ({ file, kind: "file" })),
  ]
  const activeReferenceIndex =
    referenceOptions.length === 0
      ? 0
      : Math.min(referenceIndex, referenceOptions.length - 1)
  const referenceListOpen =
    !!referenceQueryKey &&
    dismissedReferenceKey !== referenceQueryKey &&
    (referenceOptions.length > 0 || visibleWorkspaceFileError !== null)
  const messageVersions = useMemo(() => messageVersionIndex(state), [state])

  useEffect(() => {
    if (!referenceListOpen || referenceOptions.length === 0) {
      return
    }
    document
      .getElementById(`${referenceListId}-${activeReferenceIndex}`)
      ?.scrollIntoView?.({ block: "nearest" })
  }, [activeReferenceIndex, referenceListId, referenceListOpen, referenceOptions.length])

  useEffect(() => {
    if (!referenceQueryKey || dismissedReferenceKey === referenceQueryKey || !onSearchWorkspaceFiles) {
      return
    }
    let cancelled = false
    Promise.resolve(onSearchWorkspaceFiles(referenceQueryText))
      .then((files) => {
        if (!cancelled) {
          setWorkspaceFileOptions(files)
          setWorkspaceFileOptionsQuery(referenceQueryText)
          setWorkspaceFileError(null)
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setWorkspaceFileOptions([])
          setWorkspaceFileOptionsQuery(referenceQueryText)
          setWorkspaceFileError({
            message: error instanceof Error ? error.message : "Workspace file search failed.",
            query: referenceQueryText,
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [dismissedReferenceKey, onSearchWorkspaceFiles, referenceQueryKey, referenceQueryText])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Hydrates a per-branch browser draft after the client storage key is known.
    setDraft(liveApi && branchUiState ? branchUiState.draft_content : draftStorageKey ? localStorage.getItem(draftStorageKey) ?? "" : "")
    setEditingEventId(liveApi && branchUiState ? branchUiState.editing_event_id : null)
    setLoadedDraftKey(draftStorageKey)
    setLoadedUiStateKey(uiStateHydrationKey)
  }, [draftStorageKey, liveApi, uiStateHydrationKey])

  useEffect(() => {
    if (draftStorageKey !== loadedDraftKey) {
      return
    }
    if (!draftStorageKey) {
      return
    }
    if (draft) {
      localStorage.setItem(draftStorageKey, draft)
    } else {
      localStorage.removeItem(draftStorageKey)
    }
  }, [draft, draftStorageKey, loadedDraftKey])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Hydrates a per-branch browser outbox after the client storage key is known.
    setOutbox(liveApi && branchUiState ? outboxItemsFromValue(branchUiState.outbox_state) : outboxStorageKey ? readOutbox(outboxStorageKey) : [])
    setLoadedOutboxKey(outboxStorageKey)
  }, [liveApi, outboxStorageKey, uiStateHydrationKey])

  useEffect(() => {
    if (outboxStorageKey !== loadedOutboxKey) {
      return
    }
    if (!outboxStorageKey) {
      return
    }
    if (outbox.length > 0) {
      localStorage.setItem(outboxStorageKey, JSON.stringify(outbox))
    } else {
      localStorage.removeItem(outboxStorageKey)
    }
  }, [loadedOutboxKey, outbox, outboxStorageKey])

  useEffect(() => {
    if (draftMode || !liveApi || !uiStateHydrationKey || loadedUiStateKey !== uiStateHydrationKey) {
      return
    }
    if (draftStorageKey !== loadedDraftKey || outboxStorageKey !== loadedOutboxKey) {
      return
    }
    const handle = window.setTimeout(() => {
      onPersistUiState({
        branchId: state.history.current_branch_id,
        draftContent: draft,
        editingEventId,
        outboxState: outbox,
      })
    }, 350)
    return () => window.clearTimeout(handle)
  }, [
    draft,
    draftStorageKey,
    draftMode,
    editingEventId,
    liveApi,
    loadedDraftKey,
    loadedOutboxKey,
    loadedUiStateKey,
    onPersistUiState,
    outbox,
    outboxStorageKey,
    state.history.current_branch_id,
    uiStateHydrationKey,
  ])

  function insertAgentReference(participant: string) {
    if (!referenceQuery) {
      const cursor = Math.max(0, Math.min(selectionEnd, draft.length))
      const prefix = draft.slice(0, cursor)
      const suffix = draft.slice(cursor)
      const leadingSpace = prefix && !/\s$/.test(prefix) ? " " : ""
      const trailingSpace = suffix.startsWith(" ") ? "" : " "
      const insertion = `${leadingSpace}@${participant}${trailingSpace}`
      setDraft(`${prefix}${insertion}${suffix}`)
      setSelectionEnd(cursor + insertion.length)
      setDismissedReferenceKey(null)
      return
    }
    const suffix = draft.slice(referenceQuery.end)
    const trailingSpace = suffix.startsWith(" ") ? "" : " "
    const insertion = `@${participant}${trailingSpace}`
    setDraft(`${draft.slice(0, referenceQuery.start)}${insertion}${suffix}`)
    setSelectionEnd(referenceQuery.start + insertion.length)
    setDismissedReferenceKey(null)
  }

  function insertWorkspaceFileReference(file: StudioWorkspaceFileItem) {
    const nextWorkspaceFiles = selectedWorkspaceFiles.some((selected) => selected.path === file.path)
      ? selectedWorkspaceFiles
      : [...selectedWorkspaceFiles, file]
    setSelectedWorkspaceFiles(nextWorkspaceFiles)
    const marker = `@{${file.path}}`
    if (!referenceQuery) {
      const cursor = Math.max(0, Math.min(selectionEnd, draft.length))
      const prefix = draft.slice(0, cursor)
      const suffix = draft.slice(cursor)
      const leadingSpace = prefix && !/\s$/.test(prefix) ? " " : ""
      const trailingSpace = suffix.startsWith(" ") ? "" : " "
      const insertion = `${leadingSpace}${marker}${trailingSpace}`
      setDraft(`${prefix}${insertion}${suffix}`)
      setSelectionEnd(cursor + insertion.length)
      setDismissedReferenceKey(null)
      return
    }
    const suffix = draft.slice(referenceQuery.end)
    const trailingSpace = suffix.startsWith(" ") ? "" : " "
    const insertion = `${marker}${trailingSpace}`
    setDraft(`${draft.slice(0, referenceQuery.start)}${insertion}${suffix}`)
    setSelectionEnd(referenceQuery.start + insertion.length)
    setDismissedReferenceKey(null)
  }

  function insertReference(option: ReferenceOption) {
    if (option.kind === "agent") {
      insertAgentReference(option.participant)
    } else {
      insertWorkspaceFileReference(option.file)
    }
  }

  function handleReferenceKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing) {
      return
    }
    if (!referenceOptions.length) {
      return
    }
    if (event.key === "ArrowDown") {
      event.preventDefault()
      setReferenceIndex((index) => (index + 1) % referenceOptions.length)
    } else if (event.key === "ArrowUp") {
      event.preventDefault()
      setReferenceIndex((index) => (index - 1 + referenceOptions.length) % referenceOptions.length)
    } else if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault()
      insertReference(referenceOptions[activeReferenceIndex] ?? referenceOptions[0]!)
    } else if (event.key === "Escape") {
      event.preventDefault()
      setDismissedReferenceKey(referenceQuery?.key ?? null)
    }
  }

  async function submit(
    content: string,
    files: FileUIPart[],
    workspaceFiles = selectedWorkspaceFiles,
    clientMessageId = `client_${Date.now()}_${Math.random().toString(36).slice(2)}`
  ) {
    const workspacePaths = workspaceFiles.map((file) => file.path)
    const item: LocalOutboxItem = {
      clientMessageId,
      content,
      createdAt: new Date().toISOString(),
      fileNames: files
        .map((file) => file.filename)
        .filter((name): name is string => typeof name === "string" && name.length > 0),
      status: "sending",
      workspaceFiles,
    }
    if (outboxStorageKey) {
      setOutbox((items) => upsertOutboxItem(items, item))
    }
    setDraft("")
    setSelectedWorkspaceFiles([])
    try {
      await onSubmitDraft(content, files, workspacePaths, clientMessageId)
      if (outboxStorageKey) {
        setOutbox((items) => removeOutboxItem(items, clientMessageId))
      }
    } catch {
      setDraft(content)
      setSelectedWorkspaceFiles(workspaceFiles)
      if (outboxStorageKey) {
        setOutbox((items) =>
          updateOutboxItem(items, clientMessageId, { status: "failed" })
        )
      }
    }
  }

  const fileReferenceOptions = referenceOptions.filter(
    (option): option is FileReferenceOption => option.kind === "file"
  )
  const RestoreInspectorIcon =
    inspectorPlacement === "sheet" ? PanelBottomOpenIcon : PanelRightOpenIcon

  return (
    <section className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden bg-background">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-base font-medium">Public Transcript</h2>
          <p className="text-sm text-muted-foreground">
            {draftMode
              ? `New chat with ${state.team_id}`
              : `${state.conversation.events.length} events in ${state.conversation_id}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill label={state.team_id} tone="sky" />
          <StatusPill
            label={liveApi ? "Live backend" : "Fixture snapshot"}
            tone={liveApi ? "emerald" : "amber"}
          />
          {liveApi && !draftMode ? (
            <StatusPill
              label={`Stream ${streamStatus}`}
              tone={streamStatus === "connected" ? "emerald" : "amber"}
            />
          ) : null}
          {busy ? <StatusPill label="Syncing" tone="sky" /> : null}
          {onRestoreInspector && !inspectorOpen ? (
            <Button
              aria-label="Open inspector"
              onClick={onRestoreInspector}
              size="icon-sm"
              variant="ghost"
            >
              <RestoreInspectorIcon className="size-4" />
            </Button>
          ) : null}
        </div>
      </div>

      <Conversation className="min-h-0">
        <ConversationContent className="gap-5 p-4">
          {state.conversation.events.map((event) => (
            <TranscriptMessage
              event={event}
              changes={changes}
              generatedUi={state.generated_ui}
              key={event.id}
              onEditMessage={onEditMessage}
              onEditingEventChange={setEditingEventId}
              onOpenInspector={onOpenInspector}
              onSwitchBranch={onSwitchBranch}
              persistedEditing={editingEventId === event.id}
              versionSwitchDisabled={!liveApi || busy}
              versions={messageVersions.get(messageVersionKey(event)) ?? []}
            />
          ))}
        </ConversationContent>
      </Conversation>

      <div className="border-t p-3">
        <ActivityHint
          activeAgents={activeAgents}
          expanded={activityExpanded}
          onOpenInspector={onOpenInspector}
          onToggleExpanded={() => setActivityExpanded((value) => !value)}
        />
        <OutboxRecovery
          items={outbox}
          onDismiss={(clientMessageId) =>
            setOutbox((items) => removeOutboxItem(items, clientMessageId))
          }
          onRetry={(item) => submit(item.content, [], item.workspaceFiles, item.clientMessageId)}
        />
        <PromptInput
          className="rounded-md border bg-background"
          inputGroupClassName="overflow-visible"
          maxFileSize={10 * 1024 * 1024}
          multiple
          onSubmit={(message) => {
            const content = message.text.trim()
            if (!content) {
              return
            }
            return submit(content, message.files)
          }}
        >
          <PromptInputBody>
            <div className="relative w-full">
              {referenceListOpen ? (
                <div
                  className="absolute bottom-full left-0 right-0 z-20 mb-2 overflow-hidden rounded-md border bg-popover shadow-md"
                  id={referenceListId}
                  role="listbox"
                >
                  <div className="max-h-56 overflow-auto p-0.5">
                    {agentOptions.length > 0 ? (
                      <div className="px-2 py-0.5 text-xs font-medium leading-4 text-muted-foreground">
                        Agents
                      </div>
                    ) : null}
                    {agentOptions.map((option, index) => (
                      <button
                        aria-selected={index === activeReferenceIndex}
                        className={`flex w-full items-center rounded-sm px-2 py-1 text-left text-sm leading-5 ${
                          index === activeReferenceIndex ? "bg-muted" : ""
                        }`}
                        id={`${referenceListId}-${index}`}
                        key={option.participant}
                        onMouseDown={(event) => {
                          event.preventDefault()
                          insertReference(option)
                        }}
                        role="option"
                        title={`Mention ${option.participant}`}
                        type="button"
                      >
                        <span>@{option.participant}</span>
                      </button>
                    ))}
                    {fileReferenceOptions.length > 0 || onSearchWorkspaceFiles ? (
                      <div className="border-t px-2 py-0.5 text-xs font-medium leading-4 text-muted-foreground">
                        Files
                      </div>
                    ) : null}
                    {fileReferenceOptions.map((option, fileIndex) => {
                      const index = agentOptions.length + fileIndex
                      return (
                        <button
                          aria-selected={index === activeReferenceIndex}
                          className={`flex w-full items-center rounded-sm px-2 py-1 text-left text-sm leading-5 ${
                            index === activeReferenceIndex ? "bg-muted" : ""
                          }`}
                          id={`${referenceListId}-${index}`}
                          key={option.file.path}
                          onMouseDown={(event) => {
                            event.preventDefault()
                            insertReference(option)
                          }}
                          role="option"
                          title={`Include file ${option.file.path}`}
                          type="button"
                        >
                          <span className="flex min-w-0 items-center gap-2">
                            <FileTextIcon className="size-3.5 shrink-0 text-muted-foreground" />
                            <span className="truncate">{option.file.path}</span>
                          </span>
                        </button>
                      )
                    })}
                    {visibleWorkspaceFileError ? (
                      <div className="px-2 py-1 text-xs text-muted-foreground">
                        {visibleWorkspaceFileError}
                      </div>
                    ) : null}
                    {onSearchWorkspaceFiles && !visibleWorkspaceFileError && fileReferenceOptions.length === 0 ? (
                      <div className="px-2 py-1 text-xs text-muted-foreground">
                        No matching files
                      </div>
                    ) : null}
                  </div>
                  {!state.runtime.mention_hook_enabled ? (
                    <div className="border-t px-2 py-1 text-xs text-muted-foreground">
                      Mention hook is disabled
                    </div>
                  ) : null}
                </div>
              ) : null}
              <PromptInputTextarea
                aria-label="Message"
                aria-activedescendant={
                  referenceOptions.length > 0 ? `${referenceListId}-${activeReferenceIndex}` : undefined
                }
                aria-autocomplete="list"
                aria-controls={referenceListOpen ? referenceListId : undefined}
                aria-expanded={referenceListOpen}
                className="min-h-24"
                onChange={(event) => {
                  setDraft(event.target.value)
                  setSelectionEnd(event.currentTarget.selectionEnd)
                  setReferenceIndex(0)
                  setDismissedReferenceKey(null)
                }}
                onKeyDown={handleReferenceKeyDown}
                onSelect={(event) => setSelectionEnd(event.currentTarget.selectionEnd)}
                placeholder="@agent"
                role="combobox"
                value={draft}
              />
              {selectedWorkspaceFiles.length > 0 ? (
                <div className="flex flex-wrap gap-1 border-t px-2 py-2">
                  {selectedWorkspaceFiles.map((file) => (
                    <button
                      aria-label={`Remove workspace file ${file.path}`}
                      className="inline-flex max-w-full items-center gap-1 rounded-md border bg-background px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
                      key={file.path}
                      onClick={() =>
                        setSelectedWorkspaceFiles((files) =>
                          files.filter((selected) => selected.path !== file.path)
                        )
                      }
                      title={file.path}
                      type="button"
                    >
                      <FileTextIcon className="size-3.5 shrink-0" />
                      <span className="truncate">{file.path}</span>
                      <XIcon className="size-3 shrink-0" />
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </PromptInputBody>
          <PromptInputFooter>
            <PromptInputTools>
              <AttachFileButton />
              <div className="hidden min-w-0 gap-1 sm:flex">
                {state.participants.map((participant) => (
                  <button
                    aria-label={`Mention ${participant}`}
                    className="rounded-md border px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
                    key={participant}
                    onClick={() => insertAgentReference(participant)}
                    title={`Mention ${participant}`}
                    type="button"
                  >
                    @{participant}
                  </button>
                ))}
              </div>
            </PromptInputTools>
            <PromptInputSubmit aria-label="Send message">
              <SendIcon className="size-4" />
            </PromptInputSubmit>
          </PromptInputFooter>
        </PromptInput>
      </div>
    </section>
  )
}

function AttachFileButton() {
  const attachments = usePromptInputAttachments()

  return (
    <PromptInputButton
      aria-label="Attach file"
      onClick={() => attachments.openFileDialog()}
      type="button"
    >
      <PaperclipIcon className="size-4" />
    </PromptInputButton>
  )
}

function ActivityHint({
  activeAgents,
  expanded,
  onOpenInspector,
  onToggleExpanded,
}: {
  activeAgents: StudioState["conversation"]["agent_states"]
  expanded: boolean
  onOpenInspector: (view: InspectorView) => void
  onToggleExpanded: () => void
}) {
  if (activeAgents.length === 0) {
    return null
  }
  if (activeAgents.length === 1) {
    const agent = activeAgents[0]
    return (
      <button
        aria-label={`Open activity for ${agent.agent_id}`}
        className="mb-2 flex w-full items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-left text-sm text-amber-950 hover:bg-amber-100 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100"
        onClick={() => onOpenInspector({ kind: "activity", agentId: agent.agent_id })}
        title={`Open activity for ${agent.agent_id}`}
        type="button"
      >
        <ActivityIcon className="size-4" />
        <span className="min-w-0 truncate">
          {agent.agent_id} {agent.running ? "is replying..." : "is queued..."}
        </span>
      </button>
    )
  }
  return (
    <div className="mb-2 rounded-md border border-amber-200 bg-amber-50 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100">
      <button
        aria-label={expanded ? "Collapse running agents" : "Expand running agents"}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        onClick={onToggleExpanded}
        title={expanded ? "Collapse running agents" : "Expand running agents"}
        type="button"
      >
        <ActivityIcon className="size-4" />
        <span>{activeAgents.length} agents running</span>
      </button>
      {expanded ? (
        <div className="grid gap-1 border-t border-amber-200 p-2 dark:border-amber-900">
          {activeAgents.map((agent) => (
            <button
              aria-label={`Open activity for ${agent.agent_id}`}
              className="flex items-center justify-between gap-2 rounded-md px-2 py-1 text-left hover:bg-amber-100 dark:hover:bg-amber-900"
              key={agent.agent_id}
              onClick={() => onOpenInspector({ kind: "activity", agentId: agent.agent_id })}
              title={`Open activity for ${agent.agent_id}`}
              type="button"
            >
              <span className="truncate">{agent.agent_id}</span>
              <span className="text-xs">{agent.running ? "running" : "queued"}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function OutboxRecovery({
  items,
  onDismiss,
  onRetry,
}: {
  items: LocalOutboxItem[]
  onDismiss: (clientMessageId: string) => void
  onRetry: (item: LocalOutboxItem) => void
}) {
  if (items.length === 0) {
    return null
  }
  return (
    <div className="mb-2 grid gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100">
      {items.map((item) => (
        <div className="grid gap-2 rounded-sm bg-background/70 p-2" key={item.clientMessageId}>
          <div className="flex min-w-0 items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate font-medium">
                {item.status === "failed" ? "Unsaved prompt" : "Saving prompt"}
              </p>
              <p className="truncate text-xs opacity-80">{item.content}</p>
            </div>
            <StatusPill
              label={item.status === "failed" ? "failed" : "sending"}
              tone={item.status === "failed" ? "amber" : "sky"}
            />
          </div>
          {item.fileNames.length > 0 ? (
            <p className="text-xs opacity-80">
              Reattach files before retrying: {item.fileNames.join(", ")}
            </p>
          ) : null}
          {item.workspaceFiles.length > 0 ? (
            <p className="text-xs opacity-80">
              Workspace files: {item.workspaceFiles.map((file) => file.path).join(", ")}
            </p>
          ) : null}
          <div className="flex justify-end gap-1">
            <Button
              disabled={item.status !== "failed" || item.fileNames.length > 0}
              onClick={() => onRetry(item)}
              size="xs"
              type="button"
              variant="outline"
            >
              Retry
            </Button>
            <Button
              onClick={() => onDismiss(item.clientMessageId)}
              size="xs"
              type="button"
              variant="ghost"
            >
              Dismiss
            </Button>
          </div>
        </div>
      ))}
    </div>
  )
}

function TranscriptMessage({
  changes,
  event,
  generatedUi,
  onEditMessage,
  onEditingEventChange,
  onOpenInspector,
  onSwitchBranch,
  persistedEditing,
  versionSwitchDisabled,
  versions,
}: {
  changes: StudioChanges | null
  event: ConversationEvent
  generatedUi: StudioState["generated_ui"]
  onEditMessage: (messageId: string, content: string) => Promise<void> | void
  onEditingEventChange: (eventId: string | null) => void
  onOpenInspector: (view: InspectorView) => void
  onSwitchBranch: (branchId: string) => Promise<void> | void
  persistedEditing: boolean
  versionSwitchDisabled: boolean
  versions: MessageVersionOption[]
}) {
  const from = event.author_kind === "human" ? "user" : "assistant"
  const linkedGeneratedUi = generatedUiLinks(event, generatedUi)
  const linkedChanges = fileChangeLinks(event, changes)
  const sending = event.metadata.optimistic === true
  const failed = event.metadata.optimistic_status === "failed"
  const [content, setContent] = useState(event.content)
  const [draft, setDraft] = useState(event.content)
  const [editing, setEditing] = useState(false)
  const [copied, setCopied] = useState(false)
  const timestamp = transcriptTimestamp(event.created_at)

  useEffect(() => {
    if (persistedEditing && event.author_kind === "human") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Syncs the local editor draft when persisted editing is restored.
      setDraft(content)
      setEditing(true)
    } else if (!persistedEditing && editing) {
      setDraft(content)
      setEditing(false)
    }
  }, [content, editing, event.author_kind, persistedEditing])

  async function copyMessage() {
    if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
      return
    }
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch {
      setCopied(false)
    }
  }

  function startEditing() {
    setDraft(content)
    setCopied(false)
    setEditing(true)
    onEditingEventChange(event.id)
  }

  async function saveEdit() {
    const nextContent = draft.trim()
    if (!nextContent || nextContent === content) {
      setDraft(content)
      setEditing(false)
      onEditingEventChange(null)
      return
    }
    try {
      await onEditMessage(event.id, nextContent)
    } catch {
      return
    }
    setContent(nextContent)
    setDraft(nextContent)
    setCopied(false)
    setEditing(false)
    onEditingEventChange(null)
  }

  function cancelEdit() {
    setDraft(content)
    setEditing(false)
    onEditingEventChange(null)
  }

  return (
    <Message data-transcript-message from={from}>
      <MessageContent>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{event.author_id}</span>
          <span>#{event.seq}</span>
          {sending ? (
            <StatusPill label={failed ? "failed" : "sending"} tone="amber" />
          ) : null}
          {event.mentions.map((mention) => (
            <StatusPill key={mention} label={`@${mention}`} tone="sky" />
          ))}
          <MessageVersionSelector
            disabled={versionSwitchDisabled}
            onSwitchBranch={onSwitchBranch}
            versions={event.author_kind === "human" ? versions : []}
          />
        </div>
        {editing ? (
          <Textarea
            aria-label="Edited human message"
            className="min-h-24 bg-background/80"
            onChange={(editEvent) => setDraft(editEvent.target.value)}
            value={draft}
          />
        ) : (
          <RichMarkdown content={content} />
        )}
        {event.attachments.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {event.attachments.map((attachment) => (
              <button
                aria-label={`Open attachment ${attachment.filename}`}
                className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
                key={attachment.id}
                onClick={() => onOpenInspector({ kind: "files", selectedFileId: attachment.id })}
                title={`Open attachment ${attachment.filename}`}
                type="button"
              >
                <FileTextIcon className="size-3" />
                {attachment.filename}
              </button>
            ))}
          </div>
        ) : null}
        {linkedGeneratedUi.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {linkedGeneratedUi.map((specId) => (
              <Button
                aria-label={`Open generated UI ${specId}`}
                key={specId}
                onClick={() => onOpenInspector({ kind: "generated-ui", specId })}
                size="xs"
                variant="outline"
              >
                <AppWindowIcon className="size-3" />
                {specId}
              </Button>
            ))}
          </div>
        ) : null}
        {linkedChanges.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {linkedChanges.map((change) => (
              <Button
                aria-label={`Open file change ${change.id}`}
                key={change.id}
                onClick={() => onOpenInspector({ kind: "changes", selectedChangeId: change.id })}
                size="xs"
                variant="outline"
              >
                <GitCompareIcon className="size-3" />
                {change.label}
              </Button>
            ))}
          </div>
        ) : null}
      </MessageContent>
      <TranscriptMessageActions
        align={event.author_kind === "human" ? "end" : "start"}
        canEdit={event.author_kind === "human"}
        copied={copied}
        editing={editing}
        onCancelEdit={cancelEdit}
        onCopy={copyMessage}
        onSaveEdit={saveEdit}
        onStartEdit={startEditing}
        timestamp={timestamp}
      />
    </Message>
  )
}

function TranscriptMessageActions({
  align,
  canEdit,
  copied,
  editing,
  onCancelEdit,
  onCopy,
  onSaveEdit,
  onStartEdit,
  timestamp,
}: {
  align: "end" | "start"
  canEdit: boolean
  copied: boolean
  editing: boolean
  onCancelEdit: () => void
  onCopy: () => void
  onSaveEdit: () => void
  onStartEdit: () => void
  timestamp: TranscriptTimestamp | null
}) {
  const actions = (
    <>
      <TranscriptActionButton
        ariaLabel={copied ? "Message copied" : "Copy message"}
        label="copier"
        onClick={onCopy}
      >
        {copied ? (
          <CheckIcon className="size-3" />
        ) : (
          <CopyIcon className="size-3" />
        )}
      </TranscriptActionButton>
      {canEdit && !editing ? (
        <TranscriptActionButton
          ariaLabel="Edit human message"
          label="éditer"
          onClick={onStartEdit}
        >
          <PencilIcon className="size-3" />
        </TranscriptActionButton>
      ) : null}
      {editing ? (
        <>
          <TranscriptActionButton
            ariaLabel="Save message edit"
            label="Enregistrer"
            onClick={onSaveEdit}
          >
            <CheckIcon className="size-3" />
          </TranscriptActionButton>
          <TranscriptActionButton
            ariaLabel="Cancel message edit"
            label="Annuler"
            onClick={onCancelEdit}
          >
            <XIcon className="size-3" />
          </TranscriptActionButton>
        </>
      ) : null}
    </>
  )

  return (
    <div
      className={`flex h-6 items-center gap-1 text-muted-foreground ${
        align === "end" ? "justify-end" : "justify-start"
      }`}
    >
      {align === "end" ? (
        <>
          <TranscriptTimestampLabel value={timestamp} />
          {actions}
        </>
      ) : (
        <>
          {actions}
          <TranscriptTimestampLabel value={timestamp} />
        </>
      )}
    </div>
  )
}

function TranscriptTimestampLabel({ value }: { value: TranscriptTimestamp | null }) {
  if (!value) {
    return null
  }

  return (
    <time
      className="px-1 text-[11px] leading-none text-muted-foreground"
      dateTime={value.dateTime}
      title={value.title}
    >
      {value.label}
    </time>
  )
}

function TranscriptActionButton({
  ariaLabel,
  children,
  label,
  onClick,
}: {
  ariaLabel: string
  children: ReactNode
  label: string
  onClick: () => void
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          aria-label={ariaLabel}
          onClick={onClick}
          size="icon-xs"
          type="button"
          variant="ghost"
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

function MessageVersionSelector({
  disabled,
  onSwitchBranch,
  versions,
}: {
  disabled: boolean
  onSwitchBranch: (branchId: string) => Promise<void> | void
  versions: MessageVersionOption[]
}) {
  if (versions.length <= 1) {
    return null
  }

  const currentIndex = Math.max(
    0,
    versions.findIndex((version) => version.current)
  )
  const previous = versions[(currentIndex - 1 + versions.length) % versions.length]
  const next = versions[(currentIndex + 1) % versions.length]

  return (
    <ButtonGroup
      aria-label="Message versions"
      className="ml-auto overflow-hidden rounded-md border bg-background/60"
      orientation="horizontal"
    >
      <Button
        aria-label="Previous message version"
        disabled={disabled || previous.branchId === versions[currentIndex]?.branchId}
        onClick={() => onSwitchBranch(previous.branchId)}
        size="icon-xs"
        title={previous.label}
        type="button"
        variant="ghost"
      >
        <ChevronLeftIcon className="size-3" />
      </Button>
      <ButtonGroupText
        className="h-6 rounded-none border-0 bg-transparent px-2 text-[11px] text-muted-foreground"
        title={versions[currentIndex]?.label}
      >
        v{currentIndex + 1}/{versions.length}
      </ButtonGroupText>
      <Button
        aria-label="Next message version"
        disabled={disabled || next.branchId === versions[currentIndex]?.branchId}
        onClick={() => onSwitchBranch(next.branchId)}
        size="icon-xs"
        title={next.label}
        type="button"
        variant="ghost"
      >
        <ChevronRightIcon className="size-3" />
      </Button>
    </ButtonGroup>
  )
}

function messageVersionIndex(state: StudioState) {
  const branchById = new Map(state.history.branches.map((branch) => [branch.id, branch]))
  const currentBranchId = state.history.current_branch_id
  const index = new Map<string, MessageVersionOption[]>()

  for (const event of state.conversation.events) {
    if (event.author_kind !== "human") {
      continue
    }
    const key = messageVersionKey(event)
    const currentBranch = branchById.get(event.branch_id)
    const baseBranchId =
      event.version_parent_event_id && currentBranch?.parent_branch_id
        ? currentBranch.parent_branch_id
        : event.branch_id
    const relatedBranches = state.history.branches.filter(
      (branch) =>
        branch.id === event.branch_id ||
        branch.id === baseBranchId ||
        branch.origin_logical_message_id === key ||
        branch.origin_event_id === event.id ||
        branch.origin_event_id === event.logical_message_id ||
        branch.origin_event_id === event.version_parent_event_id
    )
    const unique = new Map<string, MessageVersionOption>()
    for (const branch of relatedBranches) {
      unique.set(branch.id, {
        branchId: branch.id,
        current: branch.current || branch.id === currentBranchId,
        label: branch.label,
      })
    }
    const versions = [...unique.values()].sort((left, right) => {
      if (left.branchId === baseBranchId) {
        return -1
      }
      if (right.branchId === baseBranchId) {
        return 1
      }
      const leftBranch = branchById.get(left.branchId)
      const rightBranch = branchById.get(right.branchId)
      return (leftBranch?.created_at ?? "").localeCompare(rightBranch?.created_at ?? "")
    })
    if (versions.length > 1) {
      index.set(key, versions)
    }
  }

  return index
}

function messageVersionKey(event: ConversationEvent) {
  return event.logical_message_id ?? event.version_parent_event_id ?? event.id
}

function generatedUiLinks(event: ConversationEvent, generatedUi: StudioState["generated_ui"]) {
  const knownIds = new Set(generatedUi.map((spec) => spec.id))
  const rawIds = event.metadata.generated_ui_ids ?? event.metadata.generated_ui_id
  const ids = Array.isArray(rawIds) ? rawIds : typeof rawIds === "string" ? [rawIds] : []
  return ids.filter((id): id is string => typeof id === "string" && knownIds.has(id))
}

function fileChangeLinks(event: ConversationEvent, changes: StudioChanges | null) {
  const rawIds =
    event.metadata.change_ids ??
    event.metadata.change_id ??
    event.metadata.file_change_ids ??
    event.metadata.file_change_id
  const ids = Array.isArray(rawIds) ? rawIds : typeof rawIds === "string" ? [rawIds] : []
  const changeById = new Map((changes?.changes ?? []).map((change) => [change.id, change]))
  return ids.flatMap((id) => {
    if (typeof id !== "string") {
      return []
    }
    const change = changeById.get(id)
    return [
      {
        id,
        label: change?.path ?? id,
      },
    ]
  })
}

function transcriptTimestamp(value: string): TranscriptTimestamp | null {
  const parsed = Date.parse(value)
  if (Number.isNaN(parsed)) {
    return null
  }

  const date = new Date(parsed)
  return {
    dateTime: date.toISOString(),
    label: formatTranscriptTimestampLabel(date, new Date()),
    title: date.toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }),
  }
}

function formatTranscriptTimestampLabel(date: Date, now: Date) {
  const time = `${padDatePart(date.getHours())}:${padDatePart(date.getMinutes())}`
  if (sameLocalDate(date, now)) {
    return time
  }

  const day = `${padDatePart(date.getDate())}/${padDatePart(date.getMonth() + 1)}`
  if (date.getFullYear() === now.getFullYear()) {
    return `${day} ${time}`
  }

  return `${day}/${date.getFullYear()} ${time}`
}

function sameLocalDate(left: Date, right: Date) {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  )
}

function padDatePart(value: number) {
  return String(value).padStart(2, "0")
}

function activeReferenceQuery(value: string, cursorPosition: number) {
  const cursor = Math.max(0, Math.min(cursorPosition, value.length))
  if (isInsideMarkdownCode(value, cursor)) {
    return null
  }
  const beforeCursor = value.slice(0, cursor)
  const match = /(^|[\s([{])@([A-Za-z0-9_./-]*)$/.exec(beforeCursor)
  if (!match) {
    return null
  }
  const query = match[2] ?? ""
  const start = beforeCursor.length - query.length - 1
  let end = cursor
  while (end < value.length && /[A-Za-z0-9_./-]/.test(value[end] ?? "")) {
    end += 1
  }
  return {
    end,
    key: `${start}:${end}:${query}`,
    query,
    start,
  }
}

function isInsideMarkdownCode(value: string, cursor: number) {
  const beforeCursor = value.slice(0, cursor)
  const fenceCount = beforeCursor.match(/```/g)?.length ?? 0
  if (fenceCount % 2 === 1) {
    return true
  }
  const lineStart = beforeCursor.lastIndexOf("\n") + 1
  const currentLine = beforeCursor.slice(lineStart)
  const inlineTickCount = currentLine.match(/`/g)?.length ?? 0
  return inlineTickCount % 2 === 1
}

function agentOptionsForState(state: StudioState, query: string): AgentReferenceOption[] {
  return state.participants.flatMap((participant) => {
    const aliases = state.participant_aliases[participant] ?? []
    const matchesParticipant = participant.toLowerCase().includes(query)
    const matchesAlias = aliases.some((alias) => alias.toLowerCase().includes(query))
    if (!matchesParticipant && !matchesAlias) {
      return []
    }
    return [{ aliases, kind: "agent", participant }]
  })
}

function draftKey(session: StudioSession | null, state: StudioState) {
  const storageId = session?.checkpointer?.storage_id
  if (!storageId) {
    return null
  }
  return `webapp-studio:v1:${storageId}:${state.team_id}:${state.conversation_id}:${state.history.current_branch_id}:human:draft`
}

function outboxKey(session: StudioSession | null, state: StudioState) {
  const storageId = session?.checkpointer?.storage_id
  if (!storageId) {
    return null
  }
  return `webapp-studio:v1:${storageId}:${state.team_id}:${state.conversation_id}:${state.history.current_branch_id}:human:outbox`
}

function uiStateForCurrentBranch(state: StudioState) {
  return state.ui_state.conversation_id === state.conversation_id &&
    state.ui_state.branch_id === state.history.current_branch_id &&
    state.ui_state.participant_id === "human"
    ? state.ui_state
    : null
}

function readOutbox(key: string): LocalOutboxItem[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(key) ?? "[]")
    return outboxItemsFromValue(parsed)
  } catch {
    return []
  }
}

function outboxItemsFromValue(value: unknown): LocalOutboxItem[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.flatMap((item) => {
    if (!isLocalOutboxItem(item)) {
      return []
    }
    return [
      {
        ...item,
        workspaceFiles: workspaceFilesFromValue((item as Partial<LocalOutboxItem>).workspaceFiles),
      },
    ]
  })
}

function isLocalOutboxItem(value: unknown): value is LocalOutboxItem {
  if (!value || typeof value !== "object") {
    return false
  }
  const item = value as Partial<LocalOutboxItem>
  return (
    typeof item.clientMessageId === "string" &&
    typeof item.content === "string" &&
    typeof item.createdAt === "string" &&
    Array.isArray(item.fileNames) &&
    item.fileNames.every((name) => typeof name === "string") &&
    (item.workspaceFiles === undefined || Array.isArray(item.workspaceFiles)) &&
    (item.status === "sending" || item.status === "failed")
  )
}

function workspaceFilesFromValue(value: unknown): StudioWorkspaceFileItem[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") {
      return []
    }
    const file = item as Partial<StudioWorkspaceFileItem>
    if (typeof file.path !== "string" || typeof file.filename !== "string") {
      return []
    }
    return [
      {
        filename: file.filename,
        media_type: typeof file.media_type === "string" ? file.media_type : null,
        path: file.path,
        size_bytes: typeof file.size_bytes === "number" ? file.size_bytes : null,
      },
    ]
  })
}

function upsertOutboxItem(items: LocalOutboxItem[], item: LocalOutboxItem) {
  const existingIndex = items.findIndex(
    (current) => current.clientMessageId === item.clientMessageId
  )
  if (existingIndex < 0) {
    return [...items, item]
  }
  return items.map((current, index) => (index === existingIndex ? item : current))
}

function updateOutboxItem(
  items: LocalOutboxItem[],
  clientMessageId: string,
  patch: Partial<LocalOutboxItem>
) {
  return items.map((item) =>
    item.clientMessageId === clientMessageId ? { ...item, ...patch } : item
  )
}

function removeOutboxItem(items: LocalOutboxItem[], clientMessageId: string) {
  return items.filter((item) => item.clientMessageId !== clientMessageId)
}
