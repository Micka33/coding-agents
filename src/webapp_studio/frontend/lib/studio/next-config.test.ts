import { describe, expect, it } from "vitest"

import nextConfig from "../../next.config"

describe("studio Next config", () => {
  it("sets conservative browser security headers", async () => {
    if (!nextConfig.headers) {
      throw new Error("Expected Studio Next config to define headers")
    }

    const routes = await nextConfig.headers()

    expect(routes).toContainEqual({
      source: "/:path*",
      headers: expect.arrayContaining([
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "no-referrer" },
        {
          key: "Content-Security-Policy",
          value: expect.stringContaining("object-src 'none'"),
        },
        {
          key: "Content-Security-Policy",
          value: expect.stringContaining("connect-src 'self' blob:"),
        },
      ]),
    })
  })
})
