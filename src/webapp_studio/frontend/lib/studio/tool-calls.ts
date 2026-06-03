import { z } from "zod"

const ToolStateSchema = z.enum([
  "approval-requested",
  "approval-responded",
  "input-available",
  "input-streaming",
  "output-available",
  "output-denied",
  "output-error",
])

const ToolRecordSchema = z.record(z.string(), z.unknown())

export type StudioToolKind =
  | "artifact"
  | "file-tree"
  | "generic"
  | "terminal"
  | "test-results"
  | "web-preview"

export type StudioToolState = z.infer<typeof ToolStateSchema>

export type StudioToolCall = {
  id: string
  name: string
  kind: StudioToolKind
  state: StudioToolState
  input: unknown
  output: unknown
  errorText: string | undefined
}

export function studioToolCallsFromValue(value: unknown): StudioToolCall[] {
  const records = z.array(ToolRecordSchema).safeParse(value)
  if (!records.success) {
    return []
  }

  return records.data.map((record, index) => toStudioToolCall(record, index))
}

function toStudioToolCall(record: Record<string, unknown>, index: number): StudioToolCall {
  const name = toolName(record, index)
  const output = firstPresent(record, ["output", "result"])
  const errorText = textValue(firstPresent(record, ["errorText", "error"]))

  return {
    id: textValue(firstPresent(record, ["toolCallId", "id", "call_id"])) ?? `tool-${index}`,
    name,
    kind: toolKind(name),
    state: toolState(record, output, errorText),
    input: firstPresent(record, ["input", "args", "arguments"]) ?? {},
    output,
    errorText,
  }
}

function toolName(record: Record<string, unknown>, index: number): string {
  const named = textValue(firstPresent(record, ["toolName", "name", "tool_name"]))
  if (named) {
    return named
  }

  const type = textValue(record.type)
  if (type?.startsWith("tool-")) {
    return type.replace(/^tool-/, "")
  }

  return `tool-${index + 1}`
}

function toolState(
  record: Record<string, unknown>,
  output: unknown,
  errorText: string | undefined
): StudioToolState {
  const parsed = ToolStateSchema.safeParse(record.state)
  if (parsed.success) {
    return parsed.data
  }
  if (errorText) {
    return "output-error"
  }
  if (output !== undefined) {
    return "output-available"
  }
  return "input-available"
}

function toolKind(name: string): StudioToolKind {
  const normalized = name.toLowerCase().replace(/[_\s]/g, "-")
  if (normalized.includes("terminal") || normalized.includes("shell") || normalized.includes("command")) {
    return "terminal"
  }
  if (normalized.includes("test")) {
    return "test-results"
  }
  if (normalized.includes("file")) {
    return "file-tree"
  }
  if (normalized.includes("web") || normalized.includes("preview") || normalized.includes("browser")) {
    return "web-preview"
  }
  if (normalized.includes("artifact")) {
    return "artifact"
  }
  return "generic"
}

function firstPresent(record: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    if (record[key] !== undefined) {
      return record[key]
    }
  }
  return undefined
}

function textValue(value: unknown): string | undefined {
  if (typeof value === "string" && value.trim()) {
    return value
  }
  return undefined
}
