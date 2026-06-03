"use client"

import {
  Artifact,
  ArtifactContent,
  ArtifactDescription,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact"
import {
  FileTree,
  FileTreeFile,
} from "@/components/ai-elements/file-tree"
import {
  Terminal,
  TerminalContent,
} from "@/components/ai-elements/terminal"
import {
  TestResults,
  TestResultsContent,
  TestResultsProgress,
  TestResultsSummary,
} from "@/components/ai-elements/test-results"
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from "@/components/ai-elements/tool"
import {
  WebPreview,
  WebPreviewNavigation,
  WebPreviewUrl,
} from "@/components/ai-elements/web-preview"
import type { StudioToolCall } from "@/lib/studio/tool-calls"
import { studioToolCallsFromValue } from "@/lib/studio/tool-calls"

type ToolCallListProps = {
  value: unknown
}

export function ToolCallList({ value }: ToolCallListProps) {
  const calls = studioToolCallsFromValue(value)
  if (calls.length === 0) {
    return null
  }

  return (
    <div className="mt-3 grid gap-3">
      {calls.map((call) => (
        <Tool className="mb-0" defaultOpen key={call.id}>
          <ToolHeader
            state={call.state}
            title={toolTitle(call)}
            toolName={call.name}
            type="dynamic-tool"
          />
          <ToolContent>
            <ToolInput input={call.input} />
            <SpecializedToolOutput call={call} />
          </ToolContent>
        </Tool>
      ))}
    </div>
  )
}

function SpecializedToolOutput({ call }: { call: StudioToolCall }) {
  if (call.kind === "terminal") {
    return <TerminalOutput call={call} />
  }
  if (call.kind === "test-results") {
    return <TestResultOutput call={call} />
  }
  if (call.kind === "file-tree") {
    return <FileTreeOutput call={call} />
  }
  if (call.kind === "web-preview") {
    return <WebPreviewOutput call={call} />
  }
  if (call.kind === "artifact") {
    return <ArtifactOutput call={call} />
  }
  return (
    <ToolOutput
      errorText={call.errorText}
      output={call.output}
    />
  )
}

function TerminalOutput({ call }: { call: StudioToolCall }) {
  const output = textOutput(call.output) || call.errorText || ""
  return (
    <Terminal className="rounded-md" output={output}>
      <TerminalContent />
    </Terminal>
  )
}

function TestResultOutput({ call }: { call: StudioToolCall }) {
  const summary = testSummary(call.output)
  if (!summary) {
    return <ToolOutput errorText={call.errorText} output={call.output} />
  }

  return (
    <TestResults summary={summary}>
      <TestResultsContent>
        <TestResultsSummary />
        <TestResultsProgress />
      </TestResultsContent>
    </TestResults>
  )
}

function FileTreeOutput({ call }: { call: StudioToolCall }) {
  const files = filePaths(call.output)
  if (files.length === 0) {
    return <ToolOutput errorText={call.errorText} output={call.output} />
  }

  return (
    <FileTree>
      {files.map((path) => (
        <FileTreeFile key={path} name={filename(path)} path={path} />
      ))}
    </FileTree>
  )
}

function WebPreviewOutput({ call }: { call: StudioToolCall }) {
  const url = webPreviewUrl(call.output)
  if (!url) {
    return <ToolOutput errorText={call.errorText} output={call.output} />
  }

  return (
    <WebPreview className="h-28" defaultUrl={url}>
      <WebPreviewNavigation>
        <WebPreviewUrl readOnly />
      </WebPreviewNavigation>
    </WebPreview>
  )
}

function ArtifactOutput({ call }: { call: StudioToolCall }) {
  return (
    <Artifact>
      <ArtifactHeader>
        <div className="min-w-0">
          <ArtifactTitle>{call.name}</ArtifactTitle>
          <ArtifactDescription>{call.state}</ArtifactDescription>
        </div>
      </ArtifactHeader>
      <ArtifactContent>
        <pre className="overflow-auto whitespace-pre-wrap text-xs">
          {formatJson(call.output ?? call.input)}
        </pre>
      </ArtifactContent>
    </Artifact>
  )
}

function toolTitle(call: StudioToolCall) {
  if (call.kind === "generic") {
    return call.name
  }
  return `${call.kind}: ${call.name}`
}

function textOutput(value: unknown) {
  if (typeof value === "string") {
    return value
  }
  if (isRecord(value)) {
    const output = value.output
    if (typeof output === "string") {
      return output
    }
    const text = value.text
    if (typeof text === "string") {
      return text
    }
  }
  return undefined
}

function testSummary(value: unknown) {
  if (!isRecord(value)) {
    return undefined
  }
  const passed = numberField(value, "passed")
  const failed = numberField(value, "failed")
  const skipped = numberField(value, "skipped") ?? 0
  const total = numberField(value, "total") ?? sumNumbers([passed, failed, skipped])
  if (passed === undefined || failed === undefined || total === undefined) {
    return undefined
  }

  return {
    passed,
    failed,
    skipped,
    total,
    duration: numberField(value, "duration") ?? numberField(value, "duration_ms"),
  }
}

function filePaths(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string")
  }
  if (!isRecord(value)) {
    return []
  }
  const files = value.files
  if (!Array.isArray(files)) {
    return []
  }
  return files
    .map((item) => (typeof item === "string" ? item : isRecord(item) ? item.path : undefined))
    .filter((item): item is string => typeof item === "string")
}

function webPreviewUrl(value: unknown) {
  if (typeof value === "string" && value.startsWith("http")) {
    return value
  }
  if (!isRecord(value)) {
    return undefined
  }
  const url = value.url
  return typeof url === "string" ? url : undefined
}

function filename(path: string) {
  return path.split("/").filter(Boolean).at(-1) ?? path
}

function numberField(record: Record<string, unknown>, key: string) {
  const value = record[key]
  return typeof value === "number" ? value : undefined
}

function sumNumbers(values: Array<number | undefined>) {
  if (values.every((value) => value !== undefined)) {
    return values.reduce((total, value) => total + (value ?? 0), 0)
  }
  return undefined
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function formatJson(value: unknown) {
  return JSON.stringify(value, null, 2)
}
