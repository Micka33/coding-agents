import { z } from "zod"

const JsonValueSchema: z.ZodType<unknown> = z.lazy(() =>
  z.union([
    z.string(),
    z.number(),
    z.boolean(),
    z.null(),
    z.array(JsonValueSchema),
    z.record(z.string(), JsonValueSchema),
  ])
)

const JsonObjectSchema = z.record(z.string(), JsonValueSchema)

const CapabilityStatusSchema = z.enum([
  "available",
  "degraded",
  "unsupported",
  "planned",
])

export const StudioCapabilitiesSchema = z
  .object({
    streaming: CapabilityStatusSchema,
    queue_control: CapabilityStatusSchema,
    interrupts: CapabilityStatusSchema,
    checkpoints: CapabilityStatusSchema,
    branching: CapabilityStatusSchema,
    time_travel: CapabilityStatusSchema,
    generated_ui: CapabilityStatusSchema,
  })
  .passthrough()

export const StudioErrorSchema = z
  .object({
    code: z.string(),
    message: z.string(),
    field: z.string().nullable(),
    retryable: z.boolean(),
    details: JsonObjectSchema,
  })
  .passthrough()

export const RuntimeSettingsSchema = z
  .object({
    team_id: z.string(),
    conversation_id: z.string(),
    mention_hook_enabled: z.boolean(),
    max_cascade_turns: z.number().int().nullable(),
  })
  .passthrough()

export const ConversationFileRefSchema = z
  .object({
    id: z.string(),
    filename: z.string(),
    uri: z.string(),
    media_type: z.string().nullable(),
    size_bytes: z.number().int().nullable(),
    added_by: z.string().nullable(),
  })
  .passthrough()

export const ConversationEventSchema = z
  .object({
    id: z.string(),
    team_id: z.string(),
    conversation_id: z.string(),
    branch_id: z.string().default("branch_main"),
    logical_message_id: z.string().nullable().default(null),
    version_parent_event_id: z.string().nullable().default(null),
    parent_event_id: z.string().nullable().default(null),
    frontier_before_event_id: z.string().nullable().default(null),
    frontier_after_event_id: z.string().nullable().default(null),
    seq: z.number().int(),
    created_at: z.string(),
    author_id: z.string(),
    author_kind: z.enum(["human", "agent"]),
    content: z.string(),
    mentions: z.array(z.string()),
    attachments: z.array(ConversationFileRefSchema),
    source_thread_id: z.string().nullable(),
    source_message_id: z.string().nullable(),
    metadata: JsonObjectSchema,
  })
  .passthrough()

export const ConversationDeliverySchema = z
  .object({
    id: z.string(),
    team_id: z.string(),
    conversation_id: z.string(),
    branch_id: z.string().default("branch_main"),
    agent_id: z.string(),
    run_id: z.string().nullable(),
    snapshot_seq: z.number().int().nullable(),
    status: z.enum([
      "cascade-limited",
      "empty",
      "failed",
      "ignored",
      "skipped",
      "stopped",
      "success",
    ]),
    created_at: z.string(),
    completed_at: z.string().nullable(),
    error: z.string().nullable(),
  })
  .passthrough()

export const AppendMessageResultSchema = z
  .object({
    event: ConversationEventSchema,
    deliveries: z.array(ConversationDeliverySchema),
    failures: z.array(ConversationDeliverySchema),
  })
  .passthrough()

export const StudioSessionSchema = z
  .object({
    team_id: z.string(),
    conversation_id: z.string(),
    team_file: z.string().nullable(),
    launcher_cwd: z.string(),
    resolved_root_dir: z.string(),
    checkpointer: z
      .object({
        backend: z.string(),
        sqlite_path: z.string().nullable(),
        storage_id: z.string(),
      })
      .passthrough(),
    loaded_at: z.string(),
  })
  .passthrough()

export const ConversationSummarySchema = z
  .object({
    conversation_id: z.string(),
    event_count: z.number().int(),
    last_seq: z.number().int(),
    last_event_at: z.string().nullable(),
    last_author_id: z.string().nullable(),
  })
  .passthrough()

export const ConversationListSchema = z
  .object({
    team_id: z.string(),
    current_conversation_id: z.string(),
    conversations: z.array(ConversationSummarySchema),
  })
  .passthrough()

export const ConversationSwitchResultSchema = z
  .object({
    session: StudioSessionSchema,
    state: z.lazy(() => StudioStateSchema),
  })
  .passthrough()

export const StudioFileItemSchema = z
  .object({
    id: z.string(),
    filename: z.string(),
    media_type: z.string().nullable(),
    size_bytes: z.number().int().nullable(),
    added_by: z.string().nullable(),
    event_id: z.string().nullable(),
    event_seq: z.number().int().nullable(),
    preview_url: z.string().nullable(),
    download_url: z.string(),
  })
  .passthrough()

export const StudioFilesSchema = z
  .object({
    files: z.array(StudioFileItemSchema),
  })
  .passthrough()

export const StudioChangeItemSchema = z
  .object({
    id: z.string(),
    path: z.string(),
    status: z.string(),
    source: z.string().nullable().optional(),
    agent_id: z.string().nullable().optional(),
    event_id: z.string().nullable().optional(),
    diff_url: z.string().nullable().optional(),
  })
  .passthrough()

export const StudioChangesSchema = z
  .object({
    changes: z.array(StudioChangeItemSchema),
    supported: z.boolean().optional(),
  })
  .passthrough()

export const StudioChangeDiffSchema = z
  .object({
    change_id: z.string(),
    path: z.string(),
    diff: z.string(),
  })
  .passthrough()

export const StudioTerminalSessionSchema = z
  .object({
    session_id: z.string(),
    cwd: z.string(),
    status: z.enum(["running", "terminated"]),
    created_at: z.string(),
    columns: z.number().int(),
    rows: z.number().int(),
  })
  .passthrough()

export const StudioTerminalOutputChunkSchema = z
  .object({
    cursor: z.number().int(),
    stream: z.string(),
    text: z.string(),
  })
  .passthrough()

export const StudioTerminalOutputSchema = z
  .object({
    session_id: z.string(),
    cursor: z.number().int(),
    chunks: z.array(StudioTerminalOutputChunkSchema),
    status: z.enum(["running", "terminated"]),
  })
  .passthrough()

export const AgentDeliveryStateSchema = z
  .object({
    team_id: z.string(),
    conversation_id: z.string(),
    branch_id: z.string().default("branch_main"),
    agent_id: z.string(),
    last_delivered_seq: z.number().int(),
    running: z.boolean(),
    queued: z.boolean(),
    queued_after_seq: z.number().int().nullable(),
    current_run_id: z.string().nullable(),
    current_snapshot_seq: z.number().int().nullable(),
    stop_requested: z.boolean(),
    last_identity_refresh_seq: z.number().int(),
    token_estimate_since_identity_refresh: z.number().int(),
  })
  .passthrough()

export const MessageSummarySchema = z
  .object({
    type: z.string(),
    name: z.string().nullable(),
    content: z.string(),
    tool_calls: JsonValueSchema,
  })
  .passthrough()

export const PrivateThreadSchema = z
  .object({
    agent_id: z.string().nullable(),
    thread_id: z.string(),
    messages: z.array(MessageSummarySchema),
  })
  .passthrough()

export const PrivateMessageAppendedPayloadSchema = z
  .object({
    agent_id: z.string().nullable(),
    thread_id: z.string(),
    message: MessageSummarySchema,
  })
  .passthrough()

export const ActivitySnapshotSchema = z
  .object({
    active_agent_ids: z.array(z.string()),
    private_threads: z.array(PrivateThreadSchema),
  })
  .passthrough()

export const ConversationBranchThreadSchema = z
  .object({
    team_id: z.string(),
    conversation_id: z.string(),
    branch_id: z.string(),
    logical_thread_key: z.string(),
    physical_thread_id: z.string(),
    forked_from_branch_id: z.string().nullable().default(null),
    forked_from_thread_id: z.string().nullable().default(null),
    forked_from_checkpoint_id: z.string().nullable().default(null),
    created_by_commit_id: z.string().nullable().default(null),
    status: z.enum(["active", "orphaned"]).default("active"),
  })
  .passthrough()

export const ThreadFrontierSchema = z
  .object({
    frontier_id: z.string(),
    team_id: z.string(),
    conversation_id: z.string(),
    branch_id: z.string(),
    event_id: z.string(),
    event_boundary: z.enum(["before", "after"]),
    logical_thread_key: z.string(),
    physical_thread_id: z.string(),
    checkpoint_id: z.string().nullable().default(null),
    parent_logical_thread_key: z.string().nullable().default(null),
    usable_for_fork: z.boolean().default(false),
    usable_for_continue: z.boolean().default(false),
    created_at: z.string(),
  })
  .passthrough()

export const ConversationControlEventSchema = z
  .object({
    id: z.string(),
    team_id: z.string(),
    conversation_id: z.string(),
    branch_id: z.string(),
    logical_thread_key: z.string(),
    physical_thread_id: z.string(),
    parent_run_id: z.string().nullable().default(null),
    kind: z.string(),
    content: z.string(),
    created_at: z.string(),
  })
  .passthrough()

export const ExternalSideEffectSchema = z
  .object({
    id: z.string(),
    team_id: z.string(),
    conversation_id: z.string(),
    branch_id: z.string(),
    run_id: z.string().nullable().default(null),
    agent_id: z.string().nullable().default(null),
    tool_call_id: z.string().nullable().default(null),
    kind: z.string(),
    target: z.string(),
    audit_payload: z.record(z.string(), JsonValueSchema).default({}),
    not_rewindable: z.boolean().default(true),
    created_at: z.string(),
  })
  .passthrough()

export const ConversationSnapshotSchema = z
  .object({
    events: z.array(ConversationEventSchema),
    deliveries: z.array(ConversationDeliverySchema),
    agent_states: z.array(AgentDeliveryStateSchema),
    branch_threads: z.array(ConversationBranchThreadSchema).default([]),
    thread_frontiers: z.array(ThreadFrontierSchema).default([]),
    control_events: z.array(ConversationControlEventSchema).default([]),
    external_side_effects: z.array(ExternalSideEffectSchema).default([]),
  })
  .passthrough()

export const RunSummarySchema = z
  .object({
    id: z.string(),
    conversation_id: z.string(),
    agent_id: z.string().nullable(),
    status: z.enum([
      "queued",
      "running",
      "completed",
      "failed",
      "stopped",
      "superseded",
      "unknown",
    ]),
    created_at: z.string().nullable(),
    updated_at: z.string().nullable(),
    completed_at: z.string().nullable(),
    checkpoint_id: z.string().nullable(),
    cursor: z.string().nullable(),
    metadata: JsonObjectSchema,
  })
  .passthrough()

export const RunJoinResultSchema = z
  .object({
    run_id: z.string(),
    cursor: z.string().nullable(),
    replay_available: z.boolean(),
    stream_url: z.string(),
  })
  .passthrough()

export const CheckpointResumeRequestSchema = z
  .object({
    mode: z.enum(["resume", "regenerate", "edit"]).default("resume"),
    edited_content: z.string().nullable().optional(),
    metadata: JsonObjectSchema.optional(),
  })
  .passthrough()

export const QueueItemSchema = z
  .object({
    id: z.string(),
    conversation_id: z.string(),
    agent_id: z.string(),
    status: z.enum(["pending", "running", "cancelled", "failed", "completed"]),
    position: z.number().int().nullable(),
    enqueued_at: z.string().nullable(),
    updated_at: z.string().nullable(),
    message_event_id: z.string().nullable(),
    can_cancel: z.boolean(),
    error: z.string().nullable(),
  })
  .passthrough()

export const QueueUpdatedPayloadSchema = z
  .object({
    items: z.array(QueueItemSchema),
  })
  .passthrough()

export const InterruptRequestSchema = z
  .object({
    id: z.string(),
    run_id: z.string().nullable(),
    agent_id: z.string().nullable(),
    checkpoint_id: z.string().nullable(),
    created_at: z.string(),
    kind: z.enum(["approve", "edit", "respond", "review"]),
    payload: JsonObjectSchema,
    status: z.enum(["pending", "resolved"]),
    decisions: z.array(JsonObjectSchema),
  })
  .passthrough()

export const CheckpointSummarySchema = z
  .object({
    id: z.string(),
    thread_id: z.string(),
    checkpoint_ns: z.string(),
    parent_checkpoint_id: z.string().nullable(),
    seq: z.number().int(),
    created_at: z.string(),
    source: z.string(),
    metadata: JsonObjectSchema,
    summary: JsonObjectSchema,
    capabilities: z
      .object({
        inspect: CapabilityStatusSchema,
        resume: CapabilityStatusSchema,
        branch_from_here: CapabilityStatusSchema,
      })
      .passthrough(),
  })
  .passthrough()

export const BranchSummarySchema = z
  .object({
    id: z.string(),
    label: z.string(),
    parent_branch_id: z.string().nullable(),
    origin_checkpoint_id: z.string().nullable(),
    origin_event_id: z.string().nullable(),
    origin_event_seq: z.number().int().nullable(),
    created_at: z.string(),
    current: z.boolean(),
    status: z.enum(["derived", "persisted"]),
    head_checkpoint_id: z.string().nullable(),
  })
  .passthrough()

export const HistorySnapshotSchema = z
  .object({
    current_branch_id: z.string(),
    checkpoints: z.array(CheckpointSummarySchema),
    branches: z.array(BranchSummarySchema),
  })
  .passthrough()

export const GeneratedUiActionConfirmationSchema = z
  .object({
    title: z.string(),
    message: z.string(),
    confirmLabel: z.string().optional(),
    cancelLabel: z.string().optional(),
    variant: z.enum(["default", "danger"]).optional(),
  })
  .passthrough()

export const GeneratedUiActionSchema = z
  .object({
    description: z.string().optional(),
    input_schema: JsonObjectSchema.default({}),
    confirmation_required: z.boolean().default(false),
    confirmation: GeneratedUiActionConfirmationSchema.nullable().optional(),
    audit: z.enum(["record", "none"]).default("record"),
  })
  .passthrough()

export const GeneratedUiActionBindingSchema = z
  .object({
    action: z.string(),
    params: JsonObjectSchema.optional(),
    confirm: GeneratedUiActionConfirmationSchema.optional(),
    preventDefault: z.boolean().optional(),
  })
  .passthrough()

export const GeneratedUiElementSchema = z
  .object({
    component: z.string(),
    props: JsonObjectSchema.optional(),
    children: z.array(z.string()).optional(),
    on: z
      .record(
        z.string(),
        z.union([
          GeneratedUiActionBindingSchema,
          z.array(GeneratedUiActionBindingSchema),
        ])
      )
      .optional(),
  })
  .passthrough()

export const GeneratedUiSpecSchema = z
  .object({
    id: z.string(),
    version: z.string(),
    root: z.string(),
    elements: z.record(z.string(), GeneratedUiElementSchema),
    state: JsonObjectSchema,
    actions: z.record(z.string(), GeneratedUiActionSchema).default({}),
    status: z.enum(["pending", "valid", "invalid"]),
    errors: z.array(z.string()),
    created_at: z.string(),
    updated_at: z.string().nullable(),
  })
  .passthrough()

export const GeneratedUiPatchOperationSchema = z
  .object({
    op: z.enum(["add", "remove", "replace", "move", "copy", "test"]),
    path: z.string(),
    value: JsonValueSchema.optional(),
    from: z.string().optional(),
  })
  .passthrough()

export const GeneratedUiPatchPayloadSchema = z
  .object({
    spec_id: z.string(),
    patch: GeneratedUiPatchOperationSchema,
    created_at: z.string().optional(),
    updated_at: z.string().optional(),
  })
  .passthrough()

export const StudioStateSchema = z
  .object({
    team_id: z.string(),
    conversation_id: z.string(),
    participants: z.array(z.string()),
    participant_aliases: z.record(z.string(), z.array(z.string())).default({}),
    runtime: RuntimeSettingsSchema,
    conversation: ConversationSnapshotSchema,
    activity: ActivitySnapshotSchema,
    runs: z.array(RunSummarySchema),
    queue: z.array(QueueItemSchema),
    interrupts: z.array(InterruptRequestSchema),
    history: HistorySnapshotSchema,
    generated_ui: z.array(GeneratedUiSpecSchema),
  })
  .passthrough()

export const StudioEnvelopeSchema = <TData extends z.ZodType>(data: TData) =>
  z
    .object({
      schema_version: z.literal("studio.v1"),
      request_id: z.string(),
      capabilities: StudioCapabilitiesSchema,
      data,
      errors: z.array(StudioErrorSchema),
    })
    .passthrough()

export const StreamFramePayloadSchema = z
  .object({
    schema_version: z.literal("studio.v1"),
    cursor: z.string(),
    payload: JsonValueSchema,
  })
  .passthrough()

export type StudioCapabilities = z.infer<typeof StudioCapabilitiesSchema>
export type RuntimeSettings = z.infer<typeof RuntimeSettingsSchema>
export type ConversationFileRef = z.infer<typeof ConversationFileRefSchema>
export type ConversationEvent = z.infer<typeof ConversationEventSchema>
export type ConversationDelivery = z.infer<typeof ConversationDeliverySchema>
export type AppendMessageResult = z.infer<typeof AppendMessageResultSchema>
export type StudioSession = z.infer<typeof StudioSessionSchema>
export type ConversationSummary = z.infer<typeof ConversationSummarySchema>
export type ConversationList = z.infer<typeof ConversationListSchema>
export type ConversationSwitchResult = z.infer<typeof ConversationSwitchResultSchema>
export type StudioFileItem = z.infer<typeof StudioFileItemSchema>
export type StudioFiles = z.infer<typeof StudioFilesSchema>
export type StudioChangeItem = z.infer<typeof StudioChangeItemSchema>
export type StudioChanges = z.infer<typeof StudioChangesSchema>
export type StudioChangeDiff = z.infer<typeof StudioChangeDiffSchema>
export type StudioTerminalSession = z.infer<typeof StudioTerminalSessionSchema>
export type StudioTerminalOutput = z.infer<typeof StudioTerminalOutputSchema>
export type AgentDeliveryState = z.infer<typeof AgentDeliveryStateSchema>
export type PrivateThread = z.infer<typeof PrivateThreadSchema>
export type PrivateMessageAppendedPayload = z.infer<typeof PrivateMessageAppendedPayloadSchema>
export type RunSummary = z.infer<typeof RunSummarySchema>
export type RunJoinResult = z.infer<typeof RunJoinResultSchema>
export type CheckpointResumeRequest = z.infer<typeof CheckpointResumeRequestSchema>
export type QueueItem = z.infer<typeof QueueItemSchema>
export type InterruptRequest = z.infer<typeof InterruptRequestSchema>
export type BranchSummary = z.infer<typeof BranchSummarySchema>
export type CheckpointSummary = z.infer<typeof CheckpointSummarySchema>
export type GeneratedUiSpec = z.infer<typeof GeneratedUiSpecSchema>
export type GeneratedUiPatchPayload = z.infer<typeof GeneratedUiPatchPayloadSchema>
export type StudioState = z.infer<typeof StudioStateSchema>
export type StreamFramePayload = z.infer<typeof StreamFramePayloadSchema>
