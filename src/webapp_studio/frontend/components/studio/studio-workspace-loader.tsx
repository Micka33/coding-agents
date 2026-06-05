"use client"

import { useEffect, useState } from "react"
import { CircleAlertIcon, RefreshCwIcon } from "lucide-react"

import { StudioWorkspace, emptyStudioState } from "@/components/studio/studio-workspace"
import { Button } from "@/components/ui/button"
import { StudioApiClient } from "@/lib/studio/api-client"
import type { StudioState, StudioTeams } from "@/lib/studio/schemas"

type LoaderState =
  | { status: "loading" }
  | { status: "loaded"; state: StudioState; teams: StudioTeams }
  | { status: "blocked"; teams: StudioTeams }
  | { status: "failed"; message: string }

export function StudioWorkspaceLoader() {
  const [attempt, setAttempt] = useState(0)
  const [loaderState, setLoaderState] = useState<LoaderState>({ status: "loading" })

  useEffect(() => {
    let cancelled = false
    const apiClient = new StudioApiClient()
    Promise.all([apiClient.teams(), apiClient.session()])
      .then(async ([teams, session]) => {
        if (teams.status === "blocked") {
          return { status: "blocked" as const, teams }
        }
        if (!session.conversation_id) {
          const team = teams.teams[0]
          if (!team) {
            throw new Error("No Studio conversation teams were discovered.")
          }
          return { status: "loaded" as const, state: emptyStudioState(team), teams }
        }
        return { status: "loaded" as const, state: await apiClient.state(), teams }
      })
      .then((nextState) => {
        if (!cancelled) {
          setLoaderState(nextState)
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
        teams={loaderState.teams}
      />
    )
  }

  if (loaderState.status === "blocked") {
    return (
      <main className="grid h-svh min-h-svh place-items-center bg-background p-6">
        <section className="grid w-full max-w-2xl gap-4 rounded-md border bg-background p-4">
          <div className="flex items-center gap-2">
            <CircleAlertIcon className="size-4 text-amber-600" />
            <h1 className="text-base font-medium">Team discovery blocked</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            Multiple Studio-discoverable team.yaml files declare the same id. Ids are compared case-insensitively. Rename one of the ids, then restart Webapp Studio.
          </p>
          <div className="grid gap-3">
            {loaderState.teams.duplicate_ids.map((duplicate) => (
              <section className="grid gap-2 rounded-md border p-3 text-sm" key={duplicate.normalized_id}>
                <h2 className="font-medium">{duplicate.team_id}</h2>
                <ul className="grid gap-1 text-xs text-muted-foreground">
                  {duplicate.team_files.map((teamFile) => (
                    <li className="break-all" key={teamFile}>{teamFile}</li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </section>
      </main>
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
