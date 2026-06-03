import type { NextConfig } from "next"

const contentSecurityPolicy = [
  "default-src 'self'",
  "connect-src 'self' http://127.0.0.1:* http://localhost:*",
  "img-src 'self' data: blob:",
  "style-src 'self' 'unsafe-inline'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "frame-src 'self' http://127.0.0.1:* http://localhost:*",
  "base-uri 'none'",
  "object-src 'none'",
].join("; ")

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
        ],
      },
    ]
  },
}

export default nextConfig
