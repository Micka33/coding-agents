"use client"

import { CircleAlertIcon, RefreshCwIcon } from "lucide-react"

import { Button } from "@/components/ui/button"

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <main className="grid h-svh min-h-svh place-items-center bg-background p-6">
      <section className="grid w-full max-w-md gap-3 rounded-md border bg-background p-4">
        <div className="flex items-center gap-2">
          <CircleAlertIcon className="size-4 text-amber-600" />
          <h1 className="text-base font-medium">Studio backend disconnected</h1>
        </div>
        <p className="text-sm text-muted-foreground">
          {error.message || "Unable to hydrate the conversation from the backend."}
        </p>
        <Button className="justify-self-start" onClick={reset} type="button" variant="outline">
          <RefreshCwIcon className="size-4" />
          Retry
        </Button>
      </section>
    </main>
  )
}
