# Deploying to Google Cloud Run with Google sign-in

This fork adds what the upstream server lacked for remote use: a sign-in step.
Clients such as Claude reach the server through OAuth. Google proves who the
caller is, and the server then admits only the accounts in `MCP_ALLOWED_EMAILS`.
Without that list, any Google account could complete the sign-in.

Cost: within Cloud Run's free tier for one person's use. The service scales to
zero when idle and runs at most one instance.

## What gets created

| Resource | Purpose |
|---|---|
| Cloud Run service `intervals-mcp` | The server, at `https://intervals-mcp-<project-number>.<region>.run.app` |
| Service account `intervals-mcp-run` | Runs the service; can read only its three secrets and write its state bucket |
| Secret `intervals-icu-api-key` | Your Intervals.icu API key |
| Secret `intervals-mcp-google-oauth-client-secret` | The Google OAuth client secret |
| Secret `intervals-mcp-jwt-signing-key` | Generated. Signs the server's own tokens and encrypts its stored OAuth state. Keep it stable: rotating it signs every client out |
| Bucket `<project>-intervals-mcp-state` | Encrypted OAuth client registrations and sessions, mounted at `/data`, so a restart doesn't sign you out |

The Cloud Run service is public at the network level (`--allow-unauthenticated`)
because Claude cannot present Google Cloud IAM credentials. The application
enforces sign-in instead: every MCP request without a valid token gets `401`,
and the deploy script checks for that at the end.

## One-time: a Google OAuth client

1. In the Google Cloud console for your project, open **APIs & Services → OAuth consent screen**.
   Choose **External**, give it a name (e.g. "intervals-icu-mcp"), and add your email as the
   support and developer contact. Only the `openid` and `email` scopes are used, so no Google
   verification review is needed.
2. Set the publishing status to **In production**. In **Testing** mode Google expires refresh
   tokens after 7 days, which would make Claude ask you to reconnect every week.
3. Open **APIs & Services → Credentials → Create credentials → OAuth client ID**.
   Type: **Web application**. Authorized redirect URI:
   `https://intervals-mcp-<project-number>.<region>.run.app/auth/callback`
   (the deploy script prints the exact value before it deploys anything).
4. Keep the client ID handy. The script asks for the client secret at a hidden prompt.

## Deploy

```bash
PROJECT=my-project ALLOWED_EMAILS=me@example.com ./deploy/cloud-run/deploy.sh
```

It asks for your Intervals.icu athlete ID and the OAuth client ID, and for any secret that
does not exist yet. Re-running it is safe and is also how you ship an update.

## Connect Claude

In Claude: **Settings → Connectors → Add custom connector**, URL
`https://intervals-mcp-<project-number>.<region>.run.app/mcp`. Choose Connect,
approve on the consent page, pick your Google account, done.

## Settings reference

| Variable | Meaning |
|---|---|
| `MCP_AUTH` | `google` turns sign-in on. Unset: HTTP transports refuse to start |
| `MCP_ALLOW_UNAUTHENTICATED` | `1` lets HTTP start without sign-in, only for use behind your own authenticating proxy |
| `MCP_BASE_URL` | Public URL of the service |
| `MCP_ALLOWED_EMAILS` | Comma-separated Google accounts allowed in (case-insensitive, must be verified) |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | The OAuth client above |
| `MCP_JWT_SIGNING_KEY` | Long random secret, stable across restarts |
| `FASTMCP_HOME` | Where OAuth state is kept; `/data/fastmcp` on the mounted bucket |
| `INTERVALS_ICU_API_KEY` / `INTERVALS_ICU_ATHLETE_ID` | Your Intervals.icu credentials |
| `INTERVALS_ICU_DELETE_MODE` | `safe` (default), `full` or `none`, as upstream |
