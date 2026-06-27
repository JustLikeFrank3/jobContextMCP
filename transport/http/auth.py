"""Route-level auth dependencies.

This module now delegates authentication decisions to an AuthProvider
abstraction (see transport.http.security), so routes are not coupled to a
single API key implementation.
"""

from fastapi import Cookie, Header, HTTPException, status

from transport.http.security import User, get_auth_provider


def require_authenticated_user(
    authorization: str | None = Header(default=None),
    jc_session: str | None = Cookie(default=None),
) -> User:
    """Return authenticated User or raise 401.

    Accepts bearer header and browser session cookie. Concrete validation is
    handled by the active AuthProvider.
    """
    provider = get_auth_provider()
    user = provider.authenticate_request(authorization=authorization, session_token=jc_session)
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


def require_api_key(
    authorization: str | None = Header(default=None),
    jc_session: str | None = Cookie(default=None),
) -> None:
    """Back-compat dependency used across existing routes.

    Routes currently depending on `require_api_key` do not need to change; we
    internally validate through `require_authenticated_user`.
    """
    require_authenticated_user(authorization=authorization, jc_session=jc_session)
