"use client"

import { FileTextIcon } from "lucide-react"

import { Terminal, TerminalContent } from "@/components/ai-elements/terminal"
import { RichMarkdown } from "@/components/studio/rich-markdown"
import { StatusPill } from "@/components/studio/status-pill"
import { ToolCallList } from "@/components/studio/tool-call-list"
import type { StudioState } from "@/lib/studio/schemas"

type ActivityPanelProps = {
  focusedAgentId?: string
  state: StudioState
}

export function ActivityPanel({ focusedAgentId, state }: ActivityPanelProps) {
  const agentStates = focusedAgentId
    ? state.conversation.agent_states.filter((agent) => agent.agent_id === focusedAgentId)
    : state.conversation.agent_states
  const privateThreads = focusedAgentId
    ? state.activity.private_threads.filter((thread) => thread.agent_id === focusedAgentId)
    : state.activity.private_threads

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <section className="rounded-md border bg-background p-4">
        <h2 className="text-base font-medium">Agents</h2>
        <div className="mt-4 grid gap-2">
          {agentStates.map((agent) => (
            <div className="rounded-md border p-3" key={agent.agent_id}>
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate font-medium">{agent.agent_id}</span>
                <StatusPill
                  label={agent.running ? "running" : agent.queued ? "queued" : "idle"}
                  tone={agent.running ? "emerald" : agent.queued ? "amber" : "slate"}
                />
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                Delivered through #{agent.last_delivered_seq}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="min-h-[40rem] rounded-md border bg-background">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <div>
            <h2 className="text-base font-medium">Private Activity</h2>
            <p className="text-sm text-muted-foreground">
              {privateThreads.length} observable threads
            </p>
          </div>
          <StatusPill label="Read-only" tone="sky" />
        </div>
        <div className="grid gap-4 p-4">
          {privateThreads.length === 0 ? (
            <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
              No private activity in this snapshot
            </div>
          ) : (
            privateThreads.map((thread) => (
              <article className="rounded-md border" key={thread.thread_id}>
                <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
                  <div className="min-w-0">
                    <h3 className="truncate font-medium">{thread.agent_id ?? thread.thread_id}</h3>
                    <p className="truncate text-sm text-muted-foreground">{thread.thread_id}</p>
                  </div>
                </div>
                <Terminal className="rounded-none border-0" output="">
                  <TerminalContent>
                    {thread.messages.map((message, index) => (
                      <div className="mb-4 last:mb-0" key={`${thread.thread_id}-${index}`}>
                        <div>
                          <span className="text-sky-300">{message.type}</span>{" "}
                          {message.name && <span>{message.name}</span>}
                        </div>
                        <RichMarkdown
                          className="mt-2 text-zinc-100"
                          content={message.content || "empty message"}
                        />
                        <ToolCallList value={message.tool_calls} />
                      </div>
                    ))}
                  </TerminalContent>
                </Terminal>
              </article>
            ))
          )}

          <section className="rounded-md border p-4">
            <h3 className="flex items-center gap-2 font-medium">
              <FileTextIcon className="size-4 text-emerald-600" />
              Deliveries
            </h3>
            <div className="mt-3 grid gap-2">
              {state.conversation.deliveries.length === 0 ? (
                <p className="text-sm text-muted-foreground">No delivery records</p>
              ) : (
                state.conversation.deliveries.map((delivery) => (
                  <div className="rounded-md border p-3" key={delivery.id}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{delivery.agent_id}</span>
                      <StatusPill label={delivery.status} tone="emerald" />
                    </div>
                    {delivery.error && (
                      <p className="mt-2 text-sm text-rose-700 dark:text-rose-300">
                        {delivery.error}
                      </p>
                    )}
                  </div>
                ))
              )}
            </div>
          </section>
        </div>
      </section>
    </div>
  )
}
