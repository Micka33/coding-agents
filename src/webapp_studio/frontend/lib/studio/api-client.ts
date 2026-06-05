import {
  AppendMessageResultSchema,
  BranchSummarySchema,
  ConversationListSchema,
  ConversationSwitchResultSchema,
  QueueItemSchema,
  RunJoinResultSchema,
  StudioBranchUiStateSchema,
  StudioChangesSchema,
  StudioChangeDiffSchema,
  StudioEnvelopeSchema,
  StudioFilesSchema,
  StudioSessionSchema,
  StudioStateSchema,
  StudioTerminalOutputSchema,
  StudioTerminalSessionSchema,
  type AppendMessageResult,
  type BranchSummary,
  type ConversationList,
  type ConversationSwitchResult,
  type QueueItem,
  type RunJoinResult,
  type RuntimeSettings,
  type StudioBranchUiState,
  type StudioChanges,
  type StudioChangeDiff,
  type StudioFiles,
  type StudioSession,
  type StudioState,
  type StudioTerminalOutput,
  type StudioTerminalSession,
  type InterruptRequest,
} from "@/lib/studio/schemas"
import type { FileUIPart } from "ai"
import { z } from "zod"

export const MAX_STUDIO_ATTACHMENT_BYTES = 10 * 1024 * 1024
export const MAX_STUDIO_ATTACHMENT_REQUEST_BYTES = 25 * 1024 * 1024

type InterruptResumeInput = {
  decision: "approve" | "reject" | "edit" | "respond"
  response?: string
  editedPayload?: InterruptRequest["payload"]
}

type StudioAttachmentInput = {
  content_base64: string
  filename: string
  media_type: string | null
}

export class StudioApiClient {
  constructor(private readonly baseUrl = "/api/studio/v1") {}

  async state(): Promise<StudioState> {
    return this.request("/state", StudioStateSchema)
  }

  async session(): Promise<StudioSession> {
    return this.request("/session", StudioSessionSchema)
  }

  async conversations(limit = 20): Promise<ConversationList> {
    return this.request(`/conversations?limit=${encodeURIComponent(limit)}`, ConversationListSchema)
  }

  async switchConversation(conversationId: string): Promise<ConversationSwitchResult> {
    return this.request("/session/conversation", ConversationSwitchResultSchema, {
      method: "PUT",
      body: JSON.stringify({ conversation_id: conversationId }),
      headers: {
        "Content-Type": "application/json",
      },
    })
  }

  async files(): Promise<StudioFiles> {
    return this.request("/files", StudioFilesSchema)
  }

  async changes(): Promise<StudioChanges> {
    return this.request("/changes", StudioChangesSchema)
  }

  async changeDiff(diffUrl: string): Promise<StudioChangeDiff> {
    return this.request(this.relativeApiPath(diffUrl), StudioChangeDiffSchema)
  }

  async createTerminalSession(): Promise<StudioTerminalSession> {
    return this.request("/terminal/sessions", StudioTerminalSessionSchema, {
      method: "POST",
    })
  }

  async terminalOutput(
    sessionId: string,
    cursor: number
  ): Promise<StudioTerminalOutput> {
    return this.request(
      `/terminal/sessions/${encodeURIComponent(sessionId)}/output?cursor=${encodeURIComponent(cursor)}`,
      StudioTerminalOutputSchema
    )
  }

  async sendTerminalInput(
    sessionId: string,
    data: string
  ): Promise<StudioTerminalSession> {
    return this.request(
      `/terminal/sessions/${encodeURIComponent(sessionId)}/input`,
      StudioTerminalSessionSchema,
      {
        method: "POST",
        body: JSON.stringify({ data }),
        headers: {
          "Content-Type": "application/json",
        },
      }
    )
  }

  async resizeTerminal(
    sessionId: string,
    columns: number,
    rows: number
  ): Promise<StudioTerminalSession> {
    return this.request(
      `/terminal/sessions/${encodeURIComponent(sessionId)}/resize`,
      StudioTerminalSessionSchema,
      {
        method: "POST",
        body: JSON.stringify({ columns, rows }),
        headers: {
          "Content-Type": "application/json",
        },
      }
    )
  }

  async terminateTerminal(sessionId: string): Promise<StudioTerminalSession> {
    return this.request(
      `/terminal/sessions/${encodeURIComponent(sessionId)}`,
      StudioTerminalSessionSchema,
      {
        method: "DELETE",
      }
    )
  }

  async appendMessage(
    content: string,
    files: FileUIPart[] = [],
    clientMessageId?: string
  ): Promise<AppendMessageResult> {
    const attachments = attachmentsFromFileParts(files)
    return this.request("/messages", AppendMessageResultSchema, {
      method: "POST",
      body: JSON.stringify({
        content,
        author_id: "human",
        attachments,
        wait: false,
        client_message_id: clientMessageId,
      }),
      headers: {
        "Content-Type": "application/json",
      },
    })
  }

  async editMessage(
    messageId: string,
    content: string
  ): Promise<StudioState> {
    return this.request(
      `/messages/${encodeURIComponent(messageId)}/edit`,
      StudioStateSchema,
      {
        method: "POST",
        body: JSON.stringify({
          content,
          author_id: "human",
          wait: false,
        }),
        headers: {
          "Content-Type": "application/json",
        },
      }
    )
  }

  async updateRuntime(settings: Partial<RuntimeSettings>): Promise<StudioState> {
    return this.request("/runtime", StudioStateSchema, {
      method: "PATCH",
      body: JSON.stringify(settings),
      headers: {
        "Content-Type": "application/json",
      },
    })
  }

  async stopAgent(agentId: string): Promise<StudioState> {
    return this.request(
      `/agents/${encodeURIComponent(agentId)}/stop`,
      StudioStateSchema,
      {
        method: "POST",
      }
    )
  }

  async joinRun(runId: string): Promise<RunJoinResult> {
    return this.request(
      `/runs/${encodeURIComponent(runId)}/join`,
      RunJoinResultSchema,
      {
        method: "POST",
      }
    )
  }

  async cancelQueueItem(queueItemId: string): Promise<QueueItem[]> {
    return this.request(
      `/queue/${encodeURIComponent(queueItemId)}`,
      z.array(QueueItemSchema),
      {
        method: "DELETE",
      }
    )
  }

  async clearQueue(scope: "failed" | "pending" | "all" = "pending"): Promise<QueueItem[]> {
    return this.request("/queue/clear", z.array(QueueItemSchema), {
      method: "POST",
      body: JSON.stringify({ scope }),
      headers: {
        "Content-Type": "application/json",
      },
    })
  }

  async createBranch(input: {
    checkpointId?: string
    label?: string
    messageId?: string
  }): Promise<BranchSummary> {
    return this.request("/branches", BranchSummarySchema, {
      method: "POST",
      body: JSON.stringify({
        checkpoint_id: input.checkpointId,
        label: input.label,
        message_id: input.messageId,
      }),
      headers: {
        "Content-Type": "application/json",
      },
    })
  }

  async switchBranch(branchId: string): Promise<BranchSummary[]> {
    return this.request(
      `/branches/${encodeURIComponent(branchId)}/switch`,
      z.array(BranchSummarySchema),
      {
        method: "POST",
      }
    )
  }

  async archiveBranch(branchId: string): Promise<BranchSummary[]> {
    return this.request(
      `/branches/${encodeURIComponent(branchId)}/archive`,
      z.array(BranchSummarySchema),
      {
        method: "POST",
      }
    )
  }

  async updateUiState(input: {
    branchId: string
    draftContent: string
    outboxState: unknown
    editingEventId?: string | null
    participantId?: string
    scrollAnchorEventId?: string | null
    selectedAgentId?: string | null
  }): Promise<StudioBranchUiState> {
    return this.request("/ui-state", StudioBranchUiStateSchema, {
      method: "PATCH",
      body: JSON.stringify({
        branch_id: input.branchId,
        participant_id: input.participantId ?? "human",
        draft_content: input.draftContent,
        outbox_state: input.outboxState,
        editing_event_id: input.editingEventId ?? null,
        selected_agent_id: input.selectedAgentId ?? null,
        scroll_anchor_event_id: input.scrollAnchorEventId ?? null,
      }),
      headers: {
        "Content-Type": "application/json",
      },
    })
  }

  async resumeCheckpoint(
    checkpointId: string,
    input: {
      editedContent?: string
      mode?: "resume" | "regenerate" | "edit"
    } = {}
  ): Promise<StudioState> {
    return this.request(
      `/checkpoints/${encodeURIComponent(checkpointId)}/resume`,
      StudioStateSchema,
      {
        method: "POST",
        body: JSON.stringify({
          edited_content: input.editedContent,
          mode: input.mode ?? "resume",
        }),
        headers: {
          "Content-Type": "application/json",
        },
      }
    )
  }

  async resumeInterrupt(
    interruptId: string,
    input: InterruptResumeInput
  ): Promise<StudioState> {
    return this.request(
      `/interrupts/${encodeURIComponent(interruptId)}/resume`,
      StudioStateSchema,
      {
        method: "POST",
        body: JSON.stringify({
          decision: input.decision,
          response: input.response,
          edited_payload: input.editedPayload ?? {},
        }),
        headers: {
          "Content-Type": "application/json",
        },
      }
    )
  }

  private async request<TData>(
    path: string,
    schema: z.ZodType<TData>,
    init?: RequestInit
  ): Promise<TData> {
    const response = await fetch(`${this.baseUrl}${path}`, init)
    const payload = await response.json()
    const envelope = StudioEnvelopeSchema(z.unknown()).parse(payload)
    if (!response.ok) {
      const error = envelope.errors[0]
      throw new Error(error?.message ?? "Studio API request failed.")
    }
    return schema.parse(envelope.data)
  }

  private relativeApiPath(pathOrUrl: string) {
    const marker = "/api/studio/v1"
    if (pathOrUrl.startsWith(marker)) {
      return pathOrUrl.slice(marker.length) || "/"
    }
    return pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`
  }
}

export function normalizeStudioApiBaseUrl(baseUrl: string): string {
  const normalized = baseUrl.replace(/\/$/, "")
  if (normalized.endsWith("/api/studio/v1")) {
    return normalized
  }
  return `${normalized}/api/studio/v1`
}

function attachmentsFromFileParts(files: FileUIPart[]): StudioAttachmentInput[] {
  let totalBytes = 0
  return files.map((file) => {
    const parsed = parseDataUrl(file.url)
    totalBytes += parsed.sizeBytes
    if (parsed.sizeBytes > MAX_STUDIO_ATTACHMENT_BYTES) {
      throw new Error("Attachment exceeds the 10 MiB file limit.")
    }
    if (totalBytes > MAX_STUDIO_ATTACHMENT_REQUEST_BYTES) {
      throw new Error("Attachment request exceeds the 25 MiB limit.")
    }
    return {
      content_base64: parsed.contentBase64,
      filename: file.filename || "attachment",
      media_type: file.mediaType || parsed.mediaType,
    }
  })
}

function parseDataUrl(url: string | undefined) {
  const match = /^data:([^;,]*)(;base64)?,(.*)$/.exec(url ?? "")
  if (!match || match[2] !== ";base64") {
    throw new Error("Attachment data is not available for upload.")
  }
  const contentBase64 = match[3].replace(/\s/g, "")
  return {
    contentBase64,
    mediaType: match[1] || null,
    sizeBytes: base64Size(contentBase64),
  }
}

function base64Size(contentBase64: string) {
  const padding = contentBase64.endsWith("==") ? 2 : contentBase64.endsWith("=") ? 1 : 0
  return Math.floor((contentBase64.length * 3) / 4) - padding
}
