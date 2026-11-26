# Roadmap

What this fork plans beyond keeping the upstream server alive. Upkeep runs on a
schedule (see *Maintenance*); enhancements are picked from this list one at a time.

## Maintenance (recurring)

- **Weekly:** Dependabot opens dependency PRs (Python via uv, GitHub Actions, Docker base
  image). Security updates are merged first; each PR must pass the test workflow.
- **Monthly (1st of the month):** a maintenance review: merge or close pending dependency
  PRs, check FastMCP and Intervals.icu API changes for anything breaking, run the full test
  suite, redeploy with `deploy/cloud-run/deploy.sh`, and confirm `/health` and the 401 on
  `/mcp`.
- **Monthly, dependency watch:** this server depends on Intervals.icu, which depends on
  its Garmin partnership. Check Intervals.icu pricing and free-tier terms, its Garmin sync
  status, API deprecations, and the scope of Garmin's Personal API (especially any move to
  allow workout push to individuals), and the Garmin Personal API key's expiry date (keys last
  at most a year; Garmin emails a week ahead).
- **Quarterly:** review Cloud Run logs for rejected sign-ins and errors, and confirm
  the OAuth consent screen is still "In production".

## Enhancements (pick one at a time)

1. **Deploy on merge.** GitHub Actions → Cloud Run with Workload Identity Federation (no
   stored keys), so a merged PR ships without a manual `deploy.sh` run.
2. **Running tools.** Threshold-pace zone calculator; checkpoint tracking (test results vs
   targets over a season); weekly-mileage ramp check (flag >10% jumps).
3. **Course and route analysis.** GPX elevation profile per mile, grade distribution, and
   matching a training route's climbs against a race course.
4. **Workout builder.** Turn a plain-language session ("3×2 mi at HMP, 3 min jog") into an
   Intervals.icu structured workout with pace targets in min/mi.
5. **Multi-user.** Per-user Intervals.icu OAuth instead of one API key, so others can use a
   hosted instance safely.

## Done

- 2026-11-25 — Garmin watcher: an optional route, `POST /internal/garmin-watch`, called by Cloud Scheduler every 15 minutes. When Garmin has a new activity, it fires a Claude scheduled task through that task's API trigger, so the vault and the morning brief update after a session without being asked. See docs/cloud-run.md.

- 2026-11-24 — Direct Garmin read path: 28 read-only `garmin_*` tools over Garmin's
  Connect Personal API, on when `GARMIN_PERSONAL_API_KEY` is set. Covers every endpoint in
  the Personal API reference, so activities and health data stay readable without
  Intervals.icu. Workout push still needs Intervals.icu (the Training API is business-tier).

- 2026-11-23 — Google sign-in with email allowlist; HTTP refuses to start without auth;
  Cloud Run deployment script and guide.
