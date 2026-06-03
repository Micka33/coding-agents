import { normalizeStudioApiBaseUrl } from "@/lib/studio/api-client"

export const dynamic = "force-dynamic"
export const runtime = "nodejs"

type StudioProxyContext = {
  params: Promise<{
    path?: string[]
  }>
}

const capabilities = {
  streaming: "available",
  queue_control: "degraded",
  interrupts: "degraded",
  checkpoints: "degraded",
  branching: "degraded",
  time_travel: "degraded",
  generated_ui: "degraded",
} as const

export async function GET(request: Request, context: StudioProxyContext) {
  return proxyStudioRequest(request, context)
}

export async function POST(request: Request, context: StudioProxyContext) {
  return proxyStudioRequest(request, context)
}

export async function PUT(request: Request, context: StudioProxyContext) {
  return proxyStudioRequest(request, context)
}

export async function PATCH(request: Request, context: StudioProxyContext) {
  return proxyStudioRequest(request, context)
}

export async function DELETE(request: Request, context: StudioProxyContext) {
  return proxyStudioRequest(request, context)
}

async function proxyStudioRequest(
  request: Request,
  context: StudioProxyContext
) {
  const rawBaseUrl = process.env.STUDIO_API_BASE_URL
  if (!rawBaseUrl) {
    return studioProxyError(
      503,
      "STUDIO_API_BASE_URL is not configured for the Next.js proxy."
    )
  }

  const { path = [] } = await context.params
  const incomingUrl = new URL(request.url)
  const targetUrl = new URL(
    `${normalizeStudioApiBaseUrl(rawBaseUrl)}/${path.map(encodeURIComponent).join("/")}`
  )
  targetUrl.search = incomingUrl.search

  try {
    const body =
      request.method === "GET" || request.method === "HEAD"
        ? undefined
        : await request.arrayBuffer()
    const upstream = await fetch(targetUrl, {
      method: request.method,
      body,
      headers: proxyHeaders(request.headers),
      cache: "no-store",
      redirect: "manual",
    })

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders(upstream.headers),
    })
  } catch (error) {
    return studioProxyError(
      502,
      error instanceof Error ? error.message : "Studio backend is unreachable."
    )
  }
}

function proxyHeaders(headers: Headers) {
  const proxied = new Headers(headers)
  proxied.delete("host")
  proxied.delete("x-forwarded-host")
  return proxied
}

function responseHeaders(headers: Headers) {
  const proxied = new Headers()
  for (const name of ["content-type", "cache-control", "x-accel-buffering"]) {
    const value = headers.get(name)
    if (value) {
      proxied.set(name, value)
    }
  }
  return proxied
}

function studioProxyError(status: number, message: string) {
  return Response.json(
    {
      schema_version: "studio.v1",
      request_id: "req_next_proxy",
      capabilities,
      data: {},
      errors: [
        {
          code: "proxy_error",
          message,
          field: null,
          retryable: true,
          details: {},
        },
      ],
    },
    { status }
  )
}
