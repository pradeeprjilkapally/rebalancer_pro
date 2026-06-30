---
name: review-gate
description: >-
  Run before shipping, deploying, merging, or claiming a change is done.
  A sequential quality gate — diff review, goal alignment, evaluation pass,
  no-slop review, then shipping proof — executed in order, where nothing ships
  that skips a line. Enforces the rule "never claim done without proof":
  "deployed" or "done" must be backed by same-session evidence (curl against a
  live URL, a production screenshot, or a fresh log line).
---

# Review Gate & Shipping

When work moves faster, the volume of lower-quality output rises with it. This
gate is the quality filter that runs before anything reaches a user. **Nothing
ships that skips a line.**

## The gate (in order)

Run these sequentially; a failure at any stage stops the gate.

1. **Diff review** — The change is small enough to actually review. If it is
   sprawling, split it before going further.
2. **Goal alignment** — The stated objective matches what the diff actually
   changes. No silent drift, no smuggled scope.
3. **Evaluation pass** — The test/eval suite runs and succeeds. Report real
   output; a failure here is a stop, not a footnote.
4. **No-slop review** — Run the [[no-slop]] checklist over the changed files;
   it finds no unexplained issues.
5. **Shipping proof** — Human-verifiable evidence that the live surface actually
   changed.

## Never claim done without proof

"Deployed" requires verification produced in the **same session**, by one of:

- `curl` against the live URL,
- a screenshot of the running/production surface, or
- a fresh log line from the live system.

If you cannot point to proof, you ran a command and hoped. That is not done.

## Proof template

Define the proof criteria *before* shipping, then capture the evidence:

```bash
# 1. Inspect what is shipping
git status
git diff --stat

# 2. Prove it passes
<test command>          # e.g. pytest / npm test / make test

# 3. Ship
<deploy/push command>

# 4. Prove it is live (capture this output — it is the evidence)
curl -s -o /dev/null -w '%{http_code}\n' <live-url>
# or: grep the fresh log line / attach the production screenshot
```

## Done means

One change shipped, with concrete evidence — screenshot, curl output, or log
extract — confirming the live deployment, attached in the same message that
claims completion.
