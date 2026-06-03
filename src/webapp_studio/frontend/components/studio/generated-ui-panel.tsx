"use client"

import type { ComponentRenderProps } from "@json-render/react"
import { JSONUIProvider, Renderer } from "@json-render/react"
import { shadcnComponents } from "@json-render/shadcn"
import type { ComponentType, Dispatch, ReactNode, SetStateAction } from "react"
import { createElement, useEffect, useMemo, useRef, useState } from "react"
import { PlayIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { StatusPill } from "@/components/studio/status-pill"
import type { GeneratedUiSpec } from "@/lib/studio/schemas"
import { toJsonRenderSpec } from "@/lib/studio/generated-ui"
import { cn } from "@/lib/utils"

type GeneratedUiPanelProps = {
  focusedSpecId?: string | null
  specs: GeneratedUiSpec[]
}

const registry = {
  Badge: shadcnAdapter(shadcnComponents.Badge as ShadcnRenderComponent),
  Stack: shadcnAdapter(shadcnComponents.Stack as ShadcnRenderComponent),
  Text: shadcnAdapter(shadcnComponents.Text as ShadcnRenderComponent),
  Metric,
  Plan,
  TaskList,
  FileList,
  ToolResult,
  CodeArtifact,
  TestSummary,
  TerminalOutput,
  WebPreview,
  GeneratedAction,
}

type GeneratedActionAuditEntry = {
  actionId: string
  confirmationRequired: boolean
  createdAt: string
  id: string
  params: Record<string, unknown>
  specId: string
}

type ShadcnRenderComponent = ComponentType<{
  children?: ReactNode
  emit: (event: string) => void
  on: (event: string) => { bound: boolean; shouldPreventDefault: boolean }
  props: Record<string, unknown>
}>

function shadcnAdapter(Component: ShadcnRenderComponent) {
  return function AdaptedShadcnElement({ children, element }: ComponentRenderProps) {
    return createElement(
      Component,
      {
        emit: () => undefined,
        on: () => ({ bound: false, shouldPreventDefault: false }),
        props: element.props,
      },
      children
    )
  }
}

export function GeneratedUiPanel({ focusedSpecId, specs }: GeneratedUiPanelProps) {
  const specRefs = useRef<Record<string, HTMLElement | null>>({})

  useEffect(() => {
    if (!focusedSpecId) {
      return
    }
    specRefs.current[focusedSpecId]?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    })
  }, [focusedSpecId])

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {specs.map((source) => {
        const focused = source.id === focusedSpecId
        return (
          <GeneratedUiSpecCard
            focused={focused}
            key={source.id}
            onNode={(node) => {
              specRefs.current[source.id] = node
            }}
            source={source}
          />
        )
      })}
    </div>
  )
}

function GeneratedUiSpecCard({
  focused,
  onNode,
  source,
}: {
  focused: boolean
  onNode: (node: HTMLElement | null) => void
  source: GeneratedUiSpec
}) {
  const [auditEntries, setAuditEntries] = useState<GeneratedActionAuditEntry[]>([])
  const rendered = useMemo(() => toJsonRenderSpec(source), [source])
  const handlers = useMemo(
    () => generatedActionHandlers(source, setAuditEntries),
    [source]
  )

  return (
    <section
      className={cn(
        "rounded-md border bg-background transition-colors",
        focused ? "border-emerald-500 ring-2 ring-emerald-500/30" : null
      )}
      data-testid={`generated-ui-spec-${source.id}`}
      ref={onNode}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-base font-medium">{source.id}</h2>
          <p className="text-sm text-muted-foreground">{source.version}</p>
        </div>
        <StatusPill
          label={rendered.errors.length === 0 ? "valid" : "invalid"}
          tone={rendered.errors.length === 0 ? "emerald" : "rose"}
        />
      </div>
      <div className="grid gap-4 p-4">
        {rendered.spec ? (
          <JSONUIProvider
            handlers={handlers}
            initialState={rendered.spec.state}
            registry={registry}
          >
            <Renderer registry={registry} spec={rendered.spec} />
          </JSONUIProvider>
        ) : (
          <div className="rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-100">
            {rendered.errors.map((error) => (
              <p key={error}>{error}</p>
            ))}
          </div>
        )}
        <GeneratedActionAudit entries={auditEntries} specId={source.id} />
      </div>
    </section>
  )
}

function GeneratedAction({ element, on }: ComponentRenderProps) {
  const label = textProp(element.props.label, "Run action")
  const variant =
    textProp(element.props.variant, "outline") === "destructive"
      ? "destructive"
      : "outline"
  const press = on("press")

  return (
    <Button
      disabled={!press.bound}
      onClick={() => press.emit()}
      size="sm"
      type="button"
      variant={variant}
    >
      <PlayIcon className="size-4" />
      {label}
    </Button>
  )
}

function GeneratedActionAudit({
  entries,
  specId,
}: {
  entries: GeneratedActionAuditEntry[]
  specId: string
}) {
  if (entries.length === 0) {
    return null
  }

  return (
    <section
      aria-label={`Generated action audit ${specId}`}
      className="rounded-md border bg-muted/30 p-3"
    >
      <h3 className="text-sm font-medium">Action audit</h3>
      <div className="mt-3 grid gap-2">
        {entries.map((entry) => (
          <div className="rounded-md border bg-background p-3" key={entry.id}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs">{entry.actionId}</span>
              <StatusPill
                label={entry.confirmationRequired ? "confirmed" : "recorded"}
                tone={entry.confirmationRequired ? "emerald" : "sky"}
              />
              <time className="ms-auto text-xs text-muted-foreground">
                {entry.createdAt}
              </time>
            </div>
            <pre className="mt-2 overflow-auto rounded-md bg-muted p-2 text-xs">
              {formatJson(entry.params)}
            </pre>
          </div>
        ))}
      </div>
    </section>
  )
}

function generatedActionHandlers(
  source: GeneratedUiSpec,
  setAuditEntries: Dispatch<SetStateAction<GeneratedActionAuditEntry[]>>
) {
  return Object.fromEntries(
    Object.entries(source.actions).map(([actionId, action]) => [
      actionId,
      (params: Record<string, unknown> = {}) => {
        if (action.audit === "none") {
          return
        }
        setAuditEntries((entries) => [
          {
            actionId,
            confirmationRequired: action.confirmation_required,
            createdAt: new Date().toISOString(),
            id: `${source.id}:${actionId}:${Date.now()}`,
            params,
            specId: source.id,
          },
          ...entries,
        ].slice(0, 8))
      },
    ])
  )
}

function Metric({ element }: ComponentRenderProps) {
  const label = textProp(element.props.label, "Metric")
  const value = textProp(element.props.value, "-")

  return (
    <div className="rounded-md border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900 dark:bg-emerald-950">
      <p className="text-sm text-emerald-800 dark:text-emerald-200">{label}</p>
      <p className="mt-2 text-3xl font-semibold text-emerald-950 dark:text-emerald-50">
        {value}
      </p>
    </div>
  )
}

function Plan({ element }: ComponentRenderProps) {
  return <StructuredBlock title={textProp(element.props.title, "Plan")} />
}

function TaskList({ element }: ComponentRenderProps) {
  return <StructuredBlock title={textProp(element.props.title, "Task list")} />
}

function FileList({ element }: ComponentRenderProps) {
  return <StructuredBlock title={textProp(element.props.title, "Files")} />
}

function ToolResult({ element }: ComponentRenderProps) {
  return <StructuredBlock title={textProp(element.props.title, "Tool result")} />
}

function CodeArtifact({ element }: ComponentRenderProps) {
  return <StructuredBlock title={textProp(element.props.title, "Code artifact")} />
}

function TestSummary({ element }: ComponentRenderProps) {
  return <StructuredBlock title={textProp(element.props.title, "Test summary")} />
}

function TerminalOutput({ element }: ComponentRenderProps) {
  return <StructuredBlock title={textProp(element.props.title, "Terminal output")} />
}

function WebPreview({ element }: ComponentRenderProps) {
  return <StructuredBlock title={textProp(element.props.title, "Web preview")} />
}

function StructuredBlock({ title }: { title: string }) {
  return (
    <div className="rounded-md border border-sky-200 bg-sky-50 p-4 text-sky-950 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-100">
      {title}
    </div>
  )
}

function textProp(value: unknown, fallback: string) {
  if (typeof value === "string") {
    return value
  }
  if (typeof value === "number") {
    return String(value)
  }
  return fallback
}

function formatJson(value: unknown) {
  return JSON.stringify(value, null, 2)
}
