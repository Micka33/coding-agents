import { applyGeneratedUiPatch } from "@/lib/studio/generated-ui-patches"
import type {
  CheckpointSummary,
  ConversationDelivery,
  ConversationEvent,
  GeneratedUiPatchPayload,
  GeneratedUiSpec,
  PrivateMessageAppendedPayload,
  QueueItem,
  RunSummary,
  RuntimeSettings,
  StudioState,
} from "@/lib/studio/schemas"

export type StudioAction =
  | {
      type: "state.replaced"
      state: StudioState
    }
  | {
      type: "runtime.updated"
      runtime: Partial<RuntimeSettings>
    }
  | {
      type: "conversation.event.appended"
      event: ConversationEvent
    }
  | {
      type: "conversation.delivery.updated"
      delivery: ConversationDelivery
    }
  | {
      type: "queue.updated"
      queue: QueueItem[]
    }
  | {
      type: "activity.private_message.appended"
      payload: PrivateMessageAppendedPayload
    }
  | {
      type: "checkpoint.observed"
      checkpoint: CheckpointSummary
    }
  | {
      type: "generated_ui.patch"
      payload: GeneratedUiPatchPayload
    }
  | {
      type: "generated_ui.validated"
      spec: GeneratedUiSpec
    }
  | {
      type: "run.upserted"
      run: RunSummary
    }
  | {
      type: "message.optimistic_append"
      clientMessageId?: string
      content: string
      authorId: string
    }
  | {
      type: "message.optimistic_failed"
      clientMessageId: string
    }

export function studioReducer(state: StudioState, action: StudioAction): StudioState {
  if (action.type === "state.replaced") {
    return action.state
  }

  if (action.type === "runtime.updated") {
    return {
      ...state,
      runtime: {
        ...state.runtime,
        ...action.runtime,
      },
    }
  }

  if (action.type === "conversation.event.appended") {
    const existingIndex = state.conversation.events.findIndex(
      (event) => event.id === action.event.id
    )
    const clientMessageId =
      typeof action.event.metadata.client_message_id === "string"
        ? action.event.metadata.client_message_id
        : null
    const optimisticIndex = state.conversation.events.findIndex(
      (event) =>
        event.metadata.optimistic === true &&
        (clientMessageId !== null
          ? event.metadata.client_message_id === clientMessageId
          : event.author_id === action.event.author_id &&
            event.content === action.event.content)
    )
    const replacementIndex =
      existingIndex >= 0 ? existingIndex : optimisticIndex >= 0 ? optimisticIndex : -1
    const events =
      replacementIndex >= 0
        ? state.conversation.events.map((event, index) =>
            index === replacementIndex ? action.event : event
          )
        : [...state.conversation.events, action.event]

    return {
      ...state,
      conversation: {
        ...state.conversation,
        events,
      },
    }
  }

  if (action.type === "conversation.delivery.updated") {
    return {
      ...state,
      conversation: {
        ...state.conversation,
        deliveries: upsertDelivery(state.conversation.deliveries, action.delivery),
      },
    }
  }

  if (action.type === "queue.updated") {
    return {
      ...state,
      queue: action.queue,
    }
  }

  if (action.type === "activity.private_message.appended") {
    return {
      ...state,
      activity: {
        ...state.activity,
        private_threads: appendPrivateMessage(
          state.activity.private_threads,
          action.payload
        ),
      },
    }
  }

  if (action.type === "checkpoint.observed") {
    return {
      ...state,
      history: {
        ...state.history,
        checkpoints: upsertCheckpoint(
          state.history.checkpoints,
          action.checkpoint
        ),
      },
    }
  }

  if (action.type === "generated_ui.patch") {
    return {
      ...state,
      generated_ui: applyGeneratedUiPatch(state.generated_ui, action.payload).specs,
    }
  }

  if (action.type === "generated_ui.validated") {
    return {
      ...state,
      generated_ui: upsertGeneratedUiSpec(state.generated_ui, action.spec),
    }
  }

  if (action.type === "run.upserted") {
    return {
      ...state,
      runs: upsertRunSummary(state.runs, action.run),
    }
  }

  if (action.type === "message.optimistic_failed") {
    return {
      ...state,
      conversation: {
        ...state.conversation,
        events: state.conversation.events.map((event) =>
          event.metadata.optimistic === true &&
          event.metadata.client_message_id === action.clientMessageId
            ? {
                ...event,
                metadata: {
                  ...event.metadata,
                  optimistic_status: "failed",
                },
              }
            : event
        ),
      },
    }
  }

  const nextSeq =
    Math.max(0, ...state.conversation.events.map((event) => event.seq)) + 1
  const event: ConversationEvent = {
    id: `optimistic_${nextSeq}`,
    team_id: state.team_id,
    conversation_id: state.conversation_id,
    seq: nextSeq,
    created_at: new Date().toISOString(),
    author_id: action.authorId,
    author_kind: "human",
    content: action.content,
    mentions: mentionsFromContent(state, action.content),
    attachments: [],
    source_thread_id: null,
    source_message_id: null,
    metadata: action.clientMessageId
      ? {
          client_message_id: action.clientMessageId,
          optimistic: true,
          optimistic_status: "sending",
        }
      : {
          optimistic: true,
          optimistic_status: "sending",
        },
  }

  return {
    ...state,
    conversation: {
      ...state.conversation,
      events: [...state.conversation.events, event],
    },
  }
}

function upsertGeneratedUiSpec(
  specs: GeneratedUiSpec[],
  nextSpec: GeneratedUiSpec
) {
  const existingIndex = specs.findIndex((spec) => spec.id === nextSpec.id)
  if (existingIndex < 0) {
    return [...specs, nextSpec]
  }
  return specs.map((spec, index) => (index === existingIndex ? nextSpec : spec))
}

function upsertRunSummary(runs: RunSummary[], nextRun: RunSummary) {
  const existingIndex = runs.findIndex((run) => run.id === nextRun.id)
  if (existingIndex < 0) {
    return [nextRun, ...runs]
  }
  return runs.map((run, index) => (index === existingIndex ? nextRun : run))
}

function appendPrivateMessage(
  privateThreads: StudioState["activity"]["private_threads"],
  payload: PrivateMessageAppendedPayload
) {
  const existingIndex = privateThreads.findIndex(
    (thread) => thread.thread_id === payload.thread_id
  )
  if (existingIndex < 0) {
    return [
      ...privateThreads,
      {
        agent_id: payload.agent_id,
        thread_id: payload.thread_id,
        messages: [payload.message],
      },
    ]
  }
  return privateThreads.map((thread, index) =>
    index === existingIndex
      ? {
          ...thread,
          messages: [...thread.messages, payload.message],
        }
      : thread
  )
}

function mentionsFromContent(state: StudioState, content: string) {
  const lookup = new Map<string, string>()
  for (const participant of state.participants) {
    lookup.set(participant.toLowerCase(), participant)
    for (const alias of state.participant_aliases[participant] ?? []) {
      lookup.set(alias.toLowerCase(), participant)
    }
  }
  const mentions: string[] = []
  const seen = new Set<string>()
  for (const match of content.matchAll(/(^|[^\w.])@([A-Za-z][A-Za-z0-9_-]{1,63})(?![\w.-])/g)) {
    const participant = lookup.get(match[2].toLowerCase())
    if (!participant || seen.has(participant)) {
      continue
    }
    mentions.push(participant)
    seen.add(participant)
  }
  return mentions
}

function upsertCheckpoint(
  checkpoints: CheckpointSummary[],
  nextCheckpoint: CheckpointSummary
) {
  const existingIndex = checkpoints.findIndex(
    (checkpoint) => checkpoint.id === nextCheckpoint.id
  )
  if (existingIndex < 0) {
    return [...checkpoints, nextCheckpoint]
  }
  return checkpoints.map((checkpoint, index) =>
    index === existingIndex ? nextCheckpoint : checkpoint
  )
}

function upsertDelivery(
  deliveries: ConversationDelivery[],
  nextDelivery: ConversationDelivery
) {
  const existingIndex = deliveries.findIndex((delivery) => delivery.id === nextDelivery.id)
  if (existingIndex < 0) {
    return [...deliveries, nextDelivery]
  }
  return deliveries.map((delivery, index) =>
    index === existingIndex ? nextDelivery : delivery
  )
}
