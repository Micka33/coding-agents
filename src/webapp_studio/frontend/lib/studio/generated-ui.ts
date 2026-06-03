import type { ActionBinding, ActionConfirm, Spec } from "@json-render/core"
import { validateSpec } from "@json-render/core"

import type { GeneratedUiSpec } from "@/lib/studio/schemas"

const CATALOG_COMPONENTS = {
  badge: "Badge",
  metric: "Metric",
  plan: "Plan",
  stack: "Stack",
  text: "Text",
  "task-list": "TaskList",
  "file-list": "FileList",
  "tool-result": "ToolResult",
  "code-artifact": "CodeArtifact",
  "test-summary": "TestSummary",
  "terminal-output": "TerminalOutput",
  "web-preview": "WebPreview",
  action: "GeneratedAction",
} as const

const CATALOG_EVENTS = {
  action: new Set(["press"]),
} as const

export type GeneratedUiValidation = {
  spec: Spec | null
  errors: string[]
}

export function toJsonRenderSpec(source: GeneratedUiSpec): GeneratedUiValidation {
  const errors = [...source.errors]
  const elements: Spec["elements"] = {}
  const appendError = (error: string) => {
    if (!errors.includes(error)) {
      errors.push(error)
    }
  }

  for (const [key, element] of Object.entries(source.elements)) {
    const type = CATALOG_COMPONENTS[element.component as keyof typeof CATALOG_COMPONENTS]
    if (!type) {
      appendError(`Component ${element.component} is outside the generated UI catalog.`)
      continue
    }
    elements[key] = {
      type,
      props: element.props ?? {},
      children: element.children,
    }
    const on = validatedEventBindings(source, key, element.component, element.on, appendError)
    if (on) {
      elements[key].on = on
    }
  }

  const spec = {
    root: source.root,
    elements,
    state: source.state,
  }
  const structural = validateSpec(spec)
  if (!structural.valid) {
    structural.issues.forEach((issue) => appendError(issue.message))
  }

  return {
    spec: errors.length > 0 ? null : spec,
    errors,
  }
}

function validatedEventBindings(
  source: GeneratedUiSpec,
  elementKey: string,
  component: string,
  on: GeneratedUiSpec["elements"][string]["on"],
  appendError: (error: string) => void
): Spec["elements"][string]["on"] | undefined {
  if (!on) {
    return undefined
  }

  const allowedEvents = CATALOG_EVENTS[component as keyof typeof CATALOG_EVENTS]
  const events: NonNullable<Spec["elements"][string]["on"]> = {}
  for (const [eventName, bindingOrBindings] of Object.entries(on)) {
    if (!allowedEvents?.has(eventName)) {
      appendError(
        `Event ${eventName} is not registered for generated UI component ${component}.`
      )
      continue
    }
    const bindings = Array.isArray(bindingOrBindings)
      ? bindingOrBindings
      : [bindingOrBindings]
    const safeBindings = bindings
      .map((binding) =>
        validatedActionBinding(source, elementKey, eventName, binding, appendError)
      )
      .filter((binding): binding is ActionBinding => binding !== null)
    if (safeBindings.length === 1) {
      events[eventName] = safeBindings[0]
    } else if (safeBindings.length > 1) {
      events[eventName] = safeBindings
    }
  }
  return Object.keys(events).length > 0 ? events : undefined
}

function validatedActionBinding(
  source: GeneratedUiSpec,
  elementKey: string,
  eventName: string,
  binding: ActionBinding,
  appendError: (error: string) => void
): ActionBinding | null {
  const action = source.actions[binding.action]
  if (!action) {
    appendError(
      `Action ${binding.action} on ${elementKey}.${eventName} is not registered.`
    )
    return null
  }

  const requiredParams = requiredInputFields(action.input_schema)
  if (requiredParams.length > 0) {
    const params = binding.params ?? {}
    const missing = requiredParams.filter((field) => !(field in params))
    if (missing.length > 0) {
      appendError(
        `Action ${binding.action} is missing required params: ${missing.join(", ")}.`
      )
      return null
    }
  }

  return {
    ...binding,
    confirm:
      binding.confirm ??
      (action.confirmation_required
        ? confirmationForAction(binding.action, action.confirmation)
        : undefined),
  }
}

function confirmationForAction(
  actionId: string,
  confirmation: GeneratedUiSpec["actions"][string]["confirmation"]
): ActionConfirm {
  return {
    title: textField(confirmation, "title") ?? "Confirm generated action",
    message:
      textField(confirmation, "message") ??
      `Run generated action ${actionId}?`,
    confirmLabel: textField(confirmation, "confirmLabel"),
    cancelLabel: textField(confirmation, "cancelLabel"),
    variant:
      textField(confirmation, "variant") === "danger" ? "danger" : "default",
  }
}

function requiredInputFields(inputSchema: Record<string, unknown>) {
  const required = inputSchema.required
  if (!Array.isArray(required)) {
    return []
  }
  return required.filter((field): field is string => typeof field === "string")
}

function textField(
  value: GeneratedUiSpec["actions"][string]["confirmation"],
  key: string
) {
  if (!value || typeof value !== "object") {
    return undefined
  }
  const field = value[key]
  return typeof field === "string" ? field : undefined
}
