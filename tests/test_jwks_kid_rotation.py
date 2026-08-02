"""An unknown `kid` must not be called invalid until it has earned it.

Follow-up to #196.  That PR separated "could not check this credential"
(503 + Retry-After) from "checked it, it's bad" (401 + WWW-Authenticate),
because the second one invalidates a hosted MCP connector and makes the user
reconnect by hand.  It left one case undecided: a token whose `kid` is absent
from the JWKS.

PyJWT reports that as `PyJWKClientError`, and it is genuinely ambiguous:

  * The token may be foreign — another tenant's, or forged.
  * Entra may have just rotated its signing keys.  `PyJWKClient` fetches over
    urllib and Entra serves its JWKS through a CDN, so even a *forced*
    re-fetch can be answered by an edge holding a pre-rotation copy.  Nothing
    we can request proves we saw the newest key set.

An unconditional 401 breaks valid tokens during a rotation.  An unconditional
503 means a genuinely foreign token retries forever and never gets an answer.
So: report unavailable at first, and only harden into invalid once the same
kid has kept missing from freshly fetched key sets for longer than any
plausible propagation lag.

These tests pin that ladder, the freshness it depends on, and the fact that
the per-kid ledger cannot grow without bound — its keys come off an
unverified token header, so they are chosen by the caller.
"""

from __future__ import annotations

import io
import json
import time
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from lib import auth as auth_mod
from transport.http.security import AuthUnavailable, EntraAuthProvider

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()

_LIVE_KID = "live-kid"
_UNKNOWN_KID = "rotated-or-foreign-kid"


def _token(kid: str | None = _LIVE_KID, *, audience: str = "test-client-id") -> str:
    """Mint a signed RS256 JWT carrying `kid` in its header.

    Signs with the key object rather than re-serialising it to PEM on every
    call — several tests mint hundreds of tokens, and parsing the PEM back in
    dominates the runtime.
    """
    now = int(time.time())
    return jwt.encode(
        {
            "aud": audience,
            "iss": "https://login.microsoftonline.com/test-tenant/v2.0",
            "sub": "test-subject",
            "oid": "test-oid-123",
            "name": "Test User",
            "iat": now,
            "exp": now + 3600,
        },
        _PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": kid} if kid else None,
    )


def _jwks_dict(*kids: str) -> dict:
    """A JWKS document publishing `_PUBLIC_KEY` under each of `kids`."""
    jwk = RSAAlgorithm.to_jwk(_PUBLIC_KEY, as_dict=True)
    return {"keys": [{**jwk, "kid": k, "use": "sig"} for k in kids]}


class _Key:
    """Minimal stand-in for PyJWK."""

    def __init__(self, kid: str) -> None:
        self.key_id = kid
        self.key = _PUBLIC_KEY


class _FakeJWKSClient:
    """A PyJWKClient whose key set, cache and failures the test drives.

    Models the part of the real client the design leans on: `refresh=True`
    always goes to the network (and so can fail, and so refreshes the cached
    view), while `refresh=False` is served from cache when there is one.
    `kids` is what the endpoint would return now; `cached` is what this
    process last saw.  Fetches are counted so tests can assert a rejection was
    backed by a real round-trip — and that we do not make one per request.
    """

    match_kid = staticmethod(PyJWKClient.match_kid)

    def __init__(self, *kids: str) -> None:
        self.kids = list(kids)
        self.cached: list[str] | None = list(kids)  # warm, as after warm_jwks()
        self.cached_reads = 0
        self.network_fetches = 0
        self.error: Exception | None = None

    def get_signing_keys(self, refresh: bool = False) -> list[_Key]:
        if not refresh and self.cached is not None:
            self.cached_reads += 1
            return [_Key(k) for k in self.cached]
        self.network_fetches += 1
        if self.error is not None:
            raise self.error
        self.cached = list(self.kids)
        return [_Key(k) for k in self.cached]


class _Clock:
    """Monotonic clock the test moves by hand."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def monotonic(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def jwks():
    """Install a fake JWKS client and a hand-driven clock into lib.auth."""
    client = _FakeJWKSClient(_LIVE_KID)
    clock = _Clock()
    auth_mod._reset_jwks_state_for_tests()
    with (
        patch.object(auth_mod, "_get_jwks_client", return_value=client),
        patch.object(auth_mod, "time", clock),
        patch.object(auth_mod, "CLIENT_ID", "test-client-id"),
    ):
        yield client, clock
    auth_mod._reset_jwks_state_for_tests()


# ===========================================================================
# 1. What PyJWKClient actually does — the assumption the design rests on
# ===========================================================================

class TestPyJWTFetchSemantics:
    """`refresh=True` must really go to the network, and the cache must
    really keep the normal path off it.  Everything below reads "fresh" off
    fetches *we* make, so if either half of this changed, the ladder would be
    reasoning about a key set it never actually re-fetched."""

    def _client(self) -> PyJWKClient:
        # Same construction as lib.auth._get_jwks_client.
        return PyJWKClient(
            "https://example.invalid/keys",
            cache_jwk_set=True,
            lifespan=auth_mod._JWKS_LIFESPAN,
        )

    def _served(self):
        """Patch the transport, not `fetch_data` — the cache write lives
        inside `fetch_data`, so stubbing it out would test nothing."""
        def _urlopen(*_args, **_kwargs):
            return io.BytesIO(json.dumps(_jwks_dict(_LIVE_KID)).encode())

        return patch("urllib.request.urlopen", side_effect=_urlopen)

    def test_cached_reads_do_not_refetch(self):
        client = self._client()
        with self._served() as urlopen:
            client.get_signing_keys()
            client.get_signing_keys()
            assert urlopen.call_count == 1

    def test_refresh_true_bypasses_the_cache(self):
        client = self._client()
        with self._served() as urlopen:
            client.get_signing_keys()
            client.get_signing_keys(refresh=True)
            assert urlopen.call_count == 2

    def test_kid_miss_raises_a_non_invalid_token_error(self):
        """The ambiguous case is not an InvalidTokenError, so it would
        otherwise fall through whatever generic handler comes last."""
        assert not issubclass(PyJWKClientError, jwt.InvalidTokenError)


# ===========================================================================
# 2. The ladder: unavailable first, invalid only once it has earned it
# ===========================================================================

class TestUnknownKidLadder:
    def test_valid_token_is_untouched(self, jwks):
        client, _ = jwks
        claims = auth_mod.validate_token(_token())
        assert claims["oid"] == "test-oid-123"
        # A known kid is served from cache — no forced fetch, no ledger entry.
        assert client.network_fetches == 0
        assert auth_mod._kid_misses == {}

    def test_first_miss_is_unavailable(self, jwks):
        client, _ = jwks
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token(_UNKNOWN_KID))
        # …and it was a real re-fetch, not a shrug at a stale cache.
        assert client.network_fetches == 1

    def test_repeat_miss_after_the_grace_is_invalid(self, jwks):
        client, clock = jwks
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token(_UNKNOWN_KID))

        clock.advance(auth_mod._KID_PROPAGATION_GRACE + 5)
        with pytest.raises(jwt.InvalidTokenError):
            auth_mod.validate_token(_token(_UNKNOWN_KID))
        # The verdict was backed by a second network fetch, not by the first
        # one going stale in the cache.
        assert client.network_fetches == 2

    def test_retries_inside_the_grace_stay_unavailable(self, jwks):
        _, clock = jwks
        for _ in range(4):
            with pytest.raises(auth_mod.SigningKeyUnavailable):
                auth_mod.validate_token(_token(_UNKNOWN_KID))
            clock.advance(5)

    def test_rotation_self_heals_within_the_grace(self, jwks):
        """The point of the grace period: the key shows up, the token works,
        and nothing was ever told its credential was dead."""
        client, clock = jwks
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token(_UNKNOWN_KID))

        client.kids.append(_UNKNOWN_KID)  # CDN edge catches up
        clock.advance(20)
        claims = auth_mod.validate_token(_token(_UNKNOWN_KID))
        assert claims["oid"] == "test-oid-123"
        # Healing clears the ledger, so a later miss starts its own grace.
        assert auth_mod._kid_misses == {}

    def test_each_kid_gets_its_own_grace(self, jwks):
        """One kid exhausting its grace must not condemn the next one."""
        _, clock = jwks
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token("kid-a"))
        clock.advance(auth_mod._KID_PROPAGATION_GRACE + 5)

        with pytest.raises(jwt.InvalidTokenError):
            auth_mod.validate_token(_token("kid-a"))
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token("kid-b"))

    def test_token_without_a_kid_is_invalid_immediately(self, jwks):
        """No rotation can conjure a key for a token that names none."""
        client, _ = jwks
        with pytest.raises(jwt.InvalidTokenError):
            auth_mod.validate_token(_token(None))
        assert client.network_fetches == 0

    def test_non_string_kid_is_invalid_immediately(self, jwks):
        """The header is unverified JSON, so `kid` need not be a string."""
        client, _ = jwks
        with pytest.raises(jwt.InvalidTokenError):
            auth_mod.validate_token(_token({"not": "a string"}))
        assert client.network_fetches == 0
        assert auth_mod._kid_misses == {}


# ===========================================================================
# 3. Everything that is not a verdict stays retryable
# ===========================================================================

class TestNonVerdicts:
    def test_connection_error_propagates(self, jwks):
        """Cold pod, unreachable issuer: even a good kid cannot be checked."""
        client, _ = jwks
        client.cached = None
        client.error = PyJWKClientConnectionError("connection refused")
        with pytest.raises(PyJWKClientConnectionError):
            auth_mod.validate_token(_token())

    def test_connection_error_during_the_forced_refetch_propagates(self, jwks):
        """A miss that we could not confirm against the network is not a
        verdict either — even the second time around."""
        client, clock = jwks
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token(_UNKNOWN_KID))

        clock.advance(auth_mod._KID_PROPAGATION_GRACE + 5)
        client.error = PyJWKClientConnectionError("connection refused")
        with pytest.raises(PyJWKClientConnectionError):
            auth_mod.validate_token(_token(_UNKNOWN_KID))

    def test_broken_key_set_is_unavailable_not_invalid(self, jwks):
        """An empty or malformed key set is a fault at the issuer wearing the
        same exception type as a kid miss — it says nothing about the token."""
        client, _ = jwks
        client.cached = None
        client.error = PyJWKClientError("The JWKS endpoint did not contain any signing keys")
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token())

    def test_a_stale_key_set_cannot_support_a_rejection(self, jwks):
        """Freshness outranks the grace period.

        With Entra unreachable, forced fetches are throttled rather than
        attempted per request — so what we hold gets older while the kid goes
        on missing.  Once it is too old to prove anything, the answer goes
        back to "cannot check" even though the grace has long expired.
        """
        client, clock = jwks
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token(_UNKNOWN_KID))  # fetch succeeds here

        client.error = PyJWKClientConnectionError("connection refused")
        clock.advance(auth_mod._KID_PROPAGATION_GRACE + 10)
        with pytest.raises(PyJWKClientConnectionError):
            auth_mod.validate_token(_token(_UNKNOWN_KID))  # attempt, fails

        clock.advance(1)  # inside the throttle window: no attempt at all
        client.error = None
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token(_UNKNOWN_KID))
        assert client.network_fetches == 2  # the third request made none

    def test_no_successful_fetch_yet_is_unavailable(self, jwks):
        """A key set we have never confirmed cannot condemn anything either."""
        client, clock = jwks
        client.error = PyJWKClientConnectionError("connection refused")
        with pytest.raises(PyJWKClientConnectionError):
            auth_mod.validate_token(_token(_UNKNOWN_KID))

        clock.advance(1)  # throttled, so the cached set is all we have
        client.error = None
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token(_UNKNOWN_KID))

    def test_failed_fetches_are_throttled_too(self, jwks):
        """An Entra outage must not become one blocking connection per
        request just because the fetch is failing."""
        client, clock = jwks
        client.error = PyJWKClientConnectionError("connection refused")
        for _ in range(20):
            with pytest.raises(
                (PyJWKClientConnectionError, auth_mod.SigningKeyUnavailable)
            ):
                auth_mod.validate_token(_token(_UNKNOWN_KID))
            clock.advance(1)
        assert client.network_fetches == 2  # t+0 and t+10, not twenty


# ===========================================================================
# 4. The ledger is bounded — its keys are chosen by the caller
# ===========================================================================

class TestLedgerIsBounded:
    def test_many_distinct_kids_do_not_grow_it_without_bound(self, jwks):
        for i in range(auth_mod._KID_MISS_MAX * 3):
            with pytest.raises(auth_mod.SigningKeyUnavailable):
                auth_mod.validate_token(_token(f"junk-kid-{i}"))
        assert len(auth_mod._kid_misses) <= auth_mod._KID_MISS_MAX

    def test_a_huge_kid_costs_a_fixed_size_entry(self, jwks):
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token("x" * 100_000))
        assert len(auth_mod._kid_misses) == 1
        (stored,) = auth_mod._kid_misses
        assert len(stored) == 64  # sha256 hex, whatever was sent

    def test_eviction_takes_the_oldest_first(self, jwks):
        _, clock = jwks
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token("oldest"))
        oldest = auth_mod._kid_digest("oldest")
        assert oldest in auth_mod._kid_misses

        clock.advance(1)
        for i in range(auth_mod._KID_MISS_MAX):
            with pytest.raises(auth_mod.SigningKeyUnavailable):
                auth_mod.validate_token(_token(f"later-{i}"))

        assert oldest not in auth_mod._kid_misses
        assert len(auth_mod._kid_misses) <= auth_mod._KID_MISS_MAX

    def test_entries_expire(self, jwks):
        _, clock = jwks
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token(_UNKNOWN_KID))

        clock.advance(auth_mod._KID_MISS_TTL + 1)
        # Expired, so this counts as a first miss again: unavailable, not a
        # 401 carried over from a rotation that ended long ago.
        with pytest.raises(auth_mod.SigningKeyUnavailable):
            auth_mod.validate_token(_token(_UNKNOWN_KID))
        assert len(auth_mod._kid_misses) == 1

    def test_network_fetches_are_rate_limited(self, jwks):
        """A flood of made-up kids must not become a flood of blocking
        fetches against login.microsoftonline.com."""
        client, _ = jwks
        for i in range(50):
            with pytest.raises(auth_mod.SigningKeyUnavailable):
                auth_mod.validate_token(_token(f"junk-kid-{i}"))
        assert client.network_fetches == 1


# ===========================================================================
# 5. …and the HTTP layer turns each into the right status
# ===========================================================================

class TestProviderMapping:
    def _authenticate(self, exc):
        provider = EntraAuthProvider()
        with patch("lib.auth.validate_token", side_effect=exc):
            return provider.authenticate_request("Bearer token", None)

    def test_unresolved_kid_is_retryable(self):
        with pytest.raises(AuthUnavailable):
            self._authenticate(auth_mod.SigningKeyUnavailable("not visible yet"))

    def test_hardened_kid_miss_is_a_rejection(self):
        assert self._authenticate(
            jwt.InvalidTokenError('Unable to find a signing key that matches: "x"')
        ) is None

    def test_connection_error_is_retryable(self):
        with pytest.raises(AuthUnavailable):
            self._authenticate(PyJWKClientConnectionError("down"))

    def test_valid_token_still_authenticates(self):
        provider = EntraAuthProvider()
        with patch(
            "lib.auth.validate_token", return_value={"oid": "u1", "name": "Ada"}
        ):
            user = provider.authenticate_request("Bearer token", None)
        assert user is not None and user.id == "u1"


class TestLegacyMiddlewareMapping:
    """server.py's stdio/streamable-http mode uses EntraAuthMiddleware rather
    than the provider, and mapped an unresolved key to a 500."""

    def _app(self):
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        return Starlette(
            routes=[Route("/protected", lambda r: JSONResponse({"ok": True}))],
            middleware=[Middleware(auth_mod.EntraAuthMiddleware)],
        )

    def _get(self, exc):
        from starlette.testclient import TestClient

        with (
            patch.object(auth_mod, "TENANT_ID", "tenant"),
            patch.object(auth_mod, "CLIENT_ID", "client"),
            patch.object(auth_mod, "validate_token", side_effect=exc),
        ):
            client = TestClient(self._app(), raise_server_exceptions=False)
            return client.get("/protected", headers={"Authorization": "Bearer t"})

    def test_unresolved_kid_is_503_without_a_challenge(self):
        r = self._get(auth_mod.SigningKeyUnavailable("not visible yet"))
        assert r.status_code == 503
        assert r.headers.get("Retry-After") == "5"
        assert "WWW-Authenticate" not in r.headers

    def test_unreachable_issuer_is_503(self):
        r = self._get(PyJWKClientConnectionError("down"))
        assert r.status_code == 503

    def test_hardened_kid_miss_is_401(self):
        r = self._get(jwt.InvalidTokenError('Unable to find a signing key that matches: "x"'))
        assert r.status_code == 401
        assert "WWW-Authenticate" in r.headers
