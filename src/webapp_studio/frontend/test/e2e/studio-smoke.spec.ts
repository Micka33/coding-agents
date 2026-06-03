import { expect, test } from "@playwright/test"

test("studio workspace keeps chat primary with inspector side surfaces", async ({ page }) => {
  await page.goto("/")

  await expect(page.getByText("Public Transcript")).toBeVisible()

  await openWorkspaceView(page, "Generated UI")
  await expect(page.getByRole("heading", { name: "Generated UI", exact: true }).first()).toBeVisible()

  await openWorkspaceView(page, "Activity")
  await expect(page.getByRole("heading", { name: "Activity", exact: true }).first()).toBeVisible()

  await openWorkspaceView(page, "Changes")
  await expect(page.getByRole("heading", { name: "Changes", exact: true }).first()).toBeVisible()

  const viewport = page.viewportSize()
  const mainBox = await page.locator("main").boundingBox()
  expect(mainBox?.width).toBeLessThanOrEqual(viewport?.width ?? Number.POSITIVE_INFINITY)
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  ).toBe(false)
})

test("mobile layout exposes sidebar as a drawer", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "mobile-only responsive behavior")
  await page.goto("/")

  await expect(page.getByText("Public Transcript")).toBeVisible()
  await page.getByRole("button", { name: "Expand sidebar" }).click()
  const drawer = page.getByLabel("Sidebar drawer")
  await expect(drawer.getByRole("heading", { name: "Webapp Studio" })).toBeVisible()
  await drawer.getByRole("button", { name: "Files" }).click()
  await expect(page.getByRole("heading", { name: "Files", exact: true }).first()).toBeVisible()
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  ).toBe(false)
})

async function openWorkspaceView(page: import("@playwright/test").Page, label: string) {
  if (await clickFirstVisible(page.getByRole("button", { name: `Open ${label}`, exact: true }))) {
    return
  }
  if (await clickFirstVisible(page.getByRole("button", { name: label, exact: true }))) {
    return
  }
  throw new Error(`No visible workspace view button found for ${label}.`)
}

async function clickFirstVisible(locator: import("@playwright/test").Locator) {
  for (let index = 0; index < await locator.count(); index += 1) {
    const candidate = locator.nth(index)
    if (!await candidate.isVisible()) {
      continue
    }
    try {
      await candidate.click({ timeout: 5_000 })
      return true
    } catch {
      continue
    }
  }
  return false
}
