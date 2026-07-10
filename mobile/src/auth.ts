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
  return true
}

/** Current bearer token, silently refreshed when near expiry. Null = signed out. */
// Single-flight guard: concurrent callers (Today fetch + share capture on a
// cold launch) must share ONE refresh. Refresh tokens rotate — two parallel
// refreshAsync calls spend the same token and the loser gets invalid_grant,
// surfacing as a phantom "Not signed in" on whichever surface lost the race.
let refreshInFlight: Promise<string | null> | null = null

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
    refreshInFlight = (async () => {
      try {
        const clientId = await ensureClientId(baseUrl)
        const tokens = await AuthSession.refreshAsync(
          { clientId, refreshToken: refresh },
          discovery(baseUrl),
        )
        await storeTokens(tokens)
        return tokens.accessToken
      } catch {
        return null
      } finally {
        // Always clear, even on failure — a stuck promise would otherwise
        // pin every future call to this one failed refresh until restart.
        refreshInFlight = null
      }
    })()
  }
  return refreshInFlight
}

export async function signOut(): Promise<void> {
  await Promise.all([
    SecureStore.deleteItemAsync(ACCESS_KEY),
    SecureStore.deleteItemAsync(REFRESH_KEY),
    SecureStore.deleteItemAsync(EXPIRES_KEY),
  ])
}

export async function isSignedIn(): Promise<boolean> {
  return Boolean(await SecureStore.getItemAsync(ACCESS_KEY))
}
