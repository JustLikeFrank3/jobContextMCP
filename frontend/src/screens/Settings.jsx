import { useApi, Screen, SectionHead } from './_shared.jsx'
import { Panel } from '../design-system'
import useDesktopMode from '../shell/useDesktopMode.js'
import StatusRow from './settings/StatusRow.jsx'
import AiProviderSection from './settings/AiProviderSection.jsx'
import McpClientsSection from './settings/McpClientsSection.jsx'
import DataSection from './settings/DataSection.jsx'
import CloudSyncSection from './settings/CloudSyncSection.jsx'
import OuraSection, { FlashBanner, OuraCompatChip, useOuraFlash } from './settings/OuraSection.jsx'

/* Settings: account integrations, desktop-only configuration (AI provider,
   MCP clients, cloud sync, data import/export), and the Oura Ring connection.
   Each section lives in ./settings/ and owns its own data fetching; sections
   whose /desktop endpoints 404 on the hosted product render nothing.

   Data: GET /api/dashboard/settings */

export default function Settings() {
  const { data, loading, error, reload } = useApi('/api/dashboard/settings')
  const flash = useOuraFlash()
  const isDesktop = useDesktopMode()

  return (
    <Screen loading={loading} error={error}>
      <FlashBanner flash={flash} />

      <SectionHead title="Integrations" />
      <Panel style={{ marginBottom: 20 }}>
        <div style={{ display: 'grid', gap: 10 }}>
          <StatusRow label={`AI generation${data?.aiProvider ? ` (${data.aiProvider})` : ''}`} ok={data?.openaiKeySet} okText="configured" offText="not set">
            Enables resume generation, cover letter drafting, and semantic search.
          </StatusRow>
          <StatusRow label="Oura Ring" ok={data?.ouraConnected} okText="connected" offText="not connected">
            Readiness data powers the Home dashboard hero.
          </StatusRow>
        </div>
        {/* Legacy server-rendered settings page. Hidden on desktop: the
            webview has no back button, so a full-page nav out of the SPA
            strands the user — and the AI provider section below covers
            key entry there anyway. */}
        {!isDesktop && (
          <div style={{ marginTop: 16, textAlign: 'center' }}>
            <a
              href={data?.classicUrl || '/dashboard/settings'}
              style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-sm)', textDecoration: 'none' }}
            >
              Edit AI key and preferences {'→'}
            </a>
          </div>
        )}
      </Panel>

      <AiProviderSection />
      <McpClientsSection />
      <DataSection isDesktop={isDesktop} />
      {isDesktop && <CloudSyncSection />}

      <SectionHead title="Oura Ring" />
      <OuraCompatChip />
      <OuraSection data={data} reload={reload} isDesktop={isDesktop} />
    </Screen>
  )
}
