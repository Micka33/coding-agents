import { StudioWorkspace } from "@/components/studio/studio-workspace"
import { StudioWorkspaceLoader } from "@/components/studio/studio-workspace-loader"
import { loadStudioMock } from "@/lib/studio/fixtures"

export const dynamic = "force-dynamic"

export default function Page() {
  if (process.env.STUDIO_API_BASE_URL) {
    return <StudioWorkspaceLoader />
  }

  const data = loadStudioMock()

  return (
    <StudioWorkspace
      generatedUi={data.generatedUi}
      initialState={data.state}
      liveApi={data.liveApi}
    />
  )
}
