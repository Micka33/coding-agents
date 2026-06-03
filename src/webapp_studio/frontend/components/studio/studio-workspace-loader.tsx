"use client"

import { useEffect, useState } from "react"
import { CircleAlertIcon, RefreshCwIcon } from "lucide-react"

import { StudioWorkspace } from "@/components/studio/studio-workspace"
import { Button } from "@/components/ui/button"
import { StudioApiClient } from "@/lib/studio/api-client"
import type { StudioState } from "@/lib/studio/schemas"

type LoaderState =
  | { status: "loading" }
  | { status: "loaded"; state: StudioState }
  | { status: "failed"; message: string }

export function StudioWorkspaceLoader() {
  const [attempt, setAttempt] = useState(0)
  const [loaderState, setLoaderState] = useState<LoaderState>({ status: "loading" })

  useEffect(() => {
    let cancelled = false
    new StudioApiClient()
      .state()
      .then((state) => {
        if (!cancelled) {
          setLoaderState({ status: "loaded", state })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setLoaderState({
            status: "failed",
            message: error instanceof Error ? error.message : "Unable to hydrate the conversation.",
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [attempt])

  if (loaderState.status === "loaded") {
    return (
      <StudioWorkspace
        generatedUi={loaderState.state.generated_ui}
        initialState={loaderState.state}
        liveApi
      />
    )
  }

  if (loaderState.status === "failed") {
    return (
      <main className="grid h-svh min-h-svh place-items-center bg-background p-6">
        <section className="grid w-full max-w-md gap-3 rounded-md border bg-background p-4">
          <div className="flex items-center gap-2">
            <CircleAlertIcon className="size-4 text-amber-600" />
            <h1 className="text-base font-medium">Studio backend disconnected</h1>
          </div>
          <p className="text-sm text-muted-foreground">{loaderState.message}</p>
          <Button
            className="justify-self-start"
            onClick={() => {
              setLoaderState({ status: "loading" })
              setAttempt((value) => value + 1)
            }}
            type="button"
            variant="outline"
          >
            <RefreshCwIcon className="size-4" />
            Retry
          </Button>
        </section>
      </main>
    )
  }

  return (
    <main className="grid h-svh min-h-svh place-items-center bg-background p-6">
      <section className="w-full max-w-md rounded-md border bg-background p-4">
        <div className="grid gap-3">
          <div className="h-4 w-40 rounded-md bg-muted" />
          <div className="h-3 w-full rounded-md bg-muted/70" />
          <div className="h-3 w-5/6 rounded-md bg-muted/70" />
          <p className="text-sm text-muted-foreground">Loading conversation...</p>
        </div>
      </section>
    </main>
  )
}
