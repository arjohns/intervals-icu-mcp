# Training apps for a Commonplace vault

Three apps that sit on top of this server and a Commonplace vault. Each one is a note in your vault: a method that names no one, then a short settings section with your own details.

| App | What it does | What starts it |
|---|---|---|
| [Morning brief](morning-brief/SKILL.md) | Each morning: Go, Go easy or Rest from last night's recovery, yesterday's sessions against the plan, today's session, weather, calendars. A phone notification and a page, plus a short check-in when the numbers need context, logged for weekly and monthly reviews | A daily scheduled task |
| [After-session](after-session/SKILL.md) | Within about 15 minutes of a session: records it, checks it against the plan, then asks one to three questions about how it felt, chosen for that kind of session | The server's Garmin watcher (optional) |
| [Training ledger](training-ledger/SKILL.md) | The vault's own record of every session, one line each, with totals, so the vault can answer "how many miles this year" without any outside service | After-session, plus a nightly scheduled task |

They are read and run by Claude. Nothing here is code you install; the server is the only thing you deploy.

## What you need

- A **Commonplace vault**, with its connector added in Claude.
- An **intervals.icu** account, linked to your watch's platform with download activities, download wellness and (for Garmin) upload planned workouts turned on.
- A **Google Cloud project** with billing on, and `gcloud` signed in. Running this server costs nothing within Cloud Run's free tier.
- A **Claude** plan with scheduled tasks and Claude Code on the web.
- Optional: a **Garmin Personal API key** (Garmin's Personal tier, pull only, one person's own data). Without it you still get the brief and the ledger from intervals.icu; you lose Body Battery, the after-session conversation, and same-day ledger updates.

About 45 minutes, most of it creating keys.

## Steps

1. **Keys.** From intervals.icu, Settings → Developer: your API key and athlete id. Optionally, your Garmin Personal API key. Store the Garmin key straight into Secret Manager without pasting it anywhere else:

   ```bash
   read -rs K && printf '%s' "$K" | gcloud secrets create garmin-personal-api-key --project "$PROJECT" --data-file=- && unset K
   ```

2. **Deploy the server** and **connect Claude** by following [docs/cloud-run.md](../docs/cloud-run.md): the one-time Google OAuth client, then `deploy.sh`, then the custom connector in Claude. Check it works by asking Claude "what was my last activity?".

3. **Install the apps.** Open a new Claude chat and paste [the setup prompt](setup-prompt.md). Claude asks a few questions, writes the three app notes with your settings, starts your ledger with the last few months, creates your Morning Brief page and the two daily scheduled tasks, and runs the brief once so you can see it.

4. **Optional, with a Garmin key: the after-session conversation.** Create the Code task in [tasks/after-session.md](tasks/after-session.md), give its API trigger to the server (the watcher section of [docs/cloud-run.md](../docs/cloud-run.md)), and re-run `deploy.sh`. The first call only records what already exists, so your next session is the first one it acts on.

## What's in this folder

| Path | What it is |
|---|---|
| `*/SKILL.md` | The three app notes, with blank settings |
| `training-ledger/ledger-month-template.md`, `ledger-index-template.md` | The first month's ledger and the index, before any sessions |
| `morning-brief/page/` | The brief page: `index.html` renders `brief.json`; the sample data is made up |
| `tasks/` | The three scheduled-task prompts, word for word |
| `setup-prompt.md` | The prompt that installs everything |

## Rules the apps keep

- Safety outranks the plan: reported pain above 3 out of 10, illness or a fever means rest, whatever the numbers say.
- They never change your training calendar, Garmin or your calendars. They recommend, and you approve.
- Keys and tokens live only in Secret Manager, never in the vault or a chat.
- Not medical advice.
