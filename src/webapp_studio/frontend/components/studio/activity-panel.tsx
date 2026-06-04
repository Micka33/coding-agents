"use client"

import { useState, type ReactNode } from "react"
import {
  CheckIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  CopyIcon,
  FileTextIcon,
} from "lucide-react"

import { RichMarkdown } from "@/components/studio/rich-markdown"
import { StatusPill } from "@/components/studio/status-pill"
import { ToolCallList } from "@/components/studio/tool-call-list"
import { Button } from "@/components/ui/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import type { StudioState } from "@/lib/studio/schemas"

type ActivityPanelProps = {
  focusedAgentId?: string
  onBack: () => void
  onAgentSelect: (agentId: string) => void
  state: StudioState
}

type AgentState = StudioState["conversation"]["agent_states"][number]
type PrivateThread = StudioState["activity"]["private_threads"][number]
type ActivityMessage = PrivateThread["messages"][number]

export function ActivityPanel({
  focusedAgentId,
  onBack,
  onAgentSelect,
  state,
}: ActivityPanelProps) {
  if (!focusedAgentId) {
    return (
      <section className="rounded-md border bg-background p-4">
        <h2 className="text-base font-medium">Agents</h2>
        <div className="mt-4 grid gap-2">
          {state.conversation.agent_states.length === 0 ? (
            <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
              No agents in this snapshot
            </div>
          ) : (
            state.conversation.agent_states.map((agent) => (
              <button
                aria-label={`Open activity for ${agent.agent_id}`}
                className="rounded-md border p-3 text-left hover:bg-muted"
                key={agent.agent_id}
                onClick={() => onAgentSelect(agent.agent_id)}
                title={`Open activity for ${agent.agent_id}`}
                type="button"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate font-medium">
                    {agent.agent_id}
                  </span>
                  <StatusPill
                    label={
                      agent.running
                        ? "running"
                        : agent.queued
                          ? "queued"
                          : "idle"
                    }
                    tone={
                      agent.running
                        ? "emerald"
                        : agent.queued
                          ? "amber"
                          : "slate"
                    }
                  />
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  Delivered through #{agent.last_delivered_seq}
                </p>
              </button>
            ))
          )}
        </div>
      </section>
    )
  }

  const agentState = state.conversation.agent_states.find(
    (agent) => agent.agent_id === focusedAgentId
  )
  const privateThreads = state.activity.private_threads.filter(
    (thread) => thread.agent_id === focusedAgentId
  )
  const orderedThreads = orderedPrivateThreads(
    privateThreads,
    focusedAgentId,
    agentState
  )
  const deliveries = state.conversation.deliveries.filter(
    (delivery) => delivery.agent_id === focusedAgentId
  )
  const showThreadLabels = orderedThreads.length > 1

  return (
    <div className="grid min-w-0 gap-4 overflow-hidden">
      <nav
        aria-label="Activity breadcrumb"
        className="flex min-w-0 items-center gap-2"
      >
        <Button
          aria-label="Back to activity agents"
          onClick={onBack}
          size="sm"
          variant="ghost"
        >
          <ChevronLeftIcon className="size-4" />
          <span>Activity</span>
        </Button>
        <span className="text-sm text-muted-foreground">/</span>
        <span className="min-w-0 truncate text-sm font-medium">
          {focusedAgentId}
        </span>
      </nav>

      {agentState ? (
        <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <StatusPill
            label={
              agentState.running
                ? "running"
                : agentState.queued
                  ? "queued"
                  : "idle"
            }
            tone={
              agentState.running
                ? "emerald"
                : agentState.queued
                  ? "amber"
                  : "slate"
            }
          />
          <span>Delivered through #{agentState.last_delivered_seq}</span>
        </div>
      ) : null}

      <div
        aria-label="Agent activity history"
        className="grid min-w-0 gap-6 overflow-hidden"
      >
        {orderedThreads.length === 0 ? (
          <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
            No private activity for this agent
          </div>
        ) : (
          orderedThreads.map((thread) => (
            <section className="min-w-0 overflow-hidden" key={thread.thread_id}>
              {showThreadLabels ? (
                <div className="mb-3 border-b pb-2">
                  <p className="text-xs break-all text-muted-foreground">
                    {thread.thread_id}
                  </p>
                </div>
              ) : null}
              <div className="grid min-w-0 gap-4">
                {thread.messages.length === 0 ? (
                  <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                    No messages in this thread
                  </div>
                ) : (
                  thread.messages.map((message, index) => (
                    <ActivityMessageItem
                      isFinalMessage={isFinalAiMessage(thread.messages, index)}
                      key={`${thread.thread_id}-${index}-${speakerKey(message)}-${message.content}`}
                      message={message}
                      previousMessage={thread.messages[index - 1]}
                    />
                  ))
                )}
              </div>
            </section>
          ))
        )}

        <section className="min-w-0 rounded-md border p-4">
          <h3 className="flex items-center gap-2 font-medium">
            <FileTextIcon className="size-4 text-emerald-600" />
            Deliveries
          </h3>
          <div className="mt-3 grid min-w-0 gap-2">
            {deliveries.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No delivery records for this agent
              </p>
            ) : (
              deliveries.map((delivery) => (
                <div
                  className="min-w-0 rounded-md border p-3"
                  key={delivery.id}
                >
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="font-medium">{delivery.agent_id}</span>
                    <StatusPill label={delivery.status} tone="emerald" />
                  </div>
                  {delivery.error && (
                    <p className="mt-2 text-sm [overflow-wrap:anywhere] break-words text-rose-700 dark:text-rose-300">
                      {delivery.error}
                    </p>
                  )}
                </div>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

function ActivityMessageItem({
  isFinalMessage,
  message,
  previousMessage,
}: {
  isFinalMessage: boolean
  message: ActivityMessage
  previousMessage: ActivityMessage | undefined
}) {
  const content = message.content || "empty message"
  const [copied, setCopied] = useState(false)
  const timestamp = messageTimestamp(message)

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

  if (isSystemMessage(message)) {
    return (
      <Collapsible className="min-w-0 border-b pb-3">
        <CollapsibleTrigger className="group flex w-full min-w-0 items-center justify-between gap-2 rounded-md bg-muted/50 px-2 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted">
          <span className="min-w-0 truncate font-medium">
            System instructions
          </span>
          <ChevronDownIcon className="size-3.5 shrink-0 transition-transform group-data-[state=open]:rotate-180" />
        </CollapsibleTrigger>
        <CollapsibleContent className="pt-2">
          <RichMarkdown
            className="max-w-full min-w-0 overflow-hidden [overflow-wrap:anywhere] break-words text-muted-foreground [&_*]:max-w-full [&_code]:break-words [&_pre]:overflow-x-auto [&_pre]:whitespace-pre-wrap"
            content={message.content || "empty message"}
          />
        </CollapsibleContent>
      </Collapsible>
    )
  }

  if (isHumanMessage(message)) {
    return (
      <div
        className="group/message relative ml-auto max-w-[85%] min-w-0"
        data-activity-message
      >
        <article className="min-w-0 rounded-md border border-sky-200 bg-sky-50 p-3 text-sky-950 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-100">
          <MessageHeader
            message={message}
            showName={!sameSpeaker(message, previousMessage)}
          />
          <RichMarkdown
            className="mt-2 max-w-full min-w-0 overflow-hidden [overflow-wrap:anywhere] break-words text-sky-950 dark:text-sky-100 [&_*]:max-w-full [&_code]:break-words [&_pre]:overflow-x-auto [&_pre]:whitespace-pre-wrap"
            content={content}
          />
        </article>
        <MessageActions
          align="end"
          copied={copied}
          onCopy={copyMessage}
          timestamp={timestamp}
        />
      </div>
    )
  }

  if (isThinkingMessage(message)) {
    return (
      <article className="min-w-0 overflow-hidden border-b pb-3 last:border-b-0">
        <MessageHeader
          message={message}
          showName={!sameSpeaker(message, previousMessage)}
        />
        <RichMarkdown
          className="mt-1.5 max-w-full min-w-0 overflow-hidden border-l border-violet-300/60 pl-3 text-[13px] leading-tight [overflow-wrap:anywhere] break-words text-muted-foreground dark:border-violet-700/60 [&_*]:max-w-full [&_code]:break-words [&_p]:my-0 [&_pre]:overflow-x-auto [&_pre]:whitespace-pre-wrap"
          content={message.content || "empty message"}
        />
      </article>
    )
  }

  return (
    <article
      className="group/message relative min-w-0 overflow-visible border-b pb-4 last:border-b-0"
      data-activity-message
    >
      <MessageHeader
        message={message}
        showName={!sameSpeaker(message, previousMessage)}
      />
      <RichMarkdown
        className={cn(
          "max-w-full min-w-0 overflow-hidden [overflow-wrap:anywhere] break-words text-foreground [&_*]:max-w-full [&_code]:break-words [&_pre]:overflow-x-auto [&_pre]:whitespace-pre-wrap",
          sameSpeaker(message, previousMessage) ? "mt-0" : "mt-2"
        )}
        content={content}
      />
      <div className="min-w-0 overflow-hidden">
        <ToolCallList value={message.tool_calls} />
      </div>
      {isFinalMessage ? (
        <MessageActions
          align="start"
          copied={copied}
          onCopy={copyMessage}
          placement="inline"
          timestamp={timestamp}
        />
      ) : (
        <MessageActions
          align="start"
          copied={copied}
          onCopy={copyMessage}
          timestamp={timestamp}
        />
      )}
    </article>
  )
}

function MessageActions({
  align,
  copied,
  onCopy,
  placement = "floating",
  timestamp,
}: {
  align: "end" | "start"
  copied: boolean
  onCopy: () => void
  placement?: "floating" | "inline"
  timestamp: MessageTimestamp | null
}) {
  const actions = (
    <>
      <MessageActionButton
        ariaLabel={copied ? "Message copied" : "Copy message"}
        label="copier"
        onClick={onCopy}
      >
        {copied ? (
          <CheckIcon className="size-3" />
        ) : (
          <CopyIcon className="size-3" />
        )}
      </MessageActionButton>
    </>
  )

  return (
    <div
      className={cn(
        "flex h-6 items-center gap-1",
        placement === "floating"
          ? "absolute top-full z-10 mt-0.5 opacity-100 transition-opacity sm:opacity-0 sm:group-focus-within/message:opacity-100 sm:group-hover/message:opacity-100"
          : "mt-2 opacity-100",
        align === "end" ? "right-0 justify-end" : "left-0 justify-start"
      )}
    >
      {align === "end" ? (
        <>
          <MessageTimestampLabel value={timestamp} />
          {actions}
        </>
      ) : (
        <>
          {actions}
          <MessageTimestampLabel value={timestamp} />
        </>
      )}
    </div>
  )
}

type MessageTimestamp = {
  dateTime: string
  label: string
  title: string
}

function MessageTimestampLabel({ value }: { value: MessageTimestamp | null }) {
  if (!value) {
    return null
  }

  return (
    <time
      className="min-w-max text-xs text-muted-foreground"
      dateTime={value.dateTime}
      title={value.title}
    >
      {value.label}
    </time>
  )
}

function MessageActionButton({
  ariaLabel,
  children,
  label,
  onClick,
}: {
  ariaLabel: string
  children: ReactNode
  label: string
  onClick?: () => void
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

function MessageHeader({
  message,
  showName,
}: {
  message: ActivityMessage
  showName: boolean
}) {
  if (!showName) {
    return null
  }

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span className="rounded-md bg-muted px-1.5 py-0.5 font-mono">
        {message.type}
      </span>
      {message.name && <span className="min-w-0 truncate">{message.name}</span>}
    </div>
  )
}

function sameSpeaker(
  message: ActivityMessage,
  previousMessage: ActivityMessage | undefined
) {
  if (
    !previousMessage ||
    isSystemMessage(message) ||
    isSystemMessage(previousMessage)
  ) {
    return false
  }
  return speakerKey(message) === speakerKey(previousMessage)
}

function speakerKey(message: ActivityMessage) {
  return `${message.type}:${message.name ?? ""}`
}

function isSystemMessage(message: ActivityMessage) {
  return message.type === "system"
}

function isHumanMessage(message: ActivityMessage) {
  return message.type === "human"
}

function isThinkingMessage(message: ActivityMessage) {
  return message.type === "thinking" || message.type === "reasoning"
}

function isFinalAiMessage(messages: ActivityMessage[], index: number) {
  const message = messages[index]
  if (!message || message.type !== "ai" || hasToolCalls(message)) {
    return false
  }

  return !messages
    .slice(index + 1)
    .some((nextMessage) => nextMessage.type === "ai")
}

function hasToolCalls(message: ActivityMessage) {
  return Array.isArray(message.tool_calls) && message.tool_calls.length > 0
}

function messageTimestamp(message: ActivityMessage): MessageTimestamp | null {
  const date = messageTimestampDate(message)
  if (!date) {
    return null
  }

  return {
    dateTime: date.toISOString(),
    label: formatMessageTimestampLabel(date, new Date()),
    title: date.toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }),
  }
}

function messageTimestampDate(message: ActivityMessage) {
  if (!isRecord(message)) {
    return null
  }

  for (const field of ["created_at", "updated_at"]) {
    const rawValue = message[field]
    if (typeof rawValue === "string") {
      const parsed = Date.parse(rawValue)
      if (!Number.isNaN(parsed)) {
        return new Date(parsed)
      }
    }
    if (typeof rawValue === "number" && Number.isFinite(rawValue)) {
      return new Date(rawValue)
    }
  }

  return null
}

function formatMessageTimestampLabel(date: Date, now: Date) {
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

function orderedPrivateThreads(
  threads: PrivateThread[],
  focusedAgentId: string,
  agentState: AgentState | undefined
) {
  return [...threads].sort((left, right) => {
    const activeDelta =
      activeThreadRank(right, focusedAgentId, agentState) -
      activeThreadRank(left, focusedAgentId, agentState)
    if (activeDelta !== 0) {
      return activeDelta
    }

    const activityDelta = threadActivityTime(right) - threadActivityTime(left)
    if (activityDelta !== 0) {
      return activityDelta
    }

    return left.thread_id.localeCompare(right.thread_id)
  })
}

function activeThreadRank(
  thread: PrivateThread,
  focusedAgentId: string,
  agentState: AgentState | undefined
) {
  if (!agentState?.running && !agentState?.queued) {
    return 0
  }
  return thread.thread_id.endsWith(`:mention:${focusedAgentId}`) ? 1 : 0
}

function threadActivityTime(thread: PrivateThread) {
  const threadTime = timestampValue(thread, [
    "last_activity_at",
    "updated_at",
    "created_at",
  ])
  if (threadTime !== 0) {
    return threadTime
  }

  for (const message of [...thread.messages].reverse()) {
    const messageTime = timestampValue(message, ["created_at", "updated_at"])
    if (messageTime !== 0) {
      return messageTime
    }
  }

  return 0
}

function timestampValue(value: unknown, fields: string[]) {
  if (!isRecord(value)) {
    return 0
  }
  for (const field of fields) {
    const rawValue = value[field]
    if (typeof rawValue === "number" && Number.isFinite(rawValue)) {
      return rawValue
    }
    if (typeof rawValue === "string") {
      const parsed = Date.parse(rawValue)
      if (!Number.isNaN(parsed)) {
        return parsed
      }
    }
  }
  return 0
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}
