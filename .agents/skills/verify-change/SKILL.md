# Skill: verify-change

Write and run a verification script to confirm a feature works end-to-end.

## Pattern

Every task delivery must end with one of:
- **verified** — script ran, all checks passed
- **not-verified** — explain why (e.g. requires live broker session)
- **known-issues** — list them

## Steps

1. **Create `scripts/verify_<feature>.py`**:
   ```python
   #!/usr/bin/env python3
   """Verify: <what this checks>"""
   import json
   import os
   import sys
   from datetime import date

   RESULTS = []

   def check(name: str, passed: bool, detail: str = ''):
       status = 'PASS' if passed else 'FAIL'
       print(f"  [{status}] {name}" + (f" — {detail}" if detail else ''))
       RESULTS.append({'name': name, 'status': status, 'detail': detail})

   def main():
       print(f"verify_<feature>.py\n{'='*40}")

       # --- checks ---
       check("env vars present", bool(os.getenv('PAYTM_API_KEY')))
       # add more checks...

       # --- results ---
       passed = sum(1 for r in RESULTS if r['status'] == 'PASS')
       total  = len(RESULTS)
       print(f"\n{passed}/{total} passed")

       out_dir = os.path.join('testplans', str(date.today()))
       os.makedirs(out_dir, exist_ok=True)
       with open(os.path.join(out_dir, 'results.json'), 'w') as f:
           json.dump({'feature': '<feature>', 'passed': passed, 'total': total, 'checks': RESULTS}, f, indent=2)

       sys.exit(0 if passed == total else 2)

   if __name__ == '__main__':
       main()
   ```

2. **Run it**:
   ```bash
   python scripts/verify_<feature>.py
   ```
   Exit code 0 = all pass. Exit code 2 = failures. Results saved to `testplans/<date>/results.json`.

3. **Report** the outcome in the task delivery message.

## Notes
- For checks requiring a live broker session, mark as **not-verified** and note what to run manually.
- Keep each check atomic — one assertion per `check()` call.
- `testplans/` is gitignored (runtime output).
