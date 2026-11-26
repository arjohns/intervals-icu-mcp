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
| Service account `intervals-mcp-run` | Runs the service; can read only its own secrets and write its state bucket |
| Secret `intervals-icu-api-key` | Your Intervals.icu API key |
| Secret `intervals-mcp-google-oauth-client-secret` | The Google OAuth client secret |
| Secret `intervals-mcp-jwt-signing-key` | Generated. Signs the server's own tokens and encrypts its stored OAuth state. Keep it stable: rotating it signs every client out |
| Secret `garmin-personal-api-key` (optional) | A Garmin Connect Personal API key. Not created by the script; if you create it, the script grants access and the `garmin_*` tools turn on. Keys expire after the period you chose (at most a year): add a new secret version and redeploy |
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
| `GARMIN_PERSONAL_API_KEY` | Optional. From the `garmin-personal-api-key` secret when it exists; turns on the `garmin_*` tools |

## Optional: start a Claude task when Garmin has a new activity

Garmin's Personal API is pull-only, so the server checks instead of waiting to be told. With the watcher on, a Cloud Scheduler job calls `POST /internal/garmin-watch` every 15 minutes from 6:00 to 22:45 (New York time by default). Each call asks Garmin for activities from the last two days. When one is new, the server fires a Claude scheduled task through its API trigger, passing only the new activity ids, start times, types and names. The task then does the work: ledger, plan check, page and notification. An activity is marked seen only after the fire succeeds, so a failed fire is retried on the next call. The first call only records what already exists, so turning the watcher on never replays old activities. The seen ids live in `/data/garmin-watch/state.json` on the state bucket.

To turn it on:

1. Create the Claude scheduled task, then add an **API** trigger to it at [claude.ai/code/routines](https://claude.ai/code/routines). Copy the **Fire URL**, then click **Generate token** and copy the token, which is shown only once.
2. Store both values in Secret Manager without pasting them anywhere else:

   ```bash
   read -rs U && printf '%s' "$U" | gcloud secrets create claude-after-session-fire-url --project "$PROJECT" --data-file=- && unset U
   read -rs T && printf '%s' "$T" | gcloud secrets create claude-after-session-fire-token --project "$PROJECT" --data-file=- && unset T
   ```

3. Re-run `deploy.sh`. It finds both secrets, generates the route's own key (`intervals-mcp-garmin-watch-key`), passes everything to the service, and creates or updates the scheduler job `intervals-mcp-garmin-watch`. Set `WATCH_SCHEDULE` and `WATCH_TIME_ZONE` to change when it runs.

The route refuses any call without the right `X-Watch-Key` header. The key is also stored in the scheduler job's settings, where anyone with access to the project can read it. To rotate the Claude token, regenerate it on claude.ai, add it as a new secret version, and redeploy. To turn the watcher off, delete the scheduler job, or delete either Claude secret and redeploy.

| Setting | Meaning |
|---|---|
| `GARMIN_WATCH_KEY` | The key the scheduler sends as `X-Watch-Key` |
| `CLAUDE_FIRE_URL`, `CLAUDE_FIRE_TOKEN` | The Claude scheduled task's API trigger |
| `GARMIN_WATCH_STATE_FILE` | Where the seen activity ids are kept |
