---
name: deploy
description: >-
  Triggered when Pradeep types "deploy" (or "deploy dev" / "deploy prod"). Runs the
  rebalancer_pro deploy pipeline so a merge actually goes live. `deploy dev` refreshes
  the local-only preview (dashboard_pp on :5002 from the develop worktree) for review;
  `deploy prod` pulls master, restarts the production webhook (:5001), refreshes data,
  and verifies dashboard_main. Closes the "merged ≠ live" gap that caused stale data.
---

# Deploy — make a merge actually go live

Pipeline (app-specific): `feature/<taskID-goal>` → `develop` → `master`.

- **develop** is previewed on **dashboard_pp** — a second webhook on `127.0.0.1:5002`
  running a `develop` git worktree. It is **local-only** (the tunnel targets :5001, and
  `/dashboard_pp` rejects any request carrying Cloudflare headers).
- **master** is production on **:5001** → **dashboard_main**, public via the relay+Access.

## Commands

```bash
python scripts/deploy.py dev     # preview develop on :5002/dashboard_pp (local only)
python scripts/deploy.py prod    # pull master, restart :5001, verify dashboard_main
```

- **`deploy dev`** — updates the develop worktree, (re)starts the preview webhook on
  :5002, refreshes broker snapshots, prints `dashboard_pp -> 200`. Review at
  `http://127.0.0.1:5002/dashboard_pp` (local only).
- **`deploy prod`** — checks out + pulls master, kickstarts `com.pradeep.zerodha-webhook`
  (:5001), refreshes snapshots, verifies `dashboard_main -> 200`.

## When to run

- After merging a feature branch **to develop** → `deploy dev`, then tell Pradeep to
  review dashboard_pp before he promotes develop → master.
- After Pradeep merges **develop → master** → `deploy prod` so dashboard_main reflects it.
- **Always verify:** report the real HTTP status the script prints; "deployed" needs the
  200, not an assumption. If prod verify isn't 200, the production webhook is still on old
  code — investigate, don't claim done.

## Notes

- The preview shares `.env` / tokens / `mydata` with production via symlink (you're
  reviewing code, not data). Broker refresh only works while the broker's token is valid.
- rebalancer_pro-specific. Mirror any change to this skill into `.agents/skills/deploy`.
