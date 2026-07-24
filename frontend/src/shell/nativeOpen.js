// Desktop-aware link opening. The Tauri webview supports neither
// window.open popups nor download-attribute navigation, so on desktop the
// backend opens targets natively (OS-default app for workspace files, the
// system browser for URLs). On the hosted product callers keep their normal
// anchor/popup behavior.
import { apiPost } from '../auth/api.js'

/** Open a workspace-file href (materials/pipeline artifacts) natively.
 *  Resolves true/false; pass notify:false to render failures inline —
 *  window.alert is unreliable in the Tauri webview (notably WebKitGTK),
 *  which made Linux failures fully silent. */
export function openFileNative(href, { notify = true } = {}) {
  return apiPost('/desktop/open-file', { href }).then(
    () => true,
    () => {
      if (notify) window.alert('Could not open the file.')
      return false
    },
  )
}

/** Open an external http(s) URL in the system browser. */
export function openUrlNative(url) {
  return apiPost('/desktop/open-url', { url }).catch(() => {
    window.alert('Could not open the link.')
  })
}

/** Anchor onClick handler: native-open on desktop, default behavior otherwise. */
export function nativeAnchorHandler(isDesktop, target, kind = 'url') {
  if (!isDesktop) return undefined
  return (e) => {
    e.preventDefault()
    if (kind === 'file') openFileNative(target)
    else openUrlNative(target)
  }
}
