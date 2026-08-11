"""Route-level auth dependencies.

This module now delegates authentication decisions to an AuthProvider
abstraction (see transport.http.security), so routes are not coupled to a
single API key implementation.
"""

from fastapi import Cookie, Header, HTTPException, status

from transport.http.security import AuthUnavailable, User, get_auth_provider


def _authenticate(authorization: str | None, jc_session: str | None) -> User | None:
    provider = get_auth_provider()
    try:
        return provider.authenticate_request(authorization=authorization, session_token=jc_session)
    except AuthUnavailable as exc:
        # Could not check the credential — retryable, not a rejection.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify credentials right now; retry shortly.",
            headers={"Retry-After": "5"},
        ) from exc


def require_authenticated_user(
    authorization: str | None = Header(default=None),
    jc_session: str | None = Cookie(default=None),
) -> User:
    """Return authenticated User or raise 401.

    Accepts bearer header and browser session cookie. Concrete validation is
    handled by the active AuthProvider.

    A restricted-scope credential (currently only the conference badge) is
    authentic but not authorized here — it gets 403, never 401, because the
    token is fine and re-authenticating would not help.
    """
    user = _authenticate(authorization, jc_session)
    if user and user.scope != "full":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This credential is scoped to '{user.scope}' and cannot access this endpoint.",
        )
    if user:
        return user

    has_candidate = bool((authorization and authorization.strip()) or (jc_session and jc_session.strip()))
    if not has_candidate:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing credentials",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )


def require_badge_client(
    authorization: str | None = Header(default=None),
    jc_session: str | None = Cookie(default=None),
) -> User:
    """Auth for /api/badge/* — accepts a badge-scoped key OR a full credential.

    Full credentials are allowed so the dashboard and curl can exercise the
    same endpoints the badge uses; badge-scoped keys are allowed *only* here.
    """
    user = _authenticate(authorization, jc_session)
    if user:
        return user

    has_candidate = bool((authorization and authorization.strip()) or (jc_session and jc_session.strip()))
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials" if has_candidate else "Missing credentials",
    )


def require_api_key(
    authorization: str | None = Header(default=None),
    jc_session: str | None = Cookie(default=None),
) -> None:
    """Back-compat dependency used across existing routes.

    Routes currently depending on `require_api_key` do not need to change; we
    internally validate through `require_authenticated_user`.
    """
    require_authenticated_user(authorization=authorization, jc_session=jc_session)
