import { applySpecStreamPatch } from "@json-render/core"
import type { JsonPatch } from "@json-render/core"

import { toJsonRenderSpec } from "@/lib/studio/generated-ui"
import {
  GeneratedUiSpecSchema,
  type GeneratedUiPatchPayload,
  type GeneratedUiSpec,
} from "@/lib/studio/schemas"

type GeneratedUiPatchResult = {
  errors: string[]
  specs: GeneratedUiSpec[]
}

const ALLOWED_PATCH_ROOTS = new Set([
  "actions",
  "created_at",
  "elements",
  "errors",
  "id",
  "root",
  "state",
  "status",
  "updated_at",
  "version",
])

const UNSAFE_POINTER_TOKENS = new Set(["__proto__", "constructor", "prototype"])

export function applyGeneratedUiPatch(
  specs: GeneratedUiSpec[],
  payload: GeneratedUiPatchPayload
): GeneratedUiPatchResult {
  const patchErrors = validatePatchOperation(payload.patch)
  if (patchErrors.length > 0) {
    return { errors: patchErrors, specs }
  }

  const existingIndex = specs.findIndex((spec) => spec.id === payload.spec_id)
  const previous = existingIndex >= 0 ? specs[existingIndex] : emptySpec(payload)
  const candidate = cloneJson(previous)

  try {
    applySpecStreamPatch(
      candidate as Record<string, unknown>,
      payload.patch as JsonPatch
    )
  } catch (error) {
    return {
      errors: [error instanceof Error ? error.message : "Generated UI patch failed."],
      specs,
    }
  }

  const parsed = GeneratedUiSpecSchema.safeParse(candidate)
  if (!parsed.success) {
    return {
      errors: parsed.error.issues.map((issue) => issue.message),
      specs,
    }
  }
  if (parsed.data.id !== payload.spec_id) {
    return {
      errors: [`Generated UI patch changed spec id ${payload.spec_id}.`],
      specs,
    }
  }

  const validated = toJsonRenderSpec(parsed.data)
  const nextSpec: GeneratedUiSpec = {
    ...parsed.data,
    errors: validated.errors,
    status: validated.errors.length > 0 ? "invalid" : "valid",
    updated_at: payload.updated_at ?? parsed.data.updated_at,
  }
  const nextSpecs =
    existingIndex >= 0
      ? specs.map((spec, index) => (index === existingIndex ? nextSpec : spec))
      : [...specs, nextSpec]
  return { errors: [], specs: nextSpecs }
}

export function validatePatchOperation(patch: GeneratedUiPatchPayload["patch"]) {
  const errors = [
    ...validateJsonPointer(patch.path, "path"),
    ...validatePatchValue(patch),
  ]
  if (patch.from !== undefined) {
    errors.push(...validateJsonPointer(patch.from, "from"))
  }
  return errors
}

function validatePatchValue(patch: GeneratedUiPatchPayload["patch"]) {
  if (["add", "replace", "test"].includes(patch.op) && !("value" in patch)) {
    return [`Generated UI ${patch.op} patch requires a value.`]
  }
  if (["move", "copy"].includes(patch.op) && !patch.from) {
    return [`Generated UI ${patch.op} patch requires a from pointer.`]
  }
  return []
}

function validateJsonPointer(path: string, field: string) {
  if (!path.startsWith("/")) {
    return [`Generated UI patch ${field} must be an absolute JSON Pointer.`]
  }
  const tokens = path.slice(1).split("/").map(unescapePointerToken)
  const [root] = tokens
  if (!root || !ALLOWED_PATCH_ROOTS.has(root)) {
    return [`Generated UI patch ${field} root ${root || "<empty>"} is not allowed.`]
  }
  if (tokens.some((token) => UNSAFE_POINTER_TOKENS.has(token))) {
    return [`Generated UI patch ${field} contains an unsafe pointer token.`]
  }
  return []
}

function emptySpec(payload: GeneratedUiPatchPayload): GeneratedUiSpec {
  return {
    id: payload.spec_id,
    version: "studio.generated-ui.v1",
    root: "",
    elements: {},
    state: {},
    actions: {},
    status: "pending",
    errors: [],
    created_at: payload.created_at ?? new Date().toISOString(),
    updated_at: payload.updated_at ?? null,
  }
}

function unescapePointerToken(token: string) {
  return token.replace(/~1/g, "/").replace(/~0/g, "~")
}

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}
