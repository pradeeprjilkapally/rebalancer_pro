# Task

<!--
TEMPLATE — keep this comment block as reference. Each task section starts with a
date line, then the fields.

Lifecycle (maintained by Claude):
- COMPLETE  → the whole task section is commented out with "Status: complete
              <date> — <result>", and a fresh dated template is added for the
              next task.
- PENDING   → if Pradeep says to park the task, its Status becomes
              "pending — parked <date>", the section stays VISIBLE (not
              commented), and a fresh template is added below for the next task.
- REVIEW    → at the start of each day/session, Claude shows the current state
              of this file (pending + open tasks) for review.

Date:         when the task was filed
Status:       (leave empty; Claude sets complete/pending)
Task:         <Incremental_Number_First_task_for_day_starts_With_01>-<DDMMYY>
Goal:         the one outcome, in a sentence.
Constraints:  what it must (and must not) do. Stack, perf, style, security.
Inputs:       what the agent starts with. Files, data, an API, an example.
Outputs:      what exists when it's finished. Files, endpoints, behavior.
Done-check:   the concrete test that proves it works.
Out-of-scope: what NOT to touch, so it doesn't wander.
-->
--------------------------------------------------------------------------------------------------
==================================================================================================
MORNING TO-DO — 2026-06-28  (reviewed 2026-06-29)
==================================================================================================

[1] Paytm re-auth — DONE 2026-06-29.
    Verified: `python -m agent.sanity_check --report` shows Tokens freshness OK.

[2] (optional) Fix local DNS so the Mac can resolve trycloudflare.
    Why: router 192.168.0.1 returns NXDOMAIN for *.trycloudflare.com (relay already robust to
         this after PR #7/#8, so this is comfort only).
    How: System Settings → Network → (your Wi-Fi) → DNS → add 1.1.1.1 and 8.8.8.8.

[3] 2026-07-01 — update gold holdings after the SIP.
    How: Paytm → Gold → note new grams total + invested → edit mydata/manual_holdings.json
         (gold.grams + gold.invested).

Reference (no action needed): dashboards are Access-only now (Google OTP, no app password);
pmClient/apiService.py diverges from upstream (re-apply the ConnectionError fix if you ever
re-sync from paytmmoney/pyPMClient). Full chore log lives in action_items.md.
--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-07-02
Status:       complete 2026-07-02 — fix merge-guard gh query to target the fork (--repo); it was hitting origin/upstream → never fired. Shipping-proof: blocks feature/07 (merged PR #24), allows unmerged; suite +1
Task:         09-020726
Goal:         Fix the merge-guard (08-020726): its `gh pr list` omitted --repo, so it queried origin (upstream paytmmoney) instead of the fork and never found merged PRs → never blocked. Caught by shipping proof.
Constraints:  Use GH_REPO (default pradeeprjilkapally/rebalancer_pro), matching sanity_check. Keep fail-open on gh unavailable. Regression test that the gh command carries --repo <fork>. feature→develop→master.
Inputs:       scripts/check_branch_not_merged.py.
Outputs:      --repo _GH_REPO added to the gh query; regression test test_gh_query_targets_the_fork; shipping proof recorded (blocks merged-PR branch, exit 1).
Done-check:   guard exits 1 on a branch with a merged PR (live: feature/07-020726-chit-value → PR #24) and 0 otherwise; suite green.
Out-of-scope: Anything beyond the --repo fix.

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-07-02
Status:       complete 2026-07-02 — pre-push merge-guard blocks pushing to a merged-PR branch (stops the 4×-recurring orphaned-commit bug); discipline documented; suite +4
Task:         08-020726
Goal:         Stop the recurring bug where a follow-up commit is orphaned because its PR merged at an earlier commit — happened 4×. Block, at push time, any push to a branch whose PR is already merged; document the "no follow-up pushes to a merged PR" discipline.
Constraints:  Enforced locally at the exact moment of orphaning (pre-push). Fail OPEN if gh is unavailable/unauthed (never block a legit push on tooling). Only block when a merged PR is positively found. Pure, unit-tested parse logic. feature→develop→master.
Inputs:       scripts/hooks/pre-push, gh CLI, CLAUDE.md/AGENTS.md conventions.
Outputs:      scripts/check_branch_not_merged.py (gh pr list --head <b> --state merged → block) wired as pre-push gate 0; tests; CLAUDE.md/AGENTS.md discipline note (one push per PR, new fix = new branch, merge-self-to-close-race).
Done-check:   guard blocks a push when the branch has a merged PR, allows otherwise; fails open without gh; suite green.
Out-of-scope: Branch protection / required-checks (unavailable on this plan); changing GitHub merge behaviour.

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-07-02
Status:       complete 2026-07-02 — chit value date-based + sip_day-aware (Fable-reviewed off-by-one: current month counts once due day arrives); 2 chits = ₹2.88L+₹32k; own card, out of diversification; suite +9
Task:         07-020726
Goal:         Value chit funds from the real manual_holdings.json schema (monthly_installment + Start_Month), computing months_paid = months since Start_Month (capped at tenure). Keep chits in their own card, out of the diversification layout (like MF).
Constraints:  Formula-string fields (months_paid="Current Month - Start_Month", current_value="months_paid * monthly_installment") are computed, not read literally. Numeric overrides win. months_paid floored at 0, capped at tenure_months. Shared chit_valuation() used by loader + dashboard + FIRE corpus (one source of truth). Chits excluded from the diversification donut/buckets (already true). Rigorous tests. feature→develop→master.
Inputs:       mydata/manual_holdings.json (2 chits, date schema), agent/manual_holdings.py, webhook.py (_build_chit_context), daily_review.py.
Outputs:      manual_holdings.chit_valuation() (Start_Month→months_paid, invested, current_value); loader + _build_chit_context + _manual_corpus_totals all use it; tests (date math, formula-strings, capping, numeric-override, future-start).
Done-check:   Chit 1 (Jan-2025) = 18×16000 = ₹2,88,000; Chit 2 (May-2026) = 2×16000 = ₹32,000; Chit Funds card shows ₹3,20,000, excluded from diversification; suite green.
Out-of-scope: Full chit dividend/discount/drawn-amount model; per-chit dashboard drill-down.

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-07-02
Status:       complete 2026-07-02 — chit funds supported end-to-end (manual_chit source, FIRE corpus, dashboard card); fixed the invalid manual_holdings.json (trailing comma broke MF+gold); suite +4
Task:         06-020726
Goal:         Support self-managed chit funds as a manual holding — loaded from manual_holdings.json, valued, included in the FIRE corpus, shown on the dashboard — mirroring how manual MF is handled. Also fix the invalid JSON (trailing comma) that was breaking all manual holdings.
Constraints:  Chits behave like manual_mf: in the corpus total, NOT in a category bucket, excluded from broker-equity totals and concentration trims. invested = explicit OR monthly_sip×months_paid; current_value = explicit OR invested (no invented values — placeholder shows ₹0 until Pradeep adds months_paid/data). Rigorous tests. Follow the deploy model (feature→develop→master).
Inputs:       mydata/manual_holdings.json (chits array), agent/manual_holdings.py, fire_analyser.py, daily_review.py, rebalancer.py, webhook.py, dashboard_ping.py.
Outputs:      manual_holdings.load() chits loop (source=manual_chit); manual_chit added to every source-exclusion filter; fire_aligned_suggestions gains manual_chit param + corpus term; daily_review _manual_corpus_totals returns 3-tuple; _build_chit_context + Chit Funds dashboard card (shown when value>0); tests. JSON fixed to valid.
Done-check:   manual_holdings.load surfaces a manual_chit holding with invested=monthly×months_paid; explicit values win; FIRE corpus includes it; suite green; dashboard renders.
Out-of-scope: Full chit valuation model (dividend/discount/drawn schedule) — awaiting Pradeep's full data; multiple-chit UI polish.

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-07-02
Status:       complete 2026-07-02 — CI pr-flow guard blocks feature→master; feature/*→develop, develop→master; suite +6 tests
Task:         05-020726
Goal:         Enforce the deploy model's branch flow so a feature branch physically cannot merge straight to master — feature/* → develop → master — after Claude repeatedly PR'd feature→master.
Constraints:  GitHub-side enforcement (a CI check on pull_request that can't be bypassed locally). Pure, unit-tested flow logic. Don't block release/* or unknown patterns. This task itself follows the model: feature → develop → master.
Inputs:       .github/workflows/, the deploy-model convention in CLAUDE.md/AGENTS.md.
Outputs:      scripts/check_pr_flow.py (feature/*→develop, develop→master; else allowed) + .github/workflows/pr-flow.yml (runs it on PRs); tests; CLAUDE.md/AGENTS.md document the enforced flow.
Done-check:   check_pr_flow blocks feature→master (exit 1) and passes feature→develop / develop→master; suite green; workflow runs on pull_request.
Out-of-scope: Branch protection rules (not available on this plan); auto-merging; changing the deploy scripts.

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-07-01
Status:       complete 2026-07-01 — task.md now the total ledger; pre-push guard (check_task_tracked) enforces branch→task mapping; conventions rewritten; history backfilled; suite +6 guard tests
Task:         01-010726
Goal:         Make task.md the single ledger for EVERY repo change (code/config/infra) and every agent/user recommendation, with precise factual context; restrict action_items.md to only tasks the agent genuinely cannot do; enforce it with a guard; backfill the untracked history.
Constraints:  Precise, low-temperature context in every entry (no fluff, no invented values). Rigorous tests per task — no loopholes. task.md holds ALL trackable work; action_items.md ONLY explicit manual-only items (broker login, domain purchase, secret entry). A feature branch must map to a documented task before it can be pushed. Do not weaken the existing pre-push test gate.
Inputs:       CLAUDE.md/AGENTS.md working-conventions, scripts/hooks/pre-push, git history (untracked feat-/fix- commits), task.md.
Outputs:      scripts/check_task_tracked.py (branch→task.md guard) wired into pre-push; CLAUDE.md/AGENTS.md convention rewritten (task.md = everything; action_items = explicit manual-only; rigorous tests; entry-at-start); backfilled complete-status task.md entries for shipped-but-untracked features (Slack migration, CI alerts, cross-agent parity, tunnel fixes); tests for the guard.
Done-check:   check_task_tracked passes for a branch with a documented task and fails for one without; suite green incl. new guard tests; pre-push runs the guard; backfilled entries present; conventions updated in both CLAUDE.md and AGENTS.md.
Out-of-scope: Rewriting historical commits; changing the branch→PR→merge flow; auto-generating task entries without precise context.

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-07-01
Status:       complete 2026-07-02 — deploy pipeline: /dashboard_pp (local-only preview) + scripts/deploy.py (dev/prod) + deploy skill (both dirs) + docs; suite 127
Task:         02-010726
Goal:         Add a staged deploy pipeline so "merged" reliably becomes "live" (the gap that caused stale data): feature/<taskID-goal> → develop → master, with develop previewed on a LOCAL-ONLY dashboard_pp (:5002 worktree) before promoting to the public dashboard_main (:5001, master).
Constraints:  App-specific (rebalancer_pro only). dashboard_pp must be local-only — served by a second webhook on 127.0.0.1:5002 from a `develop` git worktree, which the tunnel never exposes (no relay/Access change). Production (:5001, master, dashboard_main via relay) is unchanged. Preview shares .env/tokens/mydata with prod via symlink (reviewing code, not data). Rigorous tests. Track per the new rule.
Inputs:       agent/webhook.py (/dashboard_bkp route), agent/tunnel_manager.py (exposes :5001 only), launchd, git worktree.
Outputs:      rename /dashboard_bkp → /dashboard_pp; scripts/deploy.py (deploy dev → refresh :5002 develop worktree; deploy prod → pull master + restart :5001 + refresh); deploy skill in both skill dirs; CLAUDE.md/AGENTS.md document the pipeline; tests for deploy helpers + the route rename.
Done-check:   `deploy prod` pulls+restarts :5001 and dashboard_main serves 200; `deploy dev` starts :5002 from the develop worktree and dashboard_pp serves 200 locally only (not via relay); suite green; route renamed.
Out-of-scope: Editing the Cloudflare Worker/relay; CI-based deploys; multi-machine. (Bootstrapping: this first task ships via a direct PR; future tasks follow feature→develop→master.)

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-07-02
Status:       pending — parked 2026-07-02 (Pradeep will take up later today)
Task:         03-020726
Goal:         Python model-router so the workflow can switch models per phase — Opus for planning, Sonnet for building, Haiku for test execution — invoked when needed.
Constraints:  Realistic mechanism: orchestrate via Claude Code sub-agents (Agent tool `model` override) or the Anthropic SDK for a standalone router; document the cold-start/context trade-off; keep rigorous test DESIGN on Sonnet/Opus (Haiku executes, doesn't author edge cases). App-agnostic helper, no secrets logged.
Inputs:       the Agent tool model override, Anthropic SDK, this repo's task flow.
Outputs:      TBD when picked up — a `scripts/model_router.py` and/or a documented sub-agent convention.
Done-check:   TBD.
Out-of-scope: TBD.
(Note: logged in task.md per the convention — it's agent-doable, so not action_items. Flag if you'd rather it in action_items.)

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-07-02
Status:       pending — parked 2026-07-02 (recommended by Claude)
Task:         04-020726
Goal:         Harden the sanity-check token-freshness check to validate REAL broker session validity, not just the token file's mtime — it reported "OK" while the Paytm session was actually expired.
Constraints:  A cheap validity probe (a lightweight authed call) without burning rate limits; fail-open on network blips; no secrets logged. Rigorous tests.
Inputs:       agent/sanity_check.py (check_tokens), agent/auth.py, agent/brokers/zerodha.py.
Outputs:      TBD — a validity check replacing/augmenting the mtime heuristic.
Done-check:   TBD — check flags an expired session even when the token file is recent.
Out-of-scope: TBD.

--------------------------------------------------------------------------------------------------
BACKFILL — shipped work that predated the tracking rule (documented retroactively by 01-010726)
--------------------------------------------------------------------------------------------------

These features shipped with `feat-`/`fix-` commit slugs and no task.md entry at the
time. Recorded here for a complete ledger (all complete; SHAs + tests are facts):

- Slack migration (PR #6, `867a5dd`) — replaced Twilio/WhatsApp with a Slack incoming
  webhook; `notify()` returns True only on HTTP 200 + body `ok` (real delivery, not
  "queued"). Removed all Twilio code/config. Tests: agent notify + webhook suite.
- CI-failure alerts (`a11961a` → Slack in `bf86f57`) — GitHub Action `notify` job posts
  to Slack (via `SLACK_WEBHOOK_URL` secret) on red master CI; `check_ci` daily backstop.
- Deterministic CI + cross-platform runners (`29028b6`, `5b3237c`) — `pytest -m "not live"`,
  conftest network-block, ubuntu+windows matrix; fixed apiService 405 crash (2-arg
  httpx.HTTPError → ConnectionError).
- Tunnel/relay reliability — `2b25391` (PR #7: publish to KV via ha_connections + local
  origin, not a trycloudflare probe) and `ad121f4` (PR #8: URL regex excludes api/update/
  www infra hosts). Fixed recurring relay 530/404.
- Cross-agent parity (`c841ebe`, landed via PR #16) — AGENTS.md ≡ CLAUDE.md; `.claude/skills`
  and `.agents/skills` hold the identical set; documented the keep-in-sync convention.

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-06-30
Status:       complete 2026-06-30 — token monitor + handoff/resume baton built & tested (suite 116); also re-lands the PR#15 tail orphaned by an early merge
Task:         02-300626
Goal:         Claude↔Codex handoff loop: a background monitor estimates Claude's rolling-5h usage and, near the limit, hands the active task to Codex (HANDOFF.md + Slack); when Claude refreshes it hands back (Codex is free-tier, minimise its use). Track everything; test it.
Constraints:  Measurement must run OUTSIDE the Claude session (its own launchd job) so it survives the limit and spends no Claude tokens. The % is an estimate (Anthropic exposes no live plan-% for subscriptions) — count input+output+cache_creation from ~/.claude session logs vs a calibratable ceiling; be explicit it's an estimate. Mirror skills into both .claude/skills and .agents/skills. No secrets logged.
Inputs:       ~/.claude/projects/**/*.jsonl (per-turn usage), agent/notify.py, the cross-agent parity from PR#15.
Outputs:      agent/token_monitor.py (parse/rolling/decide/baton, --report); HANDOFF.md baton (gitignored); handoff+resume skills in both skill dirs; com.pradeep.token-monitor.plist (10-min); CLAUDE_5H_TOKEN_BUDGET + docs in CLAUDE.md/AGENTS.md/.env.example; tests (decide state machine, rolling window, parse, baton) — suite 116.
Done-check:   suite 116 green; `--report` prints rolling usage from real logs; decide() transitions handoff/handback/none correctly; baton written with owner+branch.
Out-of-scope: Self-measuring token% inside the live session (impossible); querying Codex's quota (separate, free-tier); auto-resume across a hard limit (platform-paused — baton picked up on return).

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-06-29
Status:       complete 2026-06-30 — live gold source, MF segregated (own card, out of allocatable diversification), ≥5×/day refresh path + 3×/day ping plist, manual-MF excluded from trims; suite 103 (reviewed + finished from Codex's session)
Task:         01-290626
Goal:         Fix dashboard data correctness: broker snapshots must refresh at least 5 times/day, Paytm Gold must use the existing live-market gold source consistently, and MF allocation treatment must be corrected.
Constraints:  Do not alter broker SDK code. Do not invent portfolio values; trace displayed numbers to persisted JSON/manual holdings/code paths. Keep secrets out of output. Reuse current launchd/Slack setup: dashboard pings stay separate from heavy review suggestions. Notifications must not block the scheduled flow.
Inputs:       Screenshots of /dashboard_main and Paytm app, mydata dashboard JSON/manual holdings, agent/dashboard_ping.py, agent/webhook.py, agent/portfolio.py, agent/daily_review.py, launchd setup.
Outputs:      A lightweight broker snapshot refresh path used by schedules at least 5 times/day; dashboard_ping reads encrypted refreshed snapshots; Paytm Gold valuation uses the chosen existing live-market source rather than stale/manual price; diversification/FIRE logic treats ICICI Multi-Asset MF correctly instead of double-counting or forcing an arbitrary bucket.
Done-check:   Dashboard stock values refresh from Paytm/Zerodha without waiting days; Paytm Gold value is calculated from the selected live source; MF current value is included in corpus, and allocation buckets/targets sum coherently; tests or verification script prove the aggregation math.
Out-of-scope: Visual redesign, trade execution, changing real holdings manually without confirmation.

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-06-28
Status:       complete 2026-06-28 — token alerts now @-tag + carry a tappable mobile login link; hourly alert flood fixed (cooldown + dedup); suite 96
Task:         01-280628
Goal:         When a Paytm/Zerodha token is needed, Slack-tag Pradeep with a tappable login link so he can re-auth from his phone (no laptop). Stop the hourly sanity check from flooding Slack + action_items with the same persistent alert.
Constraints:  Tag via SLACK_USER_ID (fallback <!channel>). Login URL built offline (no session). Alert the SAME failure set at most once per 12h; a changed set or a fresh auto-merge alerts immediately. action_items rows deduped (one per issue, no date in label). No secrets logged.
Inputs:       agent/notify.py, agent/sanity_check.py, .env.example, CLAUDE.md.
Outputs:      notify.py: `_mention()` + `notify(tag=…)` + tagged link-bearing `notify_auth_needed`; sanity_check.py: `_broker_login_url()` (paytm/zerodha offline URL), `_alert_suppressed()` 12h cooldown, deduped `_append_action_item`, token-issue → tagged login link; SLACK_USER_ID documented; collapsed 11 duplicate ledger rows → 1.
Done-check:   suite 96 green; `_broker_login_url` returns valid login URLs offline; cooldown suppresses repeat identical alerts; ledger dedups.
Out-of-scope: Named-tunnel migration (waiting on the free domain); auto-resetting tokens (broker login is interactive by design).

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-06-27
Status:       complete 2026-06-27 — sanity-check auto-fixer now auto-merges to master after a green test gate; suite green
Task:         03-270627
Goal:         Let the hourly sanity check keep the app up unattended — auto-fixable infra/code failures get fixed AND merged to master (not just a PR), so no manual merge is needed at 3 AM. Scoped to sanity checks only; regular work still goes via PR + review.
Constraints:  Merge ONLY if the deterministic suite (`pytest -m "not live"`) passes first (branch protection isn't available on this plan, so the test run is the gate). Always announce the merged PR on Slack (reviewable/revertible). Never auto-merge feature/regular work. Keep the 6h cooldown. No AI attribution in auto-fix commits.
Inputs:       agent/sanity_check.py (`_invoke_claude` prompt + Slack wording), CLAUDE.md (project + global).
Outputs:      _invoke_claude now instructs: fix → test → branch → push → PR → (if green) `gh pr merge --squash --delete-branch`; Slack says "Auto-fixed & merged"; project CLAUDE.md documents the opt-in; global CLAUDE.md nuanced to allow project opt-in while staying PR-only by default.
Done-check:   suite green; next real infra incident merges its own fix + posts the merged PR to Slack.
Out-of-scope: Named-tunnel migration (blocked on a domain); auto-merging regular task work.

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-06-27
Status:       complete 2026-06-27 — hourly health monitor + on-demand `monitor` skill + auto-fix cooldown; suite 93 passed, --report verified live
Task:         02-270627
Goal:         Turn the daily sanity check into an hourly health monitor (app/webhook, tunnel+relay, dashboard exposure, GitHub CI, tokens, Slack) that auto-fixes infra/code issues via `claude -p` → PR → Slack, without burning tokens when healthy.
Constraints:  Detection must cost zero tokens (plain Python on launchd). Claude only on real auto-fixable failures, and NOT re-invoked every hour for a persistent issue (cooldown). No hourly Slack noise from non-health items. Keep the PR-not-merge human gate.
Inputs:       agent/sanity_check.py, ~/Library/LaunchAgents/com.pradeep.sanity-check.plist, .claude/skills/.
Outputs:      sanity_check.py: `--report` read-only mode + auto-fix cooldown (_AUTOFIX_COOLDOWN_HOURS) + removed non-health 'Open tasks' check; launchd switched 7AM→hourly (StartInterval 3600); new `.claude/skills/monitor` skill; tests for cooldown + report.
Done-check:   `python -m agent.sanity_check --report` lists 9 health checks read-only (no Slack/fix); cooldown blocks re-invocation within window; deterministic suite green; hourly launchd job loaded.
Out-of-scope: An autonomous hourly *Claude* loop (rejected — token cost); auto-merging PRs; new notification channels.

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-06-27
Status:       complete 2026-06-27 — Basic Auth removed; exposure guard added + verified (relay 302 = not exposed); suite 90 passed
Task:         01-270627
Goal:         Drop the second dashboard auth layer (HTTP Basic Auth) now that Cloudflare Access (Google + email OTP) gates the dashboards, and add a sanity-check guard that alerts if the dashboard ever becomes publicly reachable.
Constraints:  Single sign-on (Access only) for dashboards; no app-level password to maintain. Machine paths (/callback, /paytm_callback, /health) stay Access-bypassed. Exposure guard must fail open on network blips (only a confirmed public 200 trips it). Security headers stay.
Inputs:       agent/webhook.py (require_auth + _DASH_USER/_DASH_PASS), agent/sanity_check.py, tests/agent/.
Outputs:      webhook.py: removed require_auth/_auth_ok/_DASH_* + hmac/functools imports + 4 @require_auth decorators; sanity_check.py: check_dashboard_exposure() (relay /dashboard_main must NOT be 200) in CHECKS + _HUMAN_REQUIRED; tests updated (test_webhook.py, test_sanity_dashboard_exposure.py); .env.example + CLAUDE.md updated.
Done-check:   deterministic suite 90 passed; check_dashboard_exposure() returns OK against live relay (302); /dashboard_main serves 200 at app layer (Access gates at edge).
Out-of-scope: Cloudflare Access dashboard config, tunnel/relay, notification channel.

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-06-25
Status:       complete 2026-06-25 — verify-before-publish + metrics-based watchdog; relay 200, chain green
Task:         01-250625
Goal:         Stop the morning sanity check failing on a dead tunnel URL — never publish an unverified URL to KV, and detect edge-disconnection fast via cloudflared metrics instead of flaky public DNS.
Constraints:  Only touch agent/tunnel_manager.py. Quick-tunnel architecture stays. No secrets logged. Watchdog must not false-kill a healthy tunnel on a local-DNS blip.
Inputs:       agent/tunnel_manager.py, scripts/verify_tunnel.py, live logs in ~/Library/Logs/rebalancer/
Outputs:      tunnel_manager.py: pinned --metrics port; _ha_connections() liveness; verify-before-publish to .tunnel_url + KV.
Done-check:   launchctl kickstart reloads tunnel job on new code; live log shows "Active URL"/"KV updated" only after reachable; python -m scripts.verify_tunnel → PASS.
Out-of-scope: Cloudflare Worker (relay) source, named-tunnel migration, daily_review/webhook logic.

<!-- Status: complete 2026-06-19 — split working, plists registered, both WhatsApp messages confirmed

Date:         2026-06-18
Status:       complete 2026-06-19
Task:         01-180626
Goal:         Split daily portfolio review into two separate WhatsApp messages — Paytm Money at 7:45 AM and Zerodha at 8:00 AM.
Constraints:  Each broker review must be fully independent. No shared state between runs. Secrets never logged.
Inputs:       agent/daily_review.py (single combined run), existing launchd plist at 8 AM
Outputs:      daily_review.py with --broker flag; com.pradeep.paytm-daily-review.plist (7:45 AM); com.pradeep.zerodha-daily-review.plist (8:00 AM)
Done-check:   launchctl list shows both plists loaded; python3 -m agent.daily_review --broker paytm and --broker zerodha run without error.
Out-of-scope: Portfolio analysis logic, FIRE calculations, WhatsApp message content.
-->

<!-- Status: complete 2026-06-19 — headless mode sends WhatsApp ping instead of crashing; /paytm_callback auto-exchanges token

Date:         2026-06-19
Status:       complete 2026-06-19
Task:         02-190626
Goal:         Fix Paytm Money headless auth — EOFError crash when launchd job can't call input(); add /paytm_callback OAuth route for automatic token exchange.
Constraints:  Request token must never be logged. Token exchange must happen in the callback, not deferred. Graceful fallback if Paytm API is down.
Inputs:       agent/auth.py (crashing on input()), agent/webhook.py (Zerodha callback only)
Outputs:      auth.py detects headless via sys.stdin.isatty(); webhook.py /paytm_callback route; whatsapp.py send_paytm_auth_required()
Done-check:   Run daily_review --broker paytm from launchd context (no TTY) → WhatsApp ping sent, no crash. POST /paytm_callback with valid token → tokens saved, sentinel cleared.
Out-of-scope: Zerodha auth flow, FIRE analysis, WhatsApp formatting.
-->

<!-- Status: complete 2026-06-19 — full interactive flow E2E verified on live WhatsApp; all state transitions confirmed

Date:         2026-06-19
Status:       complete 2026-06-19
Task:         03-190626
Goal:         Replace raw YES/NO text replies with Twilio quick-reply buttons and a conversation state machine covering auth ping → skip → add input → done loop.
Constraints:  Max 3 buttons per message (WhatsApp limit). State must persist across webhook restarts (file-backed). No secrets in state file. Single TwiML response per inbound message (no dual-message conflicts). Twilio signature validated against permanent relay URL.
Inputs:       agent/webhook.py (text YES/NO only), agent/whatsapp.py (plain text auth messages), Twilio Content API
Outputs:
  - 3 Twilio Content Templates (auth_ping, post_skip, continue_done) — SIDs in .env
  - agent/conversation.py — state machine (idle/auth_pending/post_skip/awaiting_input)
  - agent/whatsapp.py — send_auth_ping(), send_post_skip_prompt(), send_interactive()
  - agent/webhook.py — full state machine handler; Twilio sig validated against WORKERS_RELAY_URL
  - agent/auth_reminder.py — 9 AM launchd job checks both sentinels, sends combined nudge
  - com.pradeep.auth-reminder.plist — registered and loaded
Done-check:   E2E live test: auth ping → Skip Today → Add Input → type query → Done. All state transitions observed in watcher. Note saved to mydata/whatsapp_notes.txt.
Out-of-scope: Answering portfolio queries from WhatsApp input (future task). Paytm Money redirect URL setup in developer console (one-time manual step).
-->

<!-- Status: complete 2026-06-19 — tunnel auto-restarts on crash, re-captures URL, KV updated immediately

Date:         2026-06-19
Status:       complete 2026-06-19
Task:         04-190626
Goal:         Fix tunnel_manager.py crash-loop — cloudflared was dying and restarting with a new URL that never updated KV, breaking the Workers relay.
Constraints:  Must never hard-code a tunnel URL. Must handle URL changes on reconnect. KV update must be idempotent.
Inputs:       agent/tunnel_manager.py (captured URL once, never re-captured on reconnect)
Outputs:      tunnel_manager.py with outer restart loop and per-line URL re-detection; KV updated on every URL change.
Done-check:   curl https://portfolio-relay.pradeeprjilkapally.workers.dev/health returns {"status":"ok"} after tunnel restart.
Out-of-scope: Switching to a named Cloudflare tunnel (future, requires paid plan).
-->

<!-- Status: complete 2026-06-23 — all 3 root causes fixed; Paytm + Zerodha authenticated live on real WhatsApp

Date:         2026-06-22
Status:       complete 2026-06-23
Task:         01-220626
Goal:         no response to my pings from whatsapp. Fix all the broken connections
Constraints:  Whenever I respond to morning 7:45 or 8 AM messages, there should be a response.
Done-check:   Pradeep taps buttons on real WhatsApp and gets a response — end to end on the live device

Root causes fixed:
  1. QUIC NAT timeout — cloudflared forced to --protocol http2 (TCP); QUIC idle-dropped by router after ~2h
  2. No health watchdog — tunnel_manager now kills dead cloudflared within 4 min; previously took 11+ hours
  3. Paytm requestToken mismatch — /paytm_callback looked for request_token (snake) but Paytm sends requestToken (camelCase); every auth attempt returned 400 silently since day 1
Also: send_auth_links split into per-broker messages; auth_reminder sends separate pings per broker
Verified: Pradeep authenticated Paytm + Zerodha live on WhatsApp 2026-06-23 10:31 IST; tokens confirmed written
-->

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

<!-- Status: complete 2026-06-23 — /dashboard live (200, all sections verified); WhatsApp condensed to 6 lines with relay link; JSON written alongside txt on each review run

Date:         2026-06-23
Status:       complete 2026-06-23
Task:         01-230626
Goal:         Add a /dashboard web route showing both broker portfolios in a clean HTML table, and condense the WhatsApp morning message to a 5-line summary + dashboard link.
Constraints:  Dashboard reads structured JSON written by daily_review.py — no text parsing. Mobile-first HTML. No external CDNs. WhatsApp message must fit without scrolling (≤10 lines). Dashboard URL uses the permanent Workers relay.
Inputs:       agent/daily_review.py (_write_file, _format_whatsapp), agent/webhook.py (Flask app)
Outputs:      mydata/{broker}_data.json written alongside the txt; /dashboard Flask route in webhook.py; condensed _format_whatsapp() in daily_review.py
Done-check:   curl localhost:5001/dashboard returns 200 with both broker sections visible; WhatsApp message is ≤10 lines with dashboard link.
Out-of-scope: Stitch redesign (future), auth flow changes, FIRE calculation logic.
-->

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

<!-- Status: complete 2026-06-23 — preflight.py built; validate_all() passes on live tokens; daily_review reports session state before any auth trigger

Date:         2026-06-23
Status:       complete 2026-06-23
Task:         02-230626
Goal:         Add a pre-flight validation step that silently tests Paytm + Zerodha sessions and tunnel health before triggering any auth prompt — never ask for auth unless the silent test actually fails.
Constraints:  Validation must be silent (no user-facing output unless a check fails). Must not trigger headless auth flow or send WhatsApp. Only report what's broken. Tunnel check included.
Inputs:       agent/auth.py (setup_session), agent/brokers/zerodha.py (get_kite_client), agent/sanity_check.py (check_relay, check_tunnel_direct)
Outputs:      agent/preflight.py — validate_all() returns {paytm, zerodha, tunnel} status dict; agent/daily_review.py updated to call preflight before data fetch.
Done-check:   Running preflight with valid tokens returns all-ok with no auth prompts. Running with expired tokens reports exactly which broker needs auth and why.
Out-of-scope: Fixing MCP kitemcp session (separate tool, separate auth path), UI changes.
-->

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

<!-- Status: complete 2026-06-23 — Gold live in dashboard (₹10,005, manual badge); MF placeholder ready; portfolio total now ₹76,794

Date:         2026-06-23
Status:       complete 2026-06-23
Task:         03-230626
Goal:         Add manual holdings support (MF + Gold) — read mydata/manual_holdings.json, fetch live MF NAV from mfapi.in, derive gold price from Gold Bees ETF, merge into portfolio snapshot and dashboard.
Constraints:  mfapi.in is public/free — no auth needed. Gold price derived from Gold Bees LTP already in snapshot — no extra API. Manual file is gitignored (personal data). Holdings show a [manual] badge in dashboard. No changes to pmClient SDK.
Inputs:       agent/portfolio.py (build_snapshot), agent/webhook.py (dashboard), mydata/ dir
Outputs:      agent/manual_holdings.py; mydata/manual_holdings.json (template); portfolio.py updated; dashboard shows manual holdings with badge
Done-check:   With manual_holdings.json populated, daily review prints manual MF + gold holdings; dashboard shows them alongside Paytm/Zerodha data.
Out-of-scope: CAMS CAS parsing, MF Central API, Zerodha Coin SIP setup.
-->

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

<!-- Status: complete 2026-06-23 — IBJA-sourced 24K rate (₹14,479/g); dashboard gold section live with stats, 30-day SVG chart, 7-day colour-coded table; corrected from bogus Gold Bees proxy to real IBJA rates.

Date:         2026-06-23
Status:       complete 2026-06-23
Task:         04-230626
Goal:         Live Paytm Gold tracking — IBJA 24K rate, 79-day seeded history, dashboard gold section with invested/current/grams/P&L + SVG trend + 7-day table.
Verified:     IBJA ₹14,479/g; portfolio value ₹80,186; P&L -2.85%; 30-day chart SVG; 7-day table with colour-coded changes; Paytm markup note displayed.
-->
