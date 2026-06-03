"use client"

import { useEffect, useState, type Dispatch } from "react"

import { type StudioAction } from "@/lib/studio/reducer"
import {
  CheckpointSummarySchema,
  ConversationDeliverySchema,
  ConversationEventSchema,
  GeneratedUiPatchPayloadSchema,
  GeneratedUiSpecSchema,
  PrivateMessageAppendedPayloadSchema,
  QueueUpdatedPayloadSchema,
  RunSummarySchema,
  StreamFramePayloadSchema,
  StudioStateSchema,
} from "@/lib/studio/schemas"

export type StudioStreamStatus =
  | "disabled"
  | "connecting"
  | "connected"
  | "error"

export function useStudioStream(
  enabled: boolean,
  dispatch: Dispatch<StudioAction>,
  onError: (message: string) => void
): StudioStreamStatus {
  const [status, setStatus] = useState<StudioStreamStatus>(
    "connecting"
  )

  useEffect(() => {
    if (!enabled) {
      return
    }
    if (typeof EventSource === "undefined") {
      queueMicrotask(() => {
        setStatus("error")
        onError("This browser does not support live studio streams.")
      })
      return
    }

    const source = new EventSource("/api/studio/v1/stream")
    source.onopen = () => {
      setStatus("connected")
    }
    source.onerror = () => {
      setStatus("error")
    }

    source.addEventListener("snapshot.replace", (event) => {
      applyStreamEvent(event, (payload) => {
        dispatch({
          type: "state.replaced",
          state: StudioStateSchema.parse(payload),
        })
      }, onError)
    })
    source.addEventListener("conversation.event.appended", (event) => {
      applyStreamEvent(event, (payload) => {
        dispatch({
          type: "conversation.event.appended",
          event: ConversationEventSchema.parse(payload),
        })
      }, onError)
    })
    source.addEventListener("conversation.delivery.updated", (event) => {
      applyStreamEvent(event, (payload) => {
        dispatch({
          type: "conversation.delivery.updated",
          delivery: ConversationDeliverySchema.parse(payload),
        })
      }, onError)
    })
    source.addEventListener("queue.updated", (event) => {
      applyStreamEvent(event, (payload) => {
        dispatch({
          type: "queue.updated",
          queue: QueueUpdatedPayloadSchema.parse(payload).items,
        })
      }, onError)
    })
    source.addEventListener("activity.private_message.appended", (event) => {
      applyStreamEvent(event, (payload) => {
        dispatch({
          type: "activity.private_message.appended",
          payload: PrivateMessageAppendedPayloadSchema.parse(payload),
        })
      }, onError)
    })
    source.addEventListener("checkpoint.observed", (event) => {
      applyStreamEvent(event, (payload) => {
        dispatch({
          type: "checkpoint.observed",
          checkpoint: CheckpointSummarySchema.parse(payload),
        })
      }, onError)
    })
    for (const eventName of ["run.started", "run.updated", "run.completed"]) {
      source.addEventListener(eventName, (event) => {
        applyStreamEvent(event, (payload) => {
          dispatch({
            type: "run.upserted",
            run: RunSummarySchema.parse(payload),
          })
        }, onError)
      })
    }
    source.addEventListener("generated_ui.patch", (event) => {
      applyStreamEvent(event, (payload) => {
        dispatch({
          type: "generated_ui.patch",
          payload: GeneratedUiPatchPayloadSchema.parse(payload),
        })
      }, onError)
    })
    source.addEventListener("generated_ui.validated", (event) => {
      applyStreamEvent(event, (payload) => {
        dispatch({
          type: "generated_ui.validated",
          spec: GeneratedUiSpecSchema.parse(payload),
        })
      }, onError)
    })

    return () => {
      source.close()
    }
  }, [dispatch, enabled, onError])

  return enabled ? status : "disabled"
}

function applyStreamEvent(
  event: MessageEvent<string>,
  applyPayload: (payload: unknown) => void,
  onError: (message: string) => void
) {
  try {
    applyPayload(StreamFramePayloadSchema.parse(JSON.parse(event.data)).payload)
  } catch (error) {
    onError(
      error instanceof Error ? error.message : "Studio stream event failed."
    )
  }
}
