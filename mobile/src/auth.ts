// Entra sign-in via the cloud's own OAuth proxy (the same authorize/token
// endpoints Claude connectors use). The proxy supports dynamic client
// registration and PKCE passthrough, so the app registers itself on first
// sign-in — no Azure portal changes. Access/refresh tokens live in the
// device keychain; api.ts refreshes transparently.
import * as AuthSession from 'expo-auth-session'
import * as SecureStore from 'expo-secure-store'

const CLIENT_ID_KEY = 'jc_oauth_client_id'
const ACCESS_KEY = 'jc_access_token'
const REFRESH_KEY = 'jc_refresh_token'
const EXPIRES_KEY = 'jc_token_expires_at'

const SCOPES = [
  'api://e4d85b54-17d4-4754-af60-85b056586af1/access',
  'openid',
  'profile',
  'offline_access',
]

// Screens mount once and cache their fetch result, so sign-in/sign-out has to
// be observable: Settings flips the switch, every other tab needs to hear it.
type AuthListener = (signedIn: boolean) => void
const authListeners = new Set<AuthListener>()

/** Subscribe to sign-in/sign-out transitions. Returns an unsubscribe fn. */
export function onAuthChange(listener: AuthListener): () => void {
  authListeners.add(listener)
  return () => {
    authListeners.delete(listener)
  }
}

function notifyAuthChange(signedIn: boolean): void {
  authListeners.forEach((l) => l(signedIn))
}

export const redirectUri = AuthSession.makeRedirectUri({ scheme: 'jobcontext', path: 'auth' })

function discovery(baseUrl: string): AuthSession.DiscoveryDocument {
  return {
    authorizationEndpoint: `${baseUrl}/oauth/authorize`,
    tokenEndpoint: `${baseUrl}/oauth/token`,
  }
}

async function ensureClientId(baseUrl: string): Promise<string> {
  const cached = await SecureStore.getItemAsync(CLIENT_ID_KEY)
  if (cached) return cached
  const res = await fetch(`${baseUrl}/oauth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      client_name: 'jobContext mobile',
      redirect_uris: [redirectUri],
      grant_types: ['authorization_code', 'refresh_token'],
      token_endpoint_auth_method: 'none',
    }),
  })
  if (!res.ok) throw new Error(`Registration failed (${res.status})`)
  const body = await res.json()
  await SecureStore.setItemAsync(CLIENT_ID_KEY, body.client_id)
  return body.client_id
}

async function storeTokens(t: AuthSession.TokenResponse): Promise<void> {
  await SecureStore.setItemAsync(ACCESS_KEY, t.accessToken)
  if (t.refreshToken) await SecureStore.setItemAsync(REFRESH_KEY, t.refreshToken)
  const expiresAt = Date.now() + (t.expiresIn ?? 3600) * 1000
  await SecureStore.setItemAsync(EXPIRES_KEY, String(expiresAt))
}

/** Interactive sign-in. Returns true on success. */
export async function signIn(baseUrl: string): Promise<boolean> {
  const clientId = await ensureClientId(baseUrl)
  const request = new AuthSession.AuthRequest({
    clientId,
    redirectUri,
    scopes: SCOPES,
    usePKCE: true,
  })
  const result = await request.promptAsync(discovery(baseUrl))
  if (result.type !== 'success' || !result.params.code) return false
  const tokens = await AuthSession.exchangeCodeAsync(
    {
      clientId,
      redirectUri,
      code: result.params.code,
      extraParams: { code_verifier: request.codeVerifier ?? '' },
    },
    discovery(baseUrl),
  )
  await storeTokens(tokens)
  notifyAuthChange(true)
  return true
}

// Refresh tokens rotate server-side (each is usable once). App start fires
// several concurrent api() calls (push registration + the focused tab's own
// fetch) that can all land near expiry at once — without single-flighting,
// each one independently redeems the same refresh token, only the first
// succeeds, and the rest get invalid_grant and report "signed out" (the
// intermittent-logout bug). This cache makes every concurrent caller await
// the one in-flight refresh instead of racing.
let refreshInFlight: Promise<string | null> | null = null

async function refreshAccessToken(
  baseUrl: string,
  refresh: string,
  staleAccess: string,
): Promise<string | null> {
  try {
    const clientId = await ensureClientId(baseUrl)
    const tokens = await AuthSession.refreshAsync(
      { clientId, refreshToken: refresh },
      discovery(baseUrl),
    )
    await storeTokens(tokens)
    return tokens.accessToken
  } catch (e: any) {
    // expo-auth-session surfaces OAuth errors as TokenError with a .code.
    // invalid_grant = the rotating refresh token is spent or revoked — that
    // IS a sign-out, so clear the keychain and tell the UI (otherwise
    // Settings keeps claiming "signed in" while every call fails). Anything
    // else — offline at cold launch, 5xx, timeout — is transient: keep the
    // stored tokens and hand back the stale access token so the caller gets
    // an honest network/401 error instead of a false "Not signed in".
    const code = e?.code ?? e?.params?.error
    if (code === 'invalid_grant' || code === 'invalid_client' || code === 'unauthorized_client') {
      await signOut()
      return null
    }
    return staleAccess
  }
}

/** Current bearer token, silently refreshed when near expiry. Null = signed out. */
export async function getAccessToken(baseUrl: string): Promise<string | null> {
  const [access, refresh, expiresAt] = await Promise.all([
    SecureStore.getItemAsync(ACCESS_KEY),
    SecureStore.getItemAsync(REFRESH_KEY),
    SecureStore.getItemAsync(EXPIRES_KEY),
  ])
  if (!access) return null
  if (Date.now() < Number(expiresAt || 0) - 60_000) return access
  if (!refresh) return null
  if (!refreshInFlight) {
    refreshInFlight = refreshAccessToken(baseUrl, refresh, access).finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

export async function signOut(): Promise<void> {
  await Promise.all([
    SecureStore.deleteItemAsync(ACCESS_KEY),
    SecureStore.deleteItemAsync(REFRESH_KEY),
    SecureStore.deleteItemAsync(EXPIRES_KEY),
  ])
  notifyAuthChange(false)
}

export async function isSignedIn(): Promise<boolean> {
  return Boolean(await SecureStore.getItemAsync(ACCESS_KEY))
}
