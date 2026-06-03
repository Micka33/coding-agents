import { readFileSync } from "node:fs"
import { join } from "node:path"

import {
  GeneratedUiSpecSchema,
  StudioStateSchema,
  type GeneratedUiSpec,
  type StudioState,
} from "@/lib/studio/schemas"

export type StudioMock = {
  state: StudioState
  generatedUi: GeneratedUiSpec[]
  liveApi: boolean
}

export function loadStudioMock(): StudioMock {
  const state = StudioStateSchema.parse(readFixture("studio_state.json"))
  const generatedUi = GeneratedUiSpecSchema.parse(
    readFixture("generated_ui_spec.json")
  )
  const invalidGeneratedUi = GeneratedUiSpecSchema.parse({
    id: "generated_ui_invalid",
    version: "studio.generated-ui.v1",
    root: "unsafe_01",
    elements: {
      unsafe_01: {
        component: "unknown-panel",
        props: {
          label: "Unknown component",
        },
      },
    },
    state: {},
    status: "invalid",
    errors: ["Component unknown-panel is outside the generated UI catalog."],
    created_at: generatedUi.created_at,
    updated_at: generatedUi.updated_at,
  })

  return {
    state: {
      ...state,
      generated_ui: [generatedUi],
    },
    generatedUi: [generatedUi, invalidGeneratedUi],
    liveApi: false,
  }
}

export function readFixture(filename: string): unknown {
  return JSON.parse(readFileSync(join(fixtureDirectory(), filename), "utf8"))
}

function fixtureDirectory() {
  const cwd = process.cwd()
  if (cwd.endsWith("src/webapp_studio/frontend")) {
    return join(cwd, "../contracts/fixtures")
  }
  return join(cwd, "src/webapp_studio/contracts/fixtures")
}
