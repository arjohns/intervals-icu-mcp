"""Sign-in for remote (HTTP) deployments.

The upstream server has no authentication of its own, so an HTTP deployment
must not be reachable by anyone who finds the URL. This module puts Google
sign-in in front of it, through FastMCP's OAuth proxy, and then admits only
the Google accounts listed in ``MCP_ALLOWED_EMAILS``.

Why an allowlist on top of Google sign-in: Google's OAuth proves *who* the
caller is, not that they may use this server. Any Google account can complete
the sign-in, so without the allowlist the server would be open to all of them.

Environment variables (all required when ``MCP_AUTH=google``):

- ``MCP_AUTH``: ``google`` to enable sign-in. Unset means no auth, which is
  only allowed for stdio, or for HTTP when ``MCP_ALLOW_UNAUTHENTICATED=1``.
- ``MCP_BASE_URL``: the public URL of the service, e.g.
  ``https://intervals-mcp-abc123-uc.a.run.app``.
- ``GOOGLE_OAUTH_CLIENT_ID`` / ``GOOGLE_OAUTH_CLIENT_SECRET``: a Google
  OAuth client of type "Web application" whose authorized redirect URI is
  ``<MCP_BASE_URL>/auth/callback``.
- ``MCP_ALLOWED_EMAILS``: comma-separated Google account emails allowed in.
- ``MCP_JWT_SIGNING_KEY``: a long random secret. It signs the tokens this
  server issues and encrypts its stored OAuth state, so it must stay the same
  across restarts and instances, or every client has to sign in again.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from fastmcp.server.auth import AccessToken, AuthProvider
from fastmcp.server.auth.providers.google import GoogleProvider, GoogleTokenVerifier

logger = logging.getLogger(__name__)

_REQUIRED = (
    "MCP_BASE_URL",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "MCP_ALLOWED_EMAILS",
    "MCP_JWT_SIGNING_KEY",
)


class AuthConfigError(RuntimeError):
    """Raised when remote auth is requested but misconfigured."""


def parse_allowed_emails(raw: str) -> frozenset[str]:
    """Split a comma-separated list into normalized (lowercased) emails."""
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


class AllowlistGoogleTokenVerifier(GoogleTokenVerifier):
    """Google token verifier that also requires a verified, allowlisted email."""

    def __init__(
        self,
        *,
        allowed_emails: frozenset[str],
        required_scopes: list[str] | None = None,
        audience: str | list[str] | None = None,
    ) -> None:
        super().__init__(required_scopes=required_scopes, audience=audience)
        if not allowed_emails:
            raise AuthConfigError("MCP_ALLOWED_EMAILS is empty; nobody could sign in.")
        self.allowed_emails = allowed_emails

    async def verify_token(self, token: str) -> AccessToken | None:
        access_token = await super().verify_token(token)
        if access_token is None:
            return None
        return self.check_allowed(access_token)

    def check_allowed(self, access_token: AccessToken) -> AccessToken | None:
        """Return the token only if its email is verified and on the allowlist."""
        claims = access_token.claims or {}
        email = (claims.get("email") or "").strip().lower()
        verified = claims.get("email_verified")
        if isinstance(verified, str):
            verified = verified.lower() == "true"
        if not email or not verified:
            logger.warning("Rejected sign-in: token carries no verified email")
            return None
        if email not in self.allowed_emails:
            logger.warning("Rejected sign-in: account is not on the allowlist")
            return None
        return access_token


class AllowlistGoogleProvider(GoogleProvider):
    """GoogleProvider whose token check also enforces the email allowlist."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        base_url: str,
        jwt_signing_key: str,
        allowed_emails: frozenset[str],
    ) -> None:
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            base_url=base_url,
            required_scopes=["openid", "email"],
            jwt_signing_key=jwt_signing_key,
            extra_authorize_params={"prompt": "select_account consent"},
        )
        # Replace the stock verifier with the allowlisting one, configured the
        # same way GoogleProvider configures its own: same (normalized) scopes,
        # audience pinned to this OAuth client.
        self._token_validator = AllowlistGoogleTokenVerifier(
            allowed_emails=allowed_emails,
            required_scopes=self._token_validator.required_scopes,
            audience=client_id,
        )

    @property
    def allowlist_verifier(self) -> AllowlistGoogleTokenVerifier:
        verifier = self._token_validator
        assert isinstance(verifier, AllowlistGoogleTokenVerifier)
        return verifier


def build_auth_from_env(env: Mapping[str, str] | None = None) -> AuthProvider | None:
    """Build the auth provider named by ``MCP_AUTH``, or return None when unset."""
    env = os.environ if env is None else env
    mode = (env.get("MCP_AUTH") or "").strip().lower()
    if not mode:
        return None
    if mode != "google":
        raise AuthConfigError(f"Unsupported MCP_AUTH value: {mode!r}. Use 'google'.")

    missing = [name for name in _REQUIRED if not (env.get(name) or "").strip()]
    if missing:
        raise AuthConfigError(f"MCP_AUTH=google needs: {', '.join(missing)}")

    return AllowlistGoogleProvider(
        client_id=env["GOOGLE_OAUTH_CLIENT_ID"].strip(),
        client_secret=env["GOOGLE_OAUTH_CLIENT_SECRET"].strip(),
        base_url=env["MCP_BASE_URL"].strip().rstrip("/"),
        jwt_signing_key=env["MCP_JWT_SIGNING_KEY"].strip(),
        allowed_emails=parse_allowed_emails(env["MCP_ALLOWED_EMAILS"]),
    )


def unauthenticated_http_allowed(env: Mapping[str, str] | None = None) -> bool:
    """True only when the operator explicitly opted out of auth for HTTP."""
    env = os.environ if env is None else env
    return (env.get("MCP_ALLOW_UNAUTHENTICATED") or "").strip() == "1"
