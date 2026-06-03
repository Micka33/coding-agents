import { defineConfig, devices } from "@playwright/test"

const externalBaseURL = process.env.STUDIO_E2E_BASE_URL
const port = process.env.STUDIO_E2E_PORT ?? "3765"
const baseURL = externalBaseURL ?? `http://127.0.0.1:${port}`

export default defineConfig({
  testDir: "./test/e2e",
  timeout: 30_000,
  webServer: externalBaseURL
    ? undefined
    : {
        command: `pnpm dev --port ${port}`,
        url: baseURL,
        reuseExistingServer: true,
      },
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"] },
    },
  ],
})
