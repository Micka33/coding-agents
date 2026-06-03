import { StudioApiClient, normalizeStudioApiBaseUrl } from "@/lib/studio/api-client"
import { loadStudioMock, type StudioMock } from "@/lib/studio/fixtures"

export async function loadInitialStudioData(): Promise<StudioMock> {
  const apiBaseUrl = process.env.STUDIO_API_BASE_URL
  if (!apiBaseUrl) {
    return loadStudioMock()
  }

  const state = await new StudioApiClient(normalizeStudioApiBaseUrl(apiBaseUrl)).state()
  return {
    state,
    generatedUi: state.generated_ui,
    liveApi: true,
  }
}
