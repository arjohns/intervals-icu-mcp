"""Tests for the Google sign-in and allowlist used by HTTP deployments."""

import pytest
from fastmcp.server.auth import AccessToken

from intervals_icu_mcp.remote_auth import (
    AllowlistGoogleProvider,
    AllowlistGoogleTokenVerifier,
    AuthConfigError,
    build_auth_from_env,
    parse_allowed_emails,
    unauthenticated_http_allowed,
)

GOOD_ENV = {
    "MCP_AUTH": "google",
    "MCP_BASE_URL": "https://example.run.app/",
    "GOOGLE_OAUTH_CLIENT_ID": "123.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
    "MCP_ALLOWED_EMAILS": "Runner@Example.com, second@example.com",
    "MCP_JWT_SIGNING_KEY": "x" * 48,
}


def _token(email: str | None, verified: object = True) -> AccessToken:
    return AccessToken(
        token="t",
        client_id="sub",
        scopes=["openid"],
        claims={"email": email, "email_verified": verified},
    )


def _verifier() -> AllowlistGoogleTokenVerifier:
    return AllowlistGoogleTokenVerifier(
        allowed_emails=parse_allowed_emails(GOOD_ENV["MCP_ALLOWED_EMAILS"]),
        required_scopes=["openid"],
        audience=GOOD_ENV["GOOGLE_OAUTH_CLIENT_ID"],
    )


def test_parse_allowed_emails_normalizes():
    assert parse_allowed_emails(" A@x.com,,b@X.com ") == {"a@x.com", "b@x.com"}


def test_allowlisted_verified_email_is_admitted():
    tok = _token("runner@example.com")
    assert _verifier().check_allowed(tok) is tok


def test_email_match_is_case_insensitive():
    assert _verifier().check_allowed(_token("RUNNER@example.com")) is not None


@pytest.mark.parametrize("verified", [False, "false", None])
def test_unverified_email_is_rejected(verified):
    assert _verifier().check_allowed(_token("runner@example.com", verified)) is None


def test_string_true_counts_as_verified():
    assert _verifier().check_allowed(_token("runner@example.com", "true")) is not None


def test_other_account_is_rejected():
    assert _verifier().check_allowed(_token("stranger@example.com")) is None


def test_missing_email_is_rejected():
    assert _verifier().check_allowed(_token(None)) is None


def test_empty_allowlist_refuses_to_build():
    with pytest.raises(AuthConfigError):
        AllowlistGoogleTokenVerifier(allowed_emails=frozenset(), required_scopes=["openid"])


def test_no_auth_mode_returns_none():
    assert build_auth_from_env({}) is None


def test_unknown_mode_is_an_error():
    with pytest.raises(AuthConfigError):
        build_auth_from_env({"MCP_AUTH": "basic"})


def test_missing_settings_are_named():
    env = dict(GOOD_ENV)
    del env["MCP_JWT_SIGNING_KEY"]
    with pytest.raises(AuthConfigError, match="MCP_JWT_SIGNING_KEY"):
        build_auth_from_env(env)


def test_google_mode_installs_allowlist_verifier(tmp_path, monkeypatch):
    monkeypatch.setenv("FASTMCP_HOME", str(tmp_path))
    provider = build_auth_from_env(GOOD_ENV)
    assert isinstance(provider, AllowlistGoogleProvider)
    verifier = provider.allowlist_verifier
    assert verifier.allowed_emails == {"runner@example.com", "second@example.com"}
    assert verifier.audience == GOOD_ENV["GOOGLE_OAUTH_CLIENT_ID"]


def test_unauthenticated_http_needs_explicit_opt_in():
    assert unauthenticated_http_allowed({}) is False
    assert unauthenticated_http_allowed({"MCP_ALLOW_UNAUTHENTICATED": "true"}) is False
    assert unauthenticated_http_allowed({"MCP_ALLOW_UNAUTHENTICATED": "1"}) is True


def test_http_without_auth_refuses_to_start(monkeypatch):
    from intervals_icu_mcp import server

    monkeypatch.setattr(server, "_AUTH", None)
    monkeypatch.delenv("MCP_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.setattr("sys.argv", ["intervals-icu-mcp", "--transport", "http"])
    monkeypatch.setattr(server, "_emit_startup_log", lambda: None)
    with pytest.raises(SystemExit, match="Refusing to serve HTTP without sign-in"):
        server.main()
