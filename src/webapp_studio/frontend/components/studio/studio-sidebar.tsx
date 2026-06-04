"use client"

import type { ReactNode } from "react"
import { useMemo, useState } from "react"
import {
  ActivityIcon,
  AppWindowIcon,
  CheckIcon,
  FolderIcon,
  GitBranchIcon,
  GitCompareIcon,
  HistoryIcon,
  InfoIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  PencilIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SendIcon,
  SquareIcon,
  TerminalIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react"

import type { InspectorView } from "@/components/studio/right-inspector"
import { StatusPill } from "@/components/studio/status-pill"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import type {
  ConversationList,
  InterruptRequest,
  StudioSession,
  StudioState,
} from "@/lib/studio/schemas"
import { cn } from "@/lib/utils"

type QueueClearScope = "failed" | "pending" | "all"

type StudioSidebarProps = {
  busy: boolean
  collapsed: boolean
  conversationList: ConversationList | null
  liveApi: boolean
  onCancelQueueItem: (queueItemId: string) => void
  onCascadeLimitChange: (value: number | null) => void
  onClearQueue: (scope: QueueClearScope) => void
  onCreateBranchFromCheckpoint: (checkpointId: string) => void
  onEditCheckpoint: (checkpointId: string, editedContent: string) => void
  onOpenInspector: (view: InspectorView) => void
  onRegenerateCheckpoint: (checkpointId: string) => void
  onResumeCheckpoint: (checkpointId: string) => void
  onResumeInterrupt: (
    interruptId: string,
    decision: "approve" | "reject" | "edit" | "respond",
    input?: {
      response?: string
      editedPayload?: InterruptRequest["payload"]
    }
  ) => void
  onRuntimeChange: (mentionHookEnabled: boolean) => void
  onStopAgent: (agentId: string) => void
  onSwitchBranch: (branchId: string) => void
  onSwitchConversation: (conversationId: string) => void
  onToggleCollapsed: () => void
  session: StudioSession | null
  state: StudioState
}

export function StudioSidebar({
  busy,
  collapsed,
  conversationList,
  liveApi,
  onCancelQueueItem,
  onCascadeLimitChange,
  onClearQueue,
  onCreateBranchFromCheckpoint,
  onEditCheckpoint,
  onOpenInspector,
  onRegenerateCheckpoint,
  onResumeCheckpoint,
  onResumeInterrupt,
  onRuntimeChange,
  onStopAgent,
  onSwitchBranch,
  onSwitchConversation,
  onToggleCollapsed,
  session,
  state,
}: StudioSidebarProps) {
  const [threadDraftState, setThreadDraftState] = useState({
    conversationId: state.conversation_id,
    value: state.conversation_id,
  })
  const [interruptDrafts, setInterruptDrafts] = useState<Record<string, string>>({})
  const [editingCheckpointId, setEditingCheckpointId] = useState<string | null>(null)
  const [checkpointEditDrafts, setCheckpointEditDrafts] = useState<Record<string, string>>({})
  const threadDraft =
    threadDraftState.conversationId === state.conversation_id
      ? threadDraftState.value
      : state.conversation_id
  const cascadeLimitValue = state.runtime.max_cascade_turns === null ? "" : String(state.runtime.max_cascade_turns)
  const hasFailedQueueItems = state.queue.some((item) => item.status === "failed")
  const hasPendingQueueItems = state.queue.some((item) => item.status === "pending")
  const queueClearScope: QueueClearScope =
    hasFailedQueueItems && hasPendingQueueItems ? "all" : hasFailedQueueItems ? "failed" : "pending"
  const activeAgents = useMemo(
    () => state.conversation.agent_states.filter((agent) => agent.running || agent.queued),
    [state.conversation.agent_states]
  )
  const fileCount = state.conversation.events.reduce(
    (count, event) => count + event.attachments.length,
    0
  )

  function applyCascadeLimitDraft(input: HTMLInputElement) {
    const trimmed = input.value.trim()
    if (!trimmed) {
      onCascadeLimitChange(null)
      return
    }
    const parsed = Number(trimmed)
    if (!Number.isInteger(parsed) || parsed < 1) {
      input.value = cascadeLimitValue
      return
    }
    onCascadeLimitChange(parsed)
  }

  function switchThread(value: string) {
    const trimmed = value.trim()
    if (!trimmed || trimmed === state.conversation_id) {
      return
    }
    onSwitchConversation(trimmed)
  }

  function updateThreadDraft(value: string) {
    setThreadDraftState({
      conversationId: state.conversation_id,
      value,
    })
  }

  if (collapsed) {
    return (
      <aside className="flex h-full flex-col items-center gap-2 border-r bg-background px-2 py-3">
        <Button aria-label="Expand sidebar" onClick={onToggleCollapsed} size="icon-sm" variant="ghost">
          <PanelLeftOpenIcon className="size-4" />
        </Button>
        <RailButton icon={<FolderIcon className="size-4" />} label="Files" onClick={() => onOpenInspector({ kind: "files" })} />
        <RailButton icon={<ActivityIcon className="size-4" />} label="Activity" onClick={() => onOpenInspector({ kind: "activity" })} />
        <RailButton icon={<GitCompareIcon className="size-4" />} label="Changes" onClick={() => onOpenInspector({ kind: "changes" })} />
        <RailButton icon={<TerminalIcon className="size-4" />} label="Terminal" onClick={() => onOpenInspector({ kind: "terminal" })} />
        <RailButton icon={<AppWindowIcon className="size-4" />} label="Generated UI" onClick={() => onOpenInspector({ kind: "generated-ui" })} />
      </aside>
    )
  }

  return (
    <aside className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden border-r bg-background">
      <div className="border-b px-3 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-base font-semibold">Webapp Studio</h1>
            <p className="truncate text-xs text-muted-foreground">{state.team_id}</p>
          </div>
          <Button aria-label="Collapse sidebar" onClick={onToggleCollapsed} size="icon-sm" variant="ghost">
            <PanelLeftCloseIcon className="size-4" />
          </Button>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-1 text-xs">
          <Metric label="Events" value={state.conversation.events.length} />
          <Metric label="Files" value={fileCount} />
          <Metric label="Runs" value={state.runs.length} />
        </div>
      </div>

      <div className="min-h-0 overflow-auto px-3 py-3">
        <section className="grid gap-3">
          <div className="grid gap-2">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="studio-thread-id">
              Thread
            </label>
            <div className="flex gap-1">
              <Input
                className="h-8 text-sm"
                id="studio-thread-id"
                onChange={(event) => updateThreadDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    switchThread(event.currentTarget.value)
                  }
                }}
                value={threadDraft}
              />
              <Button
                aria-label="Switch thread"
                disabled={!liveApi || busy || !threadDraft.trim()}
                onClick={() => switchThread(threadDraft)}
                size="icon-sm"
                variant="outline"
              >
                <GitBranchIcon className="size-4" />
              </Button>
            </div>
            {conversationList?.conversations.length ? (
              <div className="grid gap-1">
                {conversationList.conversations.slice(0, 4).map((conversation) => (
                  <button
                    aria-label={`Switch to thread ${conversation.conversation_id}`}
                    className={cn(
                      "min-w-0 rounded-md border px-2 py-1 text-left text-xs hover:bg-muted",
                      conversation.conversation_id === state.conversation_id ? "bg-muted" : null
                    )}
                    key={conversation.conversation_id}
                    onClick={() => {
                      updateThreadDraft(conversation.conversation_id)
                      switchThread(conversation.conversation_id)
                    }}
                    title={`Switch to thread ${conversation.conversation_id}`}
                    type="button"
                  >
                    <span className="block truncate font-medium">{conversation.conversation_id}</span>
                    <span className="block truncate text-muted-foreground">
                      {conversation.event_count} events
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <details className="rounded-md border p-2 text-xs">
            <summary className="flex cursor-pointer items-center gap-2 font-medium">
              <InfoIcon className="size-3" />
              Persistence
            </summary>
            <div className="mt-2 grid gap-1 text-muted-foreground">
              <p className="break-all">cwd: {session?.launcher_cwd ?? "unknown"}</p>
              <p className="break-all">root: {session?.resolved_root_dir ?? "unknown"}</p>
              <p className="break-all">backend: {session?.checkpointer.backend ?? "unknown"}</p>
              <p className="break-all">db: {session?.checkpointer.sqlite_path ?? "n/a"}</p>
            </div>
          </details>
        </section>

        <Section title="Views">
          <div className="grid grid-cols-2 gap-1">
            <ViewButton icon={<FolderIcon className="size-4" />} label="Files" onClick={() => onOpenInspector({ kind: "files" })} />
            <ViewButton icon={<ActivityIcon className="size-4" />} label="Activity" onClick={() => onOpenInspector({ kind: "activity" })} />
            <ViewButton icon={<GitCompareIcon className="size-4" />} label="Changes" onClick={() => onOpenInspector({ kind: "changes" })} />
            <ViewButton icon={<TerminalIcon className="size-4" />} label="Terminal" onClick={() => onOpenInspector({ kind: "terminal" })} />
            <ViewButton icon={<AppWindowIcon className="size-4" />} label="UI" onClick={() => onOpenInspector({ kind: "generated-ui" })} />
          </div>
        </Section>

        <Section title="Runtime">
          <label className="flex items-center justify-between gap-3">
            <span className="text-sm">Mention hook</span>
            <Switch
              aria-label="Toggle mention hook"
              checked={state.runtime.mention_hook_enabled}
              onCheckedChange={onRuntimeChange}
            />
          </label>
          <label className="grid gap-2 text-sm">
            Cascade limit
            <Input
              aria-label="Cascade limit"
              defaultValue={cascadeLimitValue}
              disabled={!liveApi || busy}
              key={cascadeLimitValue}
              min={1}
              onBlur={(event) => applyCascadeLimitDraft(event.currentTarget)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.currentTarget.blur()
                }
              }}
              placeholder="unbounded"
              type="number"
            />
          </label>
        </Section>

        <Section
          action={
            state.queue.length > 0 ? (
              <Button
                aria-label="Clear queue"
                disabled={!liveApi || busy}
                onClick={() => onClearQueue(queueClearScope)}
                size="icon-sm"
                variant="outline"
              >
                <Trash2Icon className="size-4" />
              </Button>
            ) : null
          }
          title="Queue"
        >
          {state.queue.length === 0 ? (
            <p className="text-sm text-muted-foreground">No queued messages</p>
          ) : (
            state.queue.map((item) => (
              <div className="rounded-md border p-2" key={item.id}>
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">{item.agent_id}</span>
                  <div className="flex items-center gap-1">
                    <StatusPill label={item.status} tone="sky" />
                    {item.can_cancel ? (
                      <Button
                        aria-label={`Cancel ${item.agent_id} queue item`}
                        disabled={!liveApi || busy}
                        onClick={() => onCancelQueueItem(item.id)}
                        size="icon-xs"
                        variant="outline"
                      >
                        <XIcon className="size-3" />
                      </Button>
                    ) : null}
                  </div>
                </div>
              </div>
            ))
          )}
        </Section>

        <Section title="Reviews">
          {state.interrupts.length === 0 ? (
            <p className="text-sm text-muted-foreground">No pending reviews</p>
          ) : (
            state.interrupts.map((interrupt) => {
              const response = interruptDrafts[interrupt.id] ?? ""
              const trimmed = response.trim()
              return (
                <div className="grid gap-2 rounded-md border p-2" key={interrupt.id}>
                  <div className="flex min-w-0 items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{interrupt.agent_id ?? interrupt.id}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {interrupt.checkpoint_id ?? interrupt.run_id ?? interrupt.id}
                      </p>
                    </div>
                    <StatusPill label={interrupt.kind} tone="amber" />
                  </div>
                  <pre className="max-h-24 overflow-auto rounded-md bg-muted p-2 text-xs whitespace-pre-wrap break-words">
                    {payloadPreview(interrupt.payload)}
                  </pre>
                  <Textarea
                    aria-label={`Response for ${interrupt.id}`}
                    className="min-h-16 resize-none text-sm"
                    onChange={(event) =>
                      setInterruptDrafts((drafts) => ({
                        ...drafts,
                        [interrupt.id]: event.target.value,
                      }))
                    }
                    value={response}
                  />
                  <div className="grid grid-cols-2 gap-1">
                    <Button disabled={!liveApi || busy} onClick={() => onResumeInterrupt(interrupt.id, "approve")} size="xs" variant="outline">
                      <CheckIcon className="size-3" />
                      Approve
                    </Button>
                    <Button disabled={!liveApi || busy} onClick={() => onResumeInterrupt(interrupt.id, "reject")} size="xs" variant="outline">
                      <XIcon className="size-3" />
                      Reject
                    </Button>
                    <Button
                      disabled={!liveApi || busy || !trimmed}
                      onClick={() =>
                        onResumeInterrupt(interrupt.id, "edit", {
                          response: trimmed,
                          editedPayload: { response: trimmed },
                        })
                      }
                      size="xs"
                      variant="outline"
                    >
                      <PencilIcon className="size-3" />
                      Edit
                    </Button>
                    <Button
                      disabled={!liveApi || busy || !trimmed}
                      onClick={() =>
                        onResumeInterrupt(interrupt.id, "respond", {
                          response: trimmed,
                        })
                      }
                      size="xs"
                      variant="outline"
                    >
                      <SendIcon className="size-3" />
                      Respond
                    </Button>
                  </div>
                </div>
              )
            })
          )}
        </Section>

        <Section title="Agents">
          {activeAgents.length === 0 ? (
            <p className="text-sm text-muted-foreground">No active agents</p>
          ) : (
            activeAgents.map((agent) => (
              <div className="flex items-center justify-between gap-2 rounded-md border p-2" key={agent.agent_id}>
                <button
                  aria-label={`Open activity for ${agent.agent_id}`}
                  className="min-w-0 truncate text-left text-sm font-medium hover:underline"
                  onClick={() => onOpenInspector({ kind: "activity", agentId: agent.agent_id })}
                  title={`Open activity for ${agent.agent_id}`}
                  type="button"
                >
                  {agent.agent_id}
                </button>
                <Button
                  aria-label={`Stop ${agent.agent_id}`}
                  disabled={!liveApi || busy}
                  onClick={() => onStopAgent(agent.agent_id)}
                  size="icon-sm"
                  variant="outline"
                >
                  <SquareIcon className="size-4" />
                </Button>
              </div>
            ))
          )}
        </Section>

        <Section title="History">
          <div>
            <h3 className="text-xs font-medium uppercase text-muted-foreground">Branches</h3>
            <div className="mt-2 grid gap-2">
              {state.history.branches.map((branch) => (
                <div className="flex min-w-0 items-center justify-between gap-2" key={branch.id}>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{branch.label}</p>
                    <p className="truncate text-xs text-muted-foreground">{branch.id}</p>
                  </div>
                  {branch.current ? (
                    <StatusPill label="Current" tone="emerald" />
                  ) : (
                    <Button
                      aria-label={`Switch to ${branch.label}`}
                      disabled={!liveApi || busy}
                      onClick={() => onSwitchBranch(branch.id)}
                      size="xs"
                      variant="outline"
                    >
                      <GitBranchIcon className="size-3" />
                      Switch
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div>
            <h3 className="text-xs font-medium uppercase text-muted-foreground">Checkpoints</h3>
            <div className="mt-2 grid gap-2">
              {state.history.checkpoints.length === 0 ? (
                <p className="text-sm text-muted-foreground">No checkpoints</p>
              ) : (
                state.history.checkpoints.slice(-3).reverse().map((checkpoint) => {
                  const editDraft = checkpointEditDrafts[checkpoint.id] ?? ""
                  const canReplay =
                    liveApi && !busy && checkpoint.capabilities.resume !== "unsupported"
                  const canBranch =
                    liveApi && !busy && checkpoint.capabilities.branch_from_here !== "unsupported"
                  return (
                    <div className="grid gap-2 rounded-md border p-2" key={checkpoint.id}>
                      <div className="flex min-w-0 items-center justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">
                            {String(checkpoint.summary.agent_id ?? checkpoint.thread_id)}
                          </p>
                          <p className="truncate text-xs text-muted-foreground">{checkpoint.id}</p>
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <Button aria-label={`Resume ${checkpoint.id}`} disabled={!canReplay} onClick={() => onResumeCheckpoint(checkpoint.id)} size="icon-xs" variant="outline">
                            <RotateCcwIcon className="size-3" />
                          </Button>
                          <Button aria-label={`Regenerate ${checkpoint.id}`} disabled={!canReplay} onClick={() => onRegenerateCheckpoint(checkpoint.id)} size="icon-xs" variant="outline">
                            <RefreshCwIcon className="size-3" />
                          </Button>
                          <Button aria-label={`Edit ${checkpoint.id}`} disabled={!canReplay} onClick={() => setEditingCheckpointId(checkpoint.id)} size="icon-xs" variant="outline">
                            <PencilIcon className="size-3" />
                          </Button>
                          <Button aria-label={`Create branch from ${checkpoint.id}`} disabled={!canBranch} onClick={() => onCreateBranchFromCheckpoint(checkpoint.id)} size="icon-xs" variant="outline">
                            <HistoryIcon className="size-3" />
                          </Button>
                        </div>
                      </div>
                      {editingCheckpointId === checkpoint.id ? (
                        <div className="grid gap-2">
                          <Textarea
                            aria-label={`Edited content for ${checkpoint.id}`}
                            className="min-h-20 text-sm"
                            disabled={!canReplay}
                            onChange={(event) =>
                              setCheckpointEditDrafts((current) => ({
                                ...current,
                                [checkpoint.id]: event.target.value,
                              }))
                            }
                            placeholder="Edited checkpoint content"
                            value={editDraft}
                          />
                          <div className="flex justify-end gap-1">
                            <Button aria-label={`Cancel edit ${checkpoint.id}`} disabled={busy} onClick={() => setEditingCheckpointId(null)} size="icon-xs" variant="ghost">
                              <XIcon className="size-3" />
                            </Button>
                            <Button
                              aria-label={`Apply edit ${checkpoint.id}`}
                              disabled={!canReplay || !editDraft.trim()}
                              onClick={() => {
                                onEditCheckpoint(checkpoint.id, editDraft.trim())
                                setEditingCheckpointId(null)
                              }}
                              size="icon-xs"
                              variant="outline"
                            >
                              <CheckIcon className="size-3" />
                            </Button>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </Section>
      </div>
    </aside>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-0 rounded-md border bg-muted/30 px-2 py-1">
      <p className="truncate text-[0.65rem] text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold">{value}</p>
    </div>
  )
}

function RailButton({
  icon,
  label,
  onClick,
}: {
  icon: ReactNode
  label: string
  onClick: () => void
}) {
  return (
    <Button aria-label={label} onClick={onClick} size="icon-sm" title={label} variant="ghost">
      {icon}
    </Button>
  )
}

function ViewButton({
  icon,
  label,
  onClick,
}: {
  icon: ReactNode
  label: string
  onClick: () => void
}) {
  return (
    <Button className="justify-start text-xs" onClick={onClick} size="sm" type="button" variant="outline">
      {icon}
      {label}
    </Button>
  )
}

function Section({
  action,
  children,
  title,
}: {
  action?: ReactNode
  children: ReactNode
  title: string
}) {
  return (
    <section className="mt-4 grid gap-3 rounded-md border bg-background p-3">
      <div className="flex min-w-0 items-center justify-between gap-2">
        <h2 className="truncate text-sm font-medium">{title}</h2>
        {action}
      </div>
      <div className="grid gap-3">{children}</div>
    </section>
  )
}

function payloadPreview(payload: InterruptRequest["payload"]) {
  return JSON.stringify(payload, null, 2)
}
