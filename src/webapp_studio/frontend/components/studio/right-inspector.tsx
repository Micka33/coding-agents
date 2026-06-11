"use client"

import type { ReactNode } from "react"
import { useEffect, useState } from "react"
import {
  ActivityIcon,
  AppWindowIcon,
  CheckIcon,
  ChevronRightIcon,
  CopyIcon,
  PlayIcon,
  FileTextIcon,
  FolderIcon,
  GitCompareIcon,
  PanelRightCloseIcon,
  SquareIcon,
  TerminalIcon,
  WrapTextIcon,
  XIcon,
} from "lucide-react"

import { ActivityPanel } from "@/components/studio/activity-panel"
import { GeneratedUiPanel } from "@/components/studio/generated-ui-panel"
import { StatusPill } from "@/components/studio/status-pill"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { StudioApiClient } from "@/lib/studio/api-client"
import type {
  GeneratedUiSpec,
  StudioChanges,
  StudioFileItem,
  StudioSession,
  StudioState,
  StudioTerminalSession,
} from "@/lib/studio/schemas"
import { cn } from "@/lib/utils"

export type InspectorView =
  | { kind: "empty" }
  | { kind: "files"; selectedFileId?: string }
  | { kind: "activity"; agentId?: string }
  | { kind: "changes"; selectedChangeId?: string }
  | { kind: "terminal"; sessionId?: string }
  | { kind: "generated-ui"; specId?: string }
export type OpenInspectorView = Exclude<InspectorView, { kind: "empty" }>

type RightInspectorProps = {
  apiClient: StudioApiClient | null
  changes: StudioChanges | null
  files: StudioFileItem[]
  generatedUi: GeneratedUiSpec[]
  onClose: () => void
  onViewChange: (view: InspectorView) => void
  placement: "sheet" | "side"
  session: StudioSession | null
  state: StudioState
  view: InspectorView
}

const inspectorOptions: Array<{
  icon: typeof FolderIcon
  kind: InspectorView["kind"]
  label: string
}> = [
  { icon: FolderIcon, kind: "files", label: "Files" },
  { icon: ActivityIcon, kind: "activity", label: "Activity" },
  { icon: GitCompareIcon, kind: "changes", label: "Changes" },
  { icon: TerminalIcon, kind: "terminal", label: "Terminal" },
  { icon: AppWindowIcon, kind: "generated-ui", label: "Generated UI" },
]

export function RightInspector({
  apiClient,
  changes,
  files,
  generatedUi,
  onClose,
  onViewChange,
  placement,
  session,
  state,
  view,
}: RightInspectorProps) {
  const option = inspectorOptions.find((item) => item.kind === view.kind)
  const Icon = option?.icon ?? PanelRightCloseIcon
  const CloseIcon = placement === "sheet" ? XIcon : PanelRightCloseIcon
  const title = option?.label ?? "Inspector"

  return (
    <section
      className={`grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden bg-background ${
        placement === "sheet" ? "border-t" : "border-l"
      }`}
    >
      <div className="border-b px-3 py-2">
        {placement === "sheet" ? (
          <div aria-hidden className="mx-auto mb-2 h-1 w-10 rounded-full bg-muted-foreground/30" />
        ) : null}
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="size-4 shrink-0 text-emerald-600" />
          <h2 className="min-w-0 flex-1 truncate text-sm font-medium">{title}</h2>
          {state.activity.active_agent_ids.length > 0 ? (
            <StatusPill label={`${state.activity.active_agent_ids.length} active`} tone="amber" />
          ) : null}
          <Button aria-label="Close inspector" onClick={onClose} size="icon-sm" variant="ghost">
            <CloseIcon className="size-4" />
          </Button>
        </div>
        <div className="mt-2 flex min-w-0 gap-1 overflow-x-auto">
          {inspectorOptions.map((item) => {
            const OptionIcon = item.icon
            return (
              <Button
                aria-label={`Open ${item.label}`}
                key={item.kind}
                onClick={() => onViewChange({ kind: item.kind } as InspectorView)}
                size="icon-sm"
                title={item.label}
                variant={view.kind === item.kind ? "secondary" : "ghost"}
              >
                <OptionIcon className="size-4" />
              </Button>
            )
          })}
        </div>
      </div>

      <div className="min-h-0 overflow-auto p-3">
        <InspectorBody
          apiClient={apiClient}
          changes={changes}
          files={files}
          generatedUi={generatedUi}
          onViewChange={onViewChange}
          session={session}
          state={state}
          view={view}
        />
      </div>
    </section>
  )
}

function InspectorBody({
  apiClient,
  changes,
  files,
  generatedUi,
  onViewChange,
  session,
  state,
  view,
}: {
  apiClient: StudioApiClient | null
  changes: StudioChanges | null
  files: StudioFileItem[]
  generatedUi: GeneratedUiSpec[]
  onViewChange: (view: InspectorView) => void
  session: StudioSession | null
  state: StudioState
  view: InspectorView
}) {
  if (view.kind === "files") {
    return <FilesInspector files={files} selectedFileId={view.selectedFileId} />
  }

  if (view.kind === "activity") {
    return (
      <ActivityPanel
        focusedAgentId={view.agentId}
        onAgentSelect={(agentId) => onViewChange({ kind: "activity", agentId })}
        onBack={() => onViewChange({ kind: "activity" })}
        state={state}
      />
    )
  }

  if (view.kind === "changes") {
    return (
      <ChangesInspector
        apiClient={apiClient}
        changes={changes}
        selectedChangeId={view.selectedChangeId}
      />
    )
  }

  if (view.kind === "terminal") {
    return <TerminalInspector apiClient={apiClient} session={session} />
  }

  if (view.kind === "generated-ui") {
    return <GeneratedUiPanel focusedSpecId={view.specId} specs={generatedUi} />
  }

  return (
    <div className="grid h-full min-h-48 place-items-center rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
      Select a workspace view.
    </div>
  )
}

function FilesInspector({
  files,
  selectedFileId,
}: {
  files: StudioFileItem[]
  selectedFileId?: string
}) {
  const selected = files.find((file) => file.id === selectedFileId) ?? files[0]

  if (files.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
        No files in this thread
      </div>
    )
  }

  return (
    <div className="grid gap-3">
      {selected ? (
        <section className="rounded-md border">
          <div className="flex min-w-0 items-center justify-between gap-2 border-b px-3 py-2">
            <div className="min-w-0">
              <h3 className="truncate text-sm font-medium">{selected.filename}</h3>
              <p className="truncate text-xs text-muted-foreground">
                {selected.media_type ?? "unknown type"}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {fileDetails(selected)}
              </p>
            </div>
            <a
              className="inline-flex h-8 items-center rounded-md border px-2 text-xs hover:bg-muted"
              href={selected.download_url}
            >
              Download
            </a>
          </div>
          {selected.preview_url && selected.preview_mode === "text" ? (
            <TextFilePreview filename={selected.filename} url={selected.preview_url} />
          ) : selected.preview_url ? (
            <iframe
              className="h-72 w-full bg-muted"
              src={selected.preview_url}
              title={selected.filename}
            />
          ) : (
            <div className="p-4 text-sm text-muted-foreground">
              Preview is not available for this file type.
            </div>
          )}
        </section>
      ) : null}

      <div className="grid gap-2">
        {files.map((file) => (
          <div className="rounded-md border p-3" key={file.id}>
            <div className="flex min-w-0 items-center gap-2">
              <FileTextIcon className="size-4 shrink-0 text-emerald-600" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{file.filename}</p>
                <p className="truncate text-xs text-muted-foreground">
                  #{file.event_seq ?? "-"} {formatBytes(file.size_bytes)}
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  {file.added_by ? `added by ${file.added_by}` : "added by unknown"}
                </p>
              </div>
              <a
                className="inline-flex h-8 items-center rounded-md border px-2 text-xs hover:bg-muted"
                href={file.download_url}
              >
                Download
              </a>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function TextFilePreview({ filename, url }: { filename: string; url: string }) {
  const [loaded, setLoaded] = useState<{
    error: string | null
    text: string
    url: string
  } | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(url)
      .then((response) => {
        if (!response.ok) {
          throw new Error("Unable to load preview.")
        }
        return response.text()
      })
      .then((text) => {
        if (!cancelled) {
          setLoaded({ error: null, text, url })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setLoaded({
            error: error instanceof Error ? error.message : "Unable to load preview.",
            text: "",
            url,
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [url])

  const preview = loaded?.url === url ? loaded : null

  if (!preview) {
    return <div className="p-4 text-sm text-muted-foreground">Loading preview...</div>
  }

  if (preview.error) {
    return <div className="p-4 text-sm text-muted-foreground">{preview.error}</div>
  }

  return (
    <pre
      aria-label={`Raw preview for ${filename}`}
      className="max-h-72 overflow-auto whitespace-pre-wrap break-words bg-muted p-3 font-mono text-xs leading-relaxed"
    >
      {preview.text}
    </pre>
  )
}

function ChangesInspector({
  apiClient,
  changes,
  selectedChangeId,
}: {
  apiClient: StudioApiClient | null
  changes: StudioChanges | null
  selectedChangeId?: string
}) {
  const changeItems = changes?.changes ?? []
  const [manualSelectedId, setManualSelectedId] = useState<string | null>(null)
  const [diff, setDiff] = useState("")
  const [error, setError] = useState<string | null>(null)
  const selectedId =
    selectedChangeId ??
    (changeItems.some((change) => change.id === manualSelectedId)
      ? manualSelectedId
      : changeItems[0]?.id ?? null)
  const selected =
    changeItems.find((change) => change.id === selectedId) ?? changeItems[0]

  useEffect(() => {
    if (!apiClient || !selected?.diff_url) {
      return
    }
    let cancelled = false
    apiClient
      .changeDiff(selected.diff_url)
      .then((result) => {
        if (!cancelled) {
          setDiff(result.diff)
        }
      })
      .catch((nextError) => {
        if (!cancelled) {
          setDiff("")
          setError(nextError instanceof Error ? nextError.message : "Unable to load diff.")
        }
      })
    return () => {
      cancelled = true
    }
  }, [apiClient, selected?.diff_url])

  if (changes?.supported === false) {
    return (
      <UnsupportedInspector
        icon={<GitCompareIcon className="size-5" />}
        title="Changes are not available"
      />
    )
  }

  if (changeItems.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
        No file changes in this workspace
      </div>
    )
  }

  return (
    <div className="grid gap-3">
      <div className="grid gap-2">
        {changeItems.map((change) => (
          <button
            aria-label={`Open change for ${change.path}`}
            className={`flex min-w-0 items-center gap-2 rounded-md border p-2 text-left hover:bg-muted ${
              change.id === selected?.id ? "bg-muted" : ""
            }`}
            key={change.id}
            onClick={() => setManualSelectedId(change.id)}
            title={`Open change for ${change.path}`}
            type="button"
          >
            <GitCompareIcon className="size-4 shrink-0 text-emerald-600" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{change.path}</p>
              <p className="truncate text-xs text-muted-foreground">
                {change.status} {change.source ? `from ${change.source}` : ""}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {changeAssociation(change)}
              </p>
            </div>
            <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground" />
          </button>
        ))}
      </div>
      <section className="rounded-md border">
        <div className="flex min-w-0 items-center justify-between gap-2 border-b px-3 py-2">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-medium">{selected?.path}</h3>
            <p className="truncate text-xs text-muted-foreground">
              {selected ? changeAssociation(selected) : "changed"}
            </p>
          </div>
          {selected ? <StatusPill label={selected.status} tone="sky" /> : null}
        </div>
        {error ? (
          <p className="p-3 text-sm text-destructive">{error}</p>
        ) : (
          <PreformattedBlock
            className="max-h-[32rem] bg-muted/40 text-xs"
            copyAriaLabel="Copy diff output"
            defaultWrap={false}
            emptyLabel="No textual diff available."
            value={diff}
          />
        )}
      </section>
    </div>
  )
}

function TerminalInspector({
  apiClient,
  session,
}: {
  apiClient: StudioApiClient | null
  session: StudioSession | null
}) {
  const [terminal, setTerminal] = useState<StudioTerminalSession | null>(null)
  const [cursor, setCursor] = useState(0)
  const [output, setOutput] = useState("")
  const [input, setInput] = useState("")
  const [error, setError] = useState<string | null>(null)
  const cwd = terminal?.cwd ?? session?.resolved_root_dir ?? "unknown cwd"
  const running = terminal?.status === "running"
  const terminalSessionId = terminal?.session_id
  const terminalStatus = terminal?.status
  useEffect(() => {
    if (!apiClient || !terminalSessionId || terminalStatus !== "running") {
      return
    }
    let cancelled = false
    const timer = window.setInterval(() => {
      apiClient
        .terminalOutput(terminalSessionId, cursor)
        .then((result) => {
          if (cancelled) {
            return
          }
          setCursor(result.cursor)
          if (result.chunks.length > 0) {
            setOutput((value) => value + result.chunks.map((chunk) => chunk.text).join(""))
          }
          setTerminal((value) =>
            value ? { ...value, status: result.status } : value
          )
        })
        .catch((nextError) => {
          if (!cancelled) {
            setError(nextError instanceof Error ? nextError.message : "Unable to read terminal output.")
          }
        })
    }, 750)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [apiClient, cursor, terminalSessionId, terminalStatus])

  async function startTerminal() {
    if (!apiClient) {
      return
    }
    setError(null)
    const next = await apiClient.createTerminalSession()
    setTerminal(next)
    setCursor(0)
    setOutput("")
  }

  async function sendInput() {
    if (!apiClient || !terminal || !input) {
      return
    }
    const data = input.endsWith("\n") ? input : `${input}\n`
    setInput("")
    setError(null)
    setTerminal(await apiClient.sendTerminalInput(terminal.session_id, data))
  }

  async function stopTerminal() {
    if (!apiClient || !terminal) {
      return
    }
    setError(null)
    setTerminal(await apiClient.terminateTerminal(terminal.session_id))
  }

  if (!apiClient) {
    return (
      <UnsupportedInspector
        icon={<TerminalIcon className="size-5" />}
        title="Terminal requires a live backend"
      />
    )
  }

  return (
    <div className="grid gap-3">
      <section className="rounded-md border">
        <div className="flex min-w-0 items-center justify-between gap-2 border-b px-3 py-2">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-medium">Terminal</h3>
            <p className="truncate text-xs text-muted-foreground">{cwd}</p>
          </div>
          {terminal ? (
            <StatusPill label={terminal.status} tone={running ? "emerald" : "amber"} />
          ) : null}
        </div>
        <PreformattedBlock
          className="min-h-72 max-h-[32rem] bg-black font-mono text-xs text-white"
          copyAriaLabel="Copy terminal output"
          defaultWrap={false}
          emptyLabel="No terminal output yet."
          value={output}
        />
      </section>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <div className="flex gap-2">
        {terminal ? (
          <>
            <Input
              aria-label="Terminal input"
              disabled={!running}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault()
                  void sendInput()
                }
              }}
              placeholder="Command"
              value={input}
            />
            <Button aria-label="Send terminal input" disabled={!running || !input.trim()} onClick={() => void sendInput()} size="icon-sm" type="button">
              <PlayIcon className="size-4" />
            </Button>
            <Button aria-label="Stop terminal" disabled={!running} onClick={() => void stopTerminal()} size="icon-sm" type="button" variant="outline">
              <SquareIcon className="size-4" />
            </Button>
          </>
        ) : (
          <Button onClick={() => void startTerminal()} type="button">
            <TerminalIcon className="size-4" />
            Open terminal
          </Button>
        )}
      </div>
    </div>
  )
}

function PreformattedBlock({
  className,
  copyAriaLabel,
  defaultWrap,
  emptyLabel,
  value,
}: {
  className?: string
  copyAriaLabel: string
  defaultWrap: boolean
  emptyLabel: string
  value: string
}) {
  const [copied, setCopied] = useState(false)
  const [wrapped, setWrapped] = useState(defaultWrap)
  const displayValue = value || emptyLabel
  const canCopy = value.length > 0

  async function copy() {
    if (
      !canCopy ||
      typeof navigator === "undefined" ||
      !navigator.clipboard?.writeText
    ) {
      return
    }

    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div
      className="group/preformatted relative"
      data-preformatted-wrap={wrapped ? "true" : "false"}
    >
      <div className="absolute top-2 right-2 z-10 flex items-center gap-1">
        <PreformattedActionButton
          ariaLabel={copied ? "Preformatted content copied" : copyAriaLabel}
          disabled={!canCopy}
          label="copier"
          onClick={copy}
        >
          {copied ? (
            <CheckIcon className="size-3" />
          ) : (
            <CopyIcon className="size-3" />
          )}
        </PreformattedActionButton>
        <PreformattedActionButton
          ariaLabel={
            wrapped ? "Disable line wrapping" : "Enable line wrapping"
          }
          ariaPressed={wrapped}
          label={wrapped ? "défilement horizontal" : "retour à la ligne"}
          onClick={() => setWrapped((value) => !value)}
        >
          <WrapTextIcon className="size-3" />
        </PreformattedActionButton>
      </div>
      <pre
        className={cn(
          "max-w-full overflow-auto p-3 pt-10",
          wrapped
            ? "whitespace-pre-wrap break-words [overflow-wrap:anywhere]"
            : "whitespace-pre break-normal",
          className
        )}
      >
        {displayValue}
      </pre>
    </div>
  )
}

function PreformattedActionButton({
  ariaLabel,
  ariaPressed,
  children,
  disabled = false,
  label,
  onClick,
}: {
  ariaLabel: string
  ariaPressed?: boolean
  children: ReactNode
  disabled?: boolean
  label: string
  onClick: () => void
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          aria-label={ariaLabel}
          aria-pressed={ariaPressed}
          className="border-border bg-background/80 opacity-100 transition-opacity supports-[backdrop-filter]:bg-background/70 supports-[backdrop-filter]:backdrop-blur sm:opacity-0 sm:group-focus-within/preformatted:opacity-100 sm:group-hover/preformatted:opacity-100"
          disabled={disabled}
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

function UnsupportedInspector({
  icon,
  title,
}: {
  icon: ReactNode
  title: string
}) {
  return (
    <div className="grid h-full min-h-48 place-items-center rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
      <div className="grid justify-items-center gap-2">
        <span className="text-emerald-600">{icon}</span>
        <span>{title}</span>
      </div>
    </div>
  )
}

function formatBytes(value: number | null) {
  if (value === null) {
    return "unknown size"
  }
  if (value < 1024) {
    return `${value} B`
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

function fileDetails(file: StudioFileItem) {
  const byline = file.added_by ? `added by ${file.added_by}` : "added by unknown"
  const seq = file.event_seq === null ? "event unknown" : `event #${file.event_seq}`
  return `${byline} - ${seq} - ${formatBytes(file.size_bytes)}`
}

function changeAssociation(change: StudioChanges["changes"][number]) {
  const actor = change.agent_id ? `agent ${change.agent_id}` : change.source ?? "workspace"
  const event = change.event_id ? `event ${change.event_id}` : "no event link"
  return `${actor} - ${event}`
}
