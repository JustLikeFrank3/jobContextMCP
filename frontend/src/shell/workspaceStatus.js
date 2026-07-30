// State for the sidebar's workspace status card.
//
// Desktop is only "local" while cloud sync is unconfigured — once a PAT is
// saved the workspace leaves the device every 15 minutes, so the card must
// reflect the /desktop/sync status instead of claiming nothing does.

function hostOf(url) {
  if (!url) return 'cloud'
  try {
    return new URL(url).host || url
  } catch {
    return url
  }
}

function fmtSyncTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

/**
 * @param {boolean} isDesktop  backend is the desktop app
 * @param {object|null} sync   GET /desktop/sync payload (null until loaded / on error)
 * @returns {{label: string, detail: string, warn: boolean}}
 */
export function workspaceStatusCard(isDesktop, sync) {
  if (!isDesktop) {
    return {
      label: 'CLOUD WORKSPACE',
      detail: 'Synced workspace — desktop and mobile stay up to date.',
      warn: false,
    }
  }
  if (!sync?.configured) {
    return {
      label: 'LOCAL · SQLITE',
      detail: 'All data stays on this machine. Nothing leaves the device.',
      warn: false,
    }
  }
  const host = hostOf(sync.url)
  if (sync.last?.status === 'error') {
    return {
      label: 'LOCAL · SYNC FAILING',
      detail: `Cloud sync with ${host} is failing — check Settings → Cloud sync.`,
      warn: true,
    }
  }
  const when = fmtSyncTime(sync.last?.finished)
  return {
    label: 'LOCAL · SYNCED',
    detail: `Local SQLite, syncing with ${host}${when ? ` · last sync ${when}` : ''}.`,
    warn: false,
  }
}
