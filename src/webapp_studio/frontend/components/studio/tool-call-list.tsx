"use client"

import { ChevronDownIcon } from "lucide-react"

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"
import type { StudioToolCall, StudioToolState } from "@/lib/studio/tool-calls"
import { studioToolCallsFromValue } from "@/lib/studio/tool-calls"

type ToolCallListProps = {
  resultByToolCallId?: ReadonlyMap<string, unknown>
  value: unknown
}

const inProgressStates = new Set<StudioToolState>([
  "approval-requested",
  "input-available",
  "input-streaming",
])

export function ToolCallList({ resultByToolCallId, value }: ToolCallListProps) {
  const calls = studioToolCallsFromValue(value).map((call) =>
    toolCallWithResult(call, resultByToolCallId)
  )
  if (calls.length === 0) {
    return null
  }

  const inProgressCalls = calls.filter((call) =>
    inProgressStates.has(call.state)
  )
  const completedCalls = calls.filter(
    (call) => !inProgressStates.has(call.state)
  )

  return (
    <div className="mt-3 grid max-w-full min-w-0 gap-2">
      <ActionGroup calls={completedCalls} kind="completed" />
      <ActionGroup calls={inProgressCalls} kind="in-progress" />
    </div>
  )
}

function toolCallWithResult(
  call: StudioToolCall,
  resultByToolCallId: ReadonlyMap<string, unknown> | undefined
) {
  if (
    call.output !== undefined ||
    call.errorText ||
    !resultByToolCallId?.has(call.id)
  ) {
    return call
  }

  return {
    ...call,
    output: resultByToolCallId.get(call.id),
    state: "output-available" as const,
  }
}

function ActionGroup({
  calls,
  kind,
}: {
  calls: StudioToolCall[]
  kind: "completed" | "in-progress"
}) {
  if (calls.length === 0) {
    return null
  }
  if (calls.length === 1) {
    return (
      <ActionRow
        call={calls[0]}
        tone={kind === "in-progress" ? "in-progress" : "default"}
      />
    )
  }

  return (
    <Collapsible className="group/action-group min-w-0">
      <CollapsibleTrigger
        aria-label={groupLabel(calls.length, kind)}
        className={cn(
          "flex w-full min-w-0 items-center justify-between gap-2 rounded-md border px-3 py-2 text-left text-sm hover:bg-muted",
          kind === "in-progress"
            ? "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100"
            : "bg-muted/35"
        )}
      >
        <span className="min-w-0 truncate font-medium">
          {groupLabel(calls.length, kind)}
        </span>
        <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/action-group:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 grid gap-1.5">
        {calls.map((call) => (
          <ActionRow call={call} key={call.id} />
        ))}
      </CollapsibleContent>
    </Collapsible>
  )
}

function ActionRow({
  call,
  tone = "default",
}: {
  call: StudioToolCall
  tone?: "default" | "in-progress"
}) {
  const summary = actionSummary(call)

  return (
    <Collapsible
      className={cn(
        "group/action-row min-w-0 rounded-md border bg-background",
        tone === "in-progress" &&
          "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100"
      )}
    >
      <CollapsibleTrigger
        aria-label={`Open action ${summary}`}
        className={cn(
          "flex w-full min-w-0 items-center justify-between gap-2 px-3 py-2 text-left text-sm",
          tone === "in-progress"
            ? "hover:bg-amber-100/70 dark:hover:bg-amber-900/70"
            : "hover:bg-muted/50"
        )}
      >
        <span className="min-w-0 truncate">
          <span className="font-mono text-muted-foreground">&gt;</span>{" "}
          {summary}
        </span>
        <ChevronDownIcon className="size-3.5 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/action-row:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="grid gap-2 border-t p-2">
        <CompactValue label="Tool" value={call.name} />
        <CompactValue label="Input" value={call.input} />
        <CompactValue
          label={call.errorText ? "Result" : "Result"}
          value={call.errorText ?? call.output ?? "No result yet."}
          tone={call.errorText ? "error" : "default"}
        />
      </CollapsibleContent>
    </Collapsible>
  )
}

function CompactValue({
  label,
  tone = "default",
  value,
}: {
  label: string
  tone?: "default" | "error"
  value: unknown
}) {
  return (
    <div className="grid min-w-0 gap-1">
      <span className="text-xs font-medium text-muted-foreground uppercase">
        {label}
      </span>
      <pre
        className={cn(
          "max-h-44 min-w-0 overflow-auto rounded-md px-2 py-1.5 font-mono text-xs break-words whitespace-pre-wrap",
          tone === "error"
            ? "bg-destructive/10 text-destructive"
            : "bg-muted/45 text-foreground"
        )}
      >
        {formatValue(value)}
      </pre>
    </div>
  )
}

function groupLabel(count: number, kind: "completed" | "in-progress") {
  const plural = count > 1 ? "s" : ""
  if (kind === "in-progress") {
    return `${count} action${plural} en cours`
  }
  return `${count} action${plural} effectuée${plural}`
}

function actionSummary(call: StudioToolCall) {
  const input = isRecord(call.input) ? call.input : {}
  const outputText = firstSentence(textOutput(call.output))

  if (call.name === "task") {
    const subagent = textField(input, "subagent_type") ?? "subagent"
    const description = textField(input, "description")
    return compact(`${subagent} -> ${outputText || description || "completed"}`)
  }

  if (call.name.startsWith("ask_")) {
    const target = call.name.replace(/^ask_/, "").replace(/_/g, "-")
    const message = textField(input, "message")
    return compact(
      outputText
        ? `${target} -> ${outputText}`
        : `ask ${target}: ${message ?? "message"}`
    )
  }

  if (call.name === "execute") {
    return compact(`run ${textField(input, "command") ?? "command"}`)
  }

  if (call.kind === "terminal") {
    return compact(`run ${textField(input, "command") ?? call.name}`)
  }

  if (call.kind === "test-results") {
    return compact(testSummary(call.output) ?? call.name)
  }

  if (call.name === "grep") {
    return compact(
      `grep ${quote(textField(input, "pattern") ?? "pattern")} in ${
        toolPath(input) ?? "."
      }`
    )
  }

  if (call.name === "glob") {
    return compact(`glob ${quote(textField(input, "pattern") ?? "*")}`)
  }

  if (call.name === "ls") {
    return compact(`ls ${toolPath(input) ?? "."}`)
  }

  if (call.name === "read_file") {
    return compact(`read ${toolPath(input) ?? "file"}`)
  }

  if (call.name === "write_file") {
    return compact(`write ${toolPath(input) ?? "file"}`)
  }

  if (call.name === "edit_file") {
    return compact(`edit ${toolPath(input) ?? "file"}`)
  }

  if (call.name === "web_search") {
    return compact(`search ${quote(textField(input, "query") ?? "query")}`)
  }

  if (call.name === "fetch_url") {
    return compact(`fetch ${textField(input, "url") ?? "url"}`)
  }

  return compact(`${call.name} ${oneLineValue(call.input)}`)
}

function toolPath(input: Record<string, unknown>) {
  return (
    textField(input, "path") ??
    textField(input, "folder") ??
    textField(input, "directory") ??
    textField(input, "root")
  )
}

function textOutput(value: unknown) {
  if (typeof value === "string") {
    return value
  }
  if (isRecord(value)) {
    return textField(value, "output") ?? textField(value, "text")
  }
  return undefined
}

function testSummary(value: unknown) {
  if (!isRecord(value)) {
    return undefined
  }
  const passed = numberField(value, "passed")
  const failed = numberField(value, "failed")
  const skipped = numberField(value, "skipped")
  const parts = [
    passed === undefined ? undefined : `${passed} passed`,
    failed === undefined ? undefined : `${failed} failed`,
    skipped === undefined ? undefined : `${skipped} skipped`,
  ].filter((part): part is string => Boolean(part))

  return parts.length > 0 ? parts.join(", ") : undefined
}

function numberField(record: Record<string, unknown>, key: string) {
  const value = record[key]
  return typeof value === "number" ? value : undefined
}

function firstSentence(value: string | undefined) {
  if (!value) {
    return undefined
  }
  const normalized = value.replace(/\s+/g, " ").trim()
  const sentenceEnd = [".", "!", "?"]
    .map((mark) => normalized.indexOf(mark))
    .filter((index) => index >= 0)
    .sort((left, right) => left - right)[0]

  if (sentenceEnd === undefined) {
    return normalized
  }
  return normalized.slice(0, sentenceEnd + 1)
}

function textField(record: Record<string, unknown>, key: string) {
  const value = record[key]
  return typeof value === "string" && value.trim() ? value.trim() : undefined
}

function oneLineValue(value: unknown) {
  return formatValue(value).replace(/\s+/g, " ").trim()
}

function formatValue(value: unknown) {
  if (value === undefined || value === null) {
    return ""
  }
  if (typeof value === "string") {
    return value
  }
  return JSON.stringify(value, null, 2)
}

function quote(value: string) {
  return value.includes(" ") ? `"${value}"` : value
}

function compact(value: string) {
  const normalized = value.replace(/\s+/g, " ").trim()
  if (normalized.length <= 180) {
    return normalized
  }
  return `${normalized.slice(0, 177)}...`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}
