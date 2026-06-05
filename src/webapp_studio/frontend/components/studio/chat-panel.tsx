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
} from "@/lib/studio/schemas"

type ChatPanelProps = {
  busy: boolean
  changes: StudioChanges | null
  liveApi: boolean
  onOpenInspector: (view: InspectorView) => void
  onEditMessage: (messageId: string, content: string) => Promise<void> | void
  onSubmitDraft: (
    content: string,
    files: FileUIPart[],
    clientMessageId: string
  ) => Promise<void> | void
  onSwitchBranch: (branchId: string) => Promise<void> | void
  session: StudioSession | null
  state: StudioState
  streamStatus: StudioStreamStatus
}

type LocalOutboxItem = {
  clientMessageId: string
  content: string
  createdAt: string
  fileNames: string[]
  status: "sending" | "failed"
}

type MentionOption = {
  aliases: string[]
  participant: string
}

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
  liveApi,
  onOpenInspector,
  onEditMessage,
  onSubmitDraft,
  onSwitchBranch,
  session,
  state,
  streamStatus,
}: ChatPanelProps) {
  const draftStorageKey = draftKey(session, state)
  const outboxStorageKey = outboxKey(session, state)
  const [draft, setDraft] = useState("")
  const [outbox, setOutbox] = useState<LocalOutboxItem[]>([])
  const [loadedOutboxKey, setLoadedOutboxKey] = useState<string | null>(null)
  const [selectionEnd, setSelectionEnd] = useState(0)
  const [mentionIndex, setMentionIndex] = useState(0)
  const [dismissedMentionKey, setDismissedMentionKey] = useState<string | null>(null)
  const [activityExpanded, setActivityExpanded] = useState(false)
  const mentionListId = useId()
  const activeAgents = useMemo(
    () => state.conversation.agent_states.filter((agent) => agent.running || agent.queued),
    [state.conversation.agent_states]
  )
  const mentionQuery = activeMentionQuery(draft, selectionEnd)
  const mentionOptions = useMemo(() => {
    if (!mentionQuery || dismissedMentionKey === mentionQuery.key) {
      return []
    }
    const query = mentionQuery.query.toLowerCase()
    return mentionOptionsForState(state, query).slice(0, 8)
  }, [dismissedMentionKey, mentionQuery, state])
  const activeMentionIndex =
    mentionOptions.length === 0
      ? 0
      : Math.min(mentionIndex, mentionOptions.length - 1)
  const messageVersions = useMemo(() => messageVersionIndex(state), [state])

  useEffect(() => {
    if (!draftStorageKey) {
      return
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Hydrates a per-thread browser draft after the client storage key is known.
    setDraft(localStorage.getItem(draftStorageKey) ?? "")
  }, [draftStorageKey])

  useEffect(() => {
    if (!draftStorageKey) {
      return
    }
    if (draft) {
      localStorage.setItem(draftStorageKey, draft)
    } else {
      localStorage.removeItem(draftStorageKey)
    }
  }, [draft, draftStorageKey])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Hydrates a per-thread browser outbox after the client storage key is known.
    setOutbox(outboxStorageKey ? readOutbox(outboxStorageKey) : [])
    setLoadedOutboxKey(outboxStorageKey)
  }, [outboxStorageKey])

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

  function insertMention(participant: string) {
    if (!mentionQuery) {
      const cursor = Math.max(0, Math.min(selectionEnd, draft.length))
      const prefix = draft.slice(0, cursor)
      const suffix = draft.slice(cursor)
      const leadingSpace = prefix && !/\s$/.test(prefix) ? " " : ""
      const trailingSpace = suffix.startsWith(" ") ? "" : " "
      const insertion = `${leadingSpace}@${participant}${trailingSpace}`
      setDraft(`${prefix}${insertion}${suffix}`)
      setSelectionEnd(cursor + insertion.length)
      setDismissedMentionKey(null)
      return
    }
    const suffix = draft.slice(mentionQuery.end)
    const trailingSpace = suffix.startsWith(" ") ? "" : " "
    const insertion = `@${participant}${trailingSpace}`
    setDraft(`${draft.slice(0, mentionQuery.start)}${insertion}${suffix}`)
    setSelectionEnd(mentionQuery.start + insertion.length)
    setDismissedMentionKey(null)
  }

  function handleMentionKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing) {
      return
    }
    if (!mentionOptions.length) {
      return
    }
    if (event.key === "ArrowDown") {
      event.preventDefault()
      setMentionIndex((index) => (index + 1) % mentionOptions.length)
    } else if (event.key === "ArrowUp") {
      event.preventDefault()
      setMentionIndex((index) => (index - 1 + mentionOptions.length) % mentionOptions.length)
    } else if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault()
      insertMention(
        (mentionOptions[activeMentionIndex] ?? mentionOptions[0]).participant
      )
    } else if (event.key === "Escape") {
      event.preventDefault()
      setDismissedMentionKey(mentionQuery?.key ?? null)
    }
  }

  async function submit(
    content: string,
    files: FileUIPart[],
    clientMessageId = `client_${Date.now()}_${Math.random().toString(36).slice(2)}`
  ) {
    const item: LocalOutboxItem = {
      clientMessageId,
      content,
      createdAt: new Date().toISOString(),
      fileNames: files
        .map((file) => file.filename)
        .filter((name): name is string => typeof name === "string" && name.length > 0),
      status: "sending",
    }
    if (outboxStorageKey) {
      setOutbox((items) => upsertOutboxItem(items, item))
    }
    setDraft("")
    try {
      await onSubmitDraft(content, files, clientMessageId)
      if (outboxStorageKey) {
        setOutbox((items) => removeOutboxItem(items, clientMessageId))
      }
    } catch {
      if (outboxStorageKey) {
        setOutbox((items) =>
          updateOutboxItem(items, clientMessageId, { status: "failed" })
        )
      }
    }
  }

  return (
    <section className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden bg-background">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-base font-medium">Public Transcript</h2>
          <p className="text-sm text-muted-foreground">
            {state.conversation.events.length} events in {state.conversation_id}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill label={liveApi ? "Live backend" : "Fixture snapshot"} tone={liveApi ? "emerald" : "amber"} />
          {liveApi ? (
            <StatusPill
              label={`Stream ${streamStatus}`}
              tone={streamStatus === "connected" ? "emerald" : "amber"}
            />
          ) : null}
          {busy ? <StatusPill label="Syncing" tone="sky" /> : null}
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
              onOpenInspector={onOpenInspector}
              onSwitchBranch={onSwitchBranch}
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
          onRetry={(item) => submit(item.content, [], item.clientMessageId)}
        />
        <PromptInput
          accept="*"
          className="rounded-md border bg-background"
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
            <div className="relative">
              {mentionOptions.length > 0 ? (
                <div
                  className="absolute bottom-full left-2 z-20 mb-2 w-64 overflow-hidden rounded-md border bg-popover shadow-md"
                  id={mentionListId}
                  role="listbox"
                >
                  <div className="max-h-56 overflow-auto p-1">
                    {mentionOptions.map((option, index) => (
                      <button
                        aria-selected={index === activeMentionIndex}
                        className={`grid w-full gap-0.5 rounded-sm px-2 py-1.5 text-left text-sm ${
                          index === activeMentionIndex ? "bg-muted" : ""
                        }`}
                        id={`${mentionListId}-${index}`}
                        key={option.participant}
                        onMouseDown={(event) => {
                          event.preventDefault()
                          insertMention(option.participant)
                        }}
                        role="option"
                        title={`Mention ${option.participant}`}
                        type="button"
                      >
                        <span>@{option.participant}</span>
                        {option.aliases.length > 0 ? (
                          <span className="truncate text-xs text-muted-foreground">
                            aliases: {option.aliases.map((alias) => `@${alias}`).join(", ")}
                          </span>
                        ) : null}
                      </button>
                    ))}
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
                  mentionOptions.length > 0 ? `${mentionListId}-${activeMentionIndex}` : undefined
                }
                aria-autocomplete="list"
                aria-controls={mentionOptions.length > 0 ? mentionListId : undefined}
                aria-expanded={mentionOptions.length > 0}
                className="min-h-24"
                onChange={(event) => {
                  setDraft(event.target.value)
                  setSelectionEnd(event.currentTarget.selectionEnd)
                  setMentionIndex(0)
                  setDismissedMentionKey(null)
                }}
                onKeyDown={handleMentionKeyDown}
                onSelect={(event) => setSelectionEnd(event.currentTarget.selectionEnd)}
                placeholder="@agent"
                role="combobox"
                value={draft}
              />
            </div>
          </PromptInputBody>
          <PromptInputFooter>
            <PromptInputTools>
              <PromptInputButton aria-label="Attach file" type="button">
                <PaperclipIcon className="size-4" />
              </PromptInputButton>
              <div className="hidden min-w-0 gap-1 sm:flex">
                {state.participants.map((participant) => (
                  <button
                    aria-label={`Mention ${participant}`}
                    className="rounded-md border px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
                    key={participant}
                    onClick={() => insertMention(participant)}
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
  onOpenInspector,
  onSwitchBranch,
  versionSwitchDisabled,
  versions,
}: {
  changes: StudioChanges | null
  event: ConversationEvent
  generatedUi: StudioState["generated_ui"]
  onEditMessage: (messageId: string, content: string) => Promise<void> | void
  onOpenInspector: (view: InspectorView) => void
  onSwitchBranch: (branchId: string) => Promise<void> | void
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
  }

  async function saveEdit() {
    const nextContent = draft.trim()
    if (!nextContent || nextContent === content) {
      setDraft(content)
      setEditing(false)
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
  }

  function cancelEdit() {
    setDraft(content)
    setEditing(false)
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

function activeMentionQuery(value: string, cursorPosition: number) {
  const cursor = Math.max(0, Math.min(cursorPosition, value.length))
  if (isInsideMarkdownCode(value, cursor)) {
    return null
  }
  const beforeCursor = value.slice(0, cursor)
  const match = /(^|[\s([{])@([A-Za-z0-9_-]*)$/.exec(beforeCursor)
  if (!match) {
    return null
  }
  const start = beforeCursor.length - match[2].length - 1
  let end = cursor
  while (end < value.length && /[A-Za-z0-9_-]/.test(value[end] ?? "")) {
    end += 1
  }
  return {
    end,
    key: `${start}:${end}:${match[2]}`,
    query: match[2],
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

function mentionOptionsForState(state: StudioState, query: string): MentionOption[] {
  return state.participants.flatMap((participant) => {
    const aliases = state.participant_aliases[participant] ?? []
    const matchesParticipant = participant.toLowerCase().includes(query)
    const matchesAlias = aliases.some((alias) => alias.toLowerCase().includes(query))
    if (!matchesParticipant && !matchesAlias) {
      return []
    }
    return [{ aliases, participant }]
  })
}

function draftKey(session: StudioSession | null, state: StudioState) {
  const storageId = session?.checkpointer.storage_id
  if (!storageId) {
    return null
  }
  return `webapp-studio:v1:${storageId}:${state.team_id}:${state.conversation_id}:draft`
}

function outboxKey(session: StudioSession | null, state: StudioState) {
  const storageId = session?.checkpointer.storage_id
  if (!storageId) {
    return null
  }
  return `webapp-studio:v1:${storageId}:${state.team_id}:${state.conversation_id}:outbox`
}

function readOutbox(key: string): LocalOutboxItem[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(key) ?? "[]")
    if (!Array.isArray(parsed)) {
      return []
    }
    return parsed.filter(isLocalOutboxItem)
  } catch {
    return []
  }
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
    (item.status === "sending" || item.status === "failed")
  )
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
