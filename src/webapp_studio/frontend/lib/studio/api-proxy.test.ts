import { describe, expect, it } from "vitest"

import { GET, POST, PUT } from "@/app/api/studio/v1/[...path]/route"

const capabilities = {
  streaming: "available",
  queue_control: "degraded",
  interrupts: "degraded",
  checkpoints: "degraded",
  branching: "degraded",
  time_travel: "degraded",
  generated_ui: "degraded",
} as const

describe("studio Next API proxy", () => {
  it("forwards path, query, method, and body to the configured backend", async () => {
    const previousFetch = globalThis.fetch
    const previousApiBaseUrl = process.env.STUDIO_API_BASE_URL
    const requests: Array<{
      body: string | undefined
      method: string | undefined
      url: string
    }> = []

    globalThis.fetch = async (input, init) => {
      requests.push({
        body:
          init?.body instanceof ArrayBuffer
            ? new TextDecoder().decode(init.body)
            : undefined,
        method: init?.method,
        url: String(input),
      })

      return new Response(
        JSON.stringify({
          schema_version: "studio.v1",
          request_id: "req_backend",
          capabilities,
          data: { ok: true },
          errors: [],
        }),
        {
          headers: {
            "Content-Type": "application/json",
          },
          status: 200,
        }
      )
    }
    process.env.STUDIO_API_BASE_URL = "http://127.0.0.1:8765"

    try {
      const getResponse = await GET(
        new Request("http://studio.local/api/studio/v1/state?fresh=1"),
        { params: Promise.resolve({ path: ["state"] }) }
      )
      const postResponse = await POST(
        new Request("http://studio.local/api/studio/v1/messages", {
          body: JSON.stringify({ content: "@agent hi" }),
          method: "POST",
        }),
        { params: Promise.resolve({ path: ["messages"] }) }
      )
      const putResponse = await PUT(
        new Request("http://studio.local/api/studio/v1/session/conversation", {
          body: JSON.stringify({ conversation_id: "thread-2" }),
          method: "PUT",
        }),
        { params: Promise.resolve({ path: ["session", "conversation"] }) }
      )

      expect(await getResponse.json()).toEqual({
        schema_version: "studio.v1",
        request_id: "req_backend",
        capabilities,
        data: { ok: true },
        errors: [],
      })
      expect(postResponse.status).toBe(200)
      expect(putResponse.status).toBe(200)
      expect(requests).toEqual([
        {
          body: undefined,
          method: "GET",
          url: "http://127.0.0.1:8765/api/studio/v1/state?fresh=1",
        },
        {
          body: JSON.stringify({ content: "@agent hi" }),
          method: "POST",
          url: "http://127.0.0.1:8765/api/studio/v1/messages",
        },
        {
          body: JSON.stringify({ conversation_id: "thread-2" }),
          method: "PUT",
          url: "http://127.0.0.1:8765/api/studio/v1/session/conversation",
        },
      ])
    } finally {
      globalThis.fetch = previousFetch
      restoreStudioApiBaseUrl(previousApiBaseUrl)
    }
  })

  it("returns a studio envelope when no backend is configured", async () => {
    const previousApiBaseUrl = process.env.STUDIO_API_BASE_URL
    delete process.env.STUDIO_API_BASE_URL

    try {
      const response = await GET(
        new Request("http://studio.local/api/studio/v1/state"),
        { params: Promise.resolve({ path: ["state"] }) }
      )
      const payload = await response.json()

      expect(response.status).toBe(503)
      expect(payload.errors[0].code).toBe("proxy_error")
    } finally {
      restoreStudioApiBaseUrl(previousApiBaseUrl)
    }
  })
})

function restoreStudioApiBaseUrl(value: string | undefined) {
  if (value === undefined) {
    delete process.env.STUDIO_API_BASE_URL
    return
  }
  process.env.STUDIO_API_BASE_URL = value
}
