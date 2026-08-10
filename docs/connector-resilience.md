# Connector Resilience

Why the hosted MCP connector to app.jobcontext.ai used to need a manual
reconnect after every deploy, and what now makes a deploy survivable.

## The incident

2026-08-01: the connector to `app.jobcontext.ai` (the OAuth-proxy path used
by Claude.ai and Claude Code — not the mobile PAT path) dropped three times
in one working session. Each drop reported either *"The user's connection to
this connector was invalidated. The user needs to reconnect it."* or
*"Connection closed"*, and each one had to be reconnected by hand.

The pods were healthy throughout. `restartCount` was 0 on every pod; each
"restart" was a new ReplicaSet from a deploy or an explicit `kubectl rollout
restart`. Pod start times (UTC) were 20:57, 23:30 and 23:49, plus a manual
restart around 19:52 the evening before. The drops tracked those events
exactly.

So the interesting question was never *why does the server go away* — it goes
away by design, see [Why Recreate stays](#why-recreate-stays). It was **why a
~60-second outage required a manual reconnect instead of the client resuming
with the token it already held.**

Two independent defects, both since fixed.

## Defect 1 — the MCP session was process-local and unrecoverable

`server.py` built `FastMCP(...)` without `stateless_http`, so the SDK
defaulted to session mode. In session mode
`StreamableHTTPSessionManager` keeps every live session in a plain in-process
dict:

```python
self._server_instances: dict[str, StreamableHTTPServerTransport] = {}
```

Nothing persists that dict. It is not on the PVC, not in SQLite, not
anywhere — and shutdown explicitly `.clear()`s it. No `event_store` was
configured either, so `event_store=None` meant SSE streams were **not
resumable**: a client could not replay from a `Last-Event-ID` after the
stream was cut.

The result, from the SDK's own request handler: a request arriving with an
`Mcp-Session-Id` the process has never seen falls through to

```python
# Unknown or expired session ID - return 404 per MCP spec
```

Every deploy therefore destroyed every live session, and the client's next
request produced a 404 with no resume path. That is the "Connection closed"
half.

**Worth being clear about what was *not* wrong.** The OAuth proxy
(`transport/http/routes/oauth.py`) stores nothing at all. `/oauth/register`
is a static shim that echoes the pre-configured `ENTRA_CLIENT_ID` back —
there is no dynamic-registration table to lose. `/oauth/authorize` and
`/oauth/token` strip the `resource` param and forward to Entra; no
authorization code or token is ever retained server-side. Access tokens are
Entra-issued JWTs validated per request against Entra's published keys.
**None of that state can go stale on a restart, because none of it is ours.**
This is not the mobile app's rotating-refresh-token failure — the state being
lost was the MCP transport session, one layer up.

### Fix

`stateless_http=True`. A fresh transport per request, no `Mcp-Session-Id`
issued, nothing retained between calls — there is no longer any session to
lose. A pod replacement now costs exactly one failed request; the client
retries with the credential it already holds.

This is safe here because the tool surface is pure request/response. No tool
takes an MCP `Context`, and nothing uses progress notifications, sampling,
elicitation, or resource subscriptions — so a per-request transport gives up
nothing. `MCP_STATELESS_HTTP=0` restores session mode if that ever changes.

## Defect 2 — "I cannot check this token" was reported as "this token is bad"

`EntraAuthProvider.authenticate_request` wrapped validation in a bare
`except Exception: return None`, and `UserDataContextMiddleware` turns `None`
into:

```
401 Unauthorized
WWW-Authenticate: Bearer realm="jobContextMCP"
{"error": "unauthorized", "detail": "Invalid credentials"}
```

That response means one specific thing to a client: *your credential is
dead, make the user authenticate again*. But it was also being emitted when
the server simply could not reach Entra's JWKS endpoint to check the
signature.

That path is reachable on exactly the schedule the incident followed. The
JWKS cache is process-local, so **it is cold on every new pod**, and
`PyJWKClient` fetches it with a blocking `urllib` call the first time a token
is validated. Any `URLError`/timeout in that window — DNS not yet resolvable
in a just-started pod, a slow TLS handshake, an Entra blip — raises
`PyJWKClientConnectionError`, which the bare `except` swallowed into "invalid
credentials". A perfectly good token, rejected as dead.

Two things made that window easy to hit:

- **Readiness was not gated on it.** Both probes pointed at `/health`, which
  returns a static 200 and touches nothing. The ingress started routing to
  the pod ~10s after start — straight into the cold-cache window.
- **The fetch ran on the event loop.** `authenticate_request` is called from
  `async def dispatch`, so that blocking HTTPS round-trip stalled *every*
  concurrent request, widening the window it created.

### Fix

Three parts:

1. **Distinguish the two failures.** `PyJWKClientConnectionError` (and any
   unexpected exception) now raises `AuthUnavailable`, which both auth entry
   points translate to **`503` + `Retry-After: 5` and no
   `WWW-Authenticate`** — retry, don't re-authenticate. Only a real
   `InvalidTokenError` (expired, malformed, wrong audience, bad signature)
   still returns `None` → 401 with the challenge.
2. **Warm the cache at boot, off the event loop.** A background task started
   in the FastAPI lifespan fetches the JWKS via `asyncio.to_thread` and
   refreshes every 30 min, comfortably inside the 1-hour cache lifespan. The
   inline validation path is now always a cache hit and never touches the
   network. (`to_thread`, not `run_in_executor` — it copies the context, so
   contextvars still propagate. See CLAUDE.md.)
3. **Gate readiness on it.** New `/ready` returns 503 until the JWKS is
   cached; `readinessProbe` points there. Liveness stays on `/health` and
   never checks a dependency, so an Entra outage cannot get the pod killed
   and restarted. If Entra is genuinely down, the pod stays un-Ready and the
   ingress returns a retryable 503 instead of the pod handing out 401s.

## Defect 2b — an unknown `kid` is not evidence either

The fix above left one case sitting in the catch-all: a token whose `kid` is
absent from the JWKS. PyJWT raises `PyJWKClientError` for it, which is **not**
an `InvalidTokenError`, so it fell through to `except Exception` →
`AuthUnavailable` → 503 on every attempt, forever. (In `server.py`'s legacy
`EntraAuthMiddleware` path it was a 500.) Neither is right, and neither is the
obvious alternative of calling it a 401.

The case is genuinely ambiguous:

- The token may be **foreign** — issued by another tenant, or forged. A 503
  loop never tells that caller anything.
- Entra may have just **rotated its signing keys**. `PyJWKClient` fetches over
  plain `urllib` and Entra serves its JWKS through a CDN, so even a forced
  re-fetch can be answered by an edge node still holding a pre-rotation copy.
  No request we can make proves we have seen the newest key set.

PyJWT's own `get_signing_key` does re-fetch on a miss before raising, so it is
tempting to read the exception as "we looked again and it still isn't there,
therefore it isn't ours". That inference does not hold — the second look can
be served the same stale edge copy as the first.

The costs are lopsided, which is the whole point. A wrong 401 carries
`WWW-Authenticate`, which invalidates the MCP connector and makes the user
reconnect by hand — the exact pain this document exists to remove. A wrong 503
costs the client one automatic retry.

### Fix — a ladder, not a verdict

`lib/auth.py` resolves signing keys itself rather than calling
`get_signing_key_from_jwt`, because it needs to know whether a fetch actually
happened, when, and how often:

1. Cache lookup. Hit → done, exactly as before.
2. Miss → force a fetch (rate limited to one attempt per 10s, since `kid` is
   attacker-chosen and each fetch is a blocking round-trip). Key now present →
   the token was fine all along; the cached view was simply behind.
3. Still missing → `SigningKeyUnavailable` → **503 + Retry-After**, and the
   kid is recorded in a miss ledger.
4. Same kid still missing from a freshly fetched key set **60s after its first
   miss** → `InvalidTokenError` → **401**. A rotation self-heals inside that
   window; a foreign token gets a definitive answer inside a minute.

Freshness outranks the ladder: if the key set cannot be shown to have been
fetched within the last 30s — the endpoint is unreachable, or nothing has ever
been fetched successfully — the answer is 503 regardless of how long the kid
has been missing. We do not reject on evidence we cannot date.

Everything that is not a verdict stays retryable: connection errors, and
`PyJWKClientError`s that mean "the endpoint returned no JSON object" or "no
signing keys in the set" (issuer-side faults wearing the same exception type
as a kid miss). A token carrying no `kid` at all is rejected immediately — no
rotation can conjure a key for a token that names none.

The ledger is deliberately small and bounded, because its keys come off an
**unverified** token header: entries are keyed by SHA-256 digest (so one
oversized `kid` cannot cost more than 64 bytes), capped at 256 with
oldest-first eviction, and expire after 15 minutes. Losing an entry only costs
that kid a fresh grace period — eviction can never manufacture a 401.

Tunables live at the top of `lib/auth.py`: `_KID_PROPAGATION_GRACE`,
`_FRESH_FETCH_WINDOW`, `_MIN_FORCED_FETCH_INTERVAL`, `_KID_MISS_TTL`,
`_KID_MISS_MAX`.

## Defect 3 — the refresh never worked, and nothing above could have saved it

Reported 2026-08-10: *"claude continues to drop connections periodically."*
Everything the earlier defects predict was absent. The pod had been up 2d19h
with `restartCount` 0, so no deploy, no pod replacement, no cold JWKS cache.
No `AuthUnavailable`, no 503s, no lines from the unknown-kid ladder. Defects 1,
2 and 2b were all fixed and all irrelevant.

The ingress access log showed the shape immediately. Per session: exactly one
`POST /mcp` 401 followed by a burst of 200s — that first 401 is *correct*, it
is the MCP client probing unauthenticated to collect the `WWW-Authenticate`
challenge. The failures are the hours holding a 401 with **no** 200s after it.
On 2026-08-08 there were three of those and not one successful call all day.

`POST /oauth/token` explains why, and it alternates with grim regularity:

```
06/Aug 21:00  200      <- manual reconnect: authorization_code
06/Aug 22:39  400      <- refresh, 1h39m later. connector dead
07/Aug 18:59  200      <- manual reconnect
07/Aug 20:21  400      <- refresh, 1h22m later. connector dead
09/Aug 16:53  200
09/Aug 21:31  400
```

The gap is one access-token lifetime. **Every** refresh this deployment has
ever attempted has failed; the connector only ever worked on the freshly
minted token from a hand-driven sign-in.

The proxy logs the body it forwards, and the failing one is:

```
grant_type=refresh_token   refresh_token=1.AVIAbr…   client_id=e4d85b54-…
```

No `scope`. RFC 6749 §6 makes it OPTIONAL on a refresh — omit it and you get
the originally granted scope — so the client is correct to leave it out, and
Claude's connector does. Entra v2.0 does not implement that default. With no
scope it cannot resolve a resource, falls back to the calling application, and
returns:

```
400 AADSTS90009: Application 'e4d85b54-…' (api://e4d85b54-…) is requesting
a token for itself. This scenario is supported only if resource is specified
using the GUID based App Identifier.
```

Self-reference is unavoidable here — one app registration is both the OAuth
client and the protected API — so the request has to name the resource
explicitly. The authorization_code exchange sends no scope either and works
fine, because the code already carries what was consented to at
`/oauth/authorize`; only the refresh has nothing to inherit from.

### Fix

`/oauth/token` already rewrites the body for Entra (it strips `resource`).
It now also supplies `scope` when a `refresh_token` grant arrives without one,
using the exact string `/oauth/register` advertises —
`api://<client_id>/access openid profile offline_access` — because Entra
matches a refresh against the scopes actually consented to. Both now come from
`_granted_scope()`, and a test asserts they are equal, since a drift between
them fails the same way with a different error.

`authorization_code` is deliberately untouched: it works, and the code carries
its own scope.

### Still to confirm

AADSTS90009's own advice is to name the resource "using the GUID based App
Identifier" — i.e. `<client_id>/access` rather than `api://<client_id>/access`.
This fix sends the `api://` form because that is what was consented to, but
that reasoning is not the same as a verification. Entra validates the refresh
token before it resolves scope, so a probe with a dummy token returns
`invalid_grant` for every scope form and cannot discriminate between them.
**The first real refresh after this deploys is the test.** If it still returns
AADSTS90009, switch `_granted_scope` to the GUID form — the plumbing is
unchanged either way.

## Why Recreate stays

`replicas: 1` + `strategy: Recreate` means every deploy is a hard outage of
roughly 30–60s with no server at all. That is deliberate and it must not be
"fixed" by switching to RollingUpdate.

The datastore is SQLite on the `jcmcp-data` PVC, and since PR #188
(`SQLITE_ONLY=1`) it is the *sole* source of truth. The PVC is:

```yaml
accessModes:
  - ReadWriteOnce
storageClassName: managed-premium   # Azure Disk
```

`RollingUpdate` with `maxSurge > 0` is unsafe in one direction and useless in
the other:

- **Same node.** ReadWriteOnce on Azure Disk is *node*-scoped, not
  pod-scoped. Two pods co-scheduled on the node already holding the disk both
  mount it successfully — and both open the same SQLite file for writing.
  That is the corruption case, and a single-node or disk-affinity-constrained
  scheduler makes it the *likely* placement, not a corner case.
- **Different node.** The surge pod blocks in `ContainerCreating` until the
  disk detaches from the old node, which cannot happen until the old pod
  terminates. The rollout serialises anyway, with a longer outage than
  Recreate.

So RollingUpdate either risks the database or makes the symptom worse. The
single-writer constraint is what pins this, and it holds as long as the
datastore is one SQLite file on one RWO volume. Revisit only if that changes
(e.g. a move to Postgres or SQLite in WAL mode on a ReadWriteMany volume with
a proven single-writer discipline) — not before.

What made Recreate *painful* was defect 1, and that is fixed at the transport
layer instead. Two smaller changes reduce the remaining edge:

- `terminationGracePeriodSeconds: 45` and a 5s `preStop` sleep, so the
  ingress drops the pod from its upstream set before uvicorn stops accepting
  and in-flight calls are not truncated mid-response.
- The readiness gate above, so the new pod takes traffic only once it can
  actually serve it.

## What a deploy looks like now

1. `preStop` fires; the ingress removes the pod; in-flight calls drain.
2. The pod terminates. For ~30–60s requests fail — the client sees connection
   errors, not `401`s and not `404 Session not found`.
3. The new pod starts, warms the JWKS, and only then reports `/ready`.
4. The client's next request carries the same bearer token and no session id.
   It succeeds.

No reconnect.

## Where to look if it recurs

- `GET /ready` — is the pod actually ready, or stuck warming the JWKS?
- `jwks_warm` log lines: `JWKS cached; token validation ready` on success,
  `JWKS warm-up failed (...); retrying` on failure.
- **`POST /oauth/token` in the ingress log is the first place to look for a
  periodic drop.** A `200` followed hours later by a `400` is a failing
  refresh, and the interval between them is the access-token lifetime. Pair it
  with the `oauth/token proxy payload:` line in the app log, which shows the
  grant type and whether a scope was present. A `POST /mcp` 401 on its own is
  not a fault — clients probe unauthenticated to get the challenge; the fault
  is a 401 with no 200s after it.
- A `503` with `Retry-After` in the client's logs means "could not verify" —
  look at Entra reachability. A `401` means the token really was rejected.
- During a key rotation, `kid=… absent from a freshly fetched JWKS (Ns of 60s
  grace)` at INFO is the ladder doing its job. The same kid reaching
  `treating token as foreign` at WARNING means propagation took longer than
  the grace period — raise `_KID_PROPAGATION_GRACE` if that ever happens for
  a legitimate token.
- `http_requests_total{route="/mcp",status="401"}` in Prometheus: any 401s on
  `/mcp` for a signed-in user are now a genuine credential problem, not
  infrastructure noise.
