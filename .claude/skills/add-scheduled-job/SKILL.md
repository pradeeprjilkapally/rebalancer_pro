# Skill: add-scheduled-job

Add a new scheduled job to the rebalancer_pro agent.

## Pattern

All scheduled jobs run via macOS **launchd**. Each job calls a Python module entry point.
Job logic lives in `agent/daily_review.py` or a new module — never inline in a plist.

## Steps

1. **Write the job function** in the relevant `agent/*.py` module:
   ```python
   def run_my_job():
       try:
           # job logic here
           print("[cron] my_job: done")
       except Exception as e:
           print(f"[cron] my_job: failed — {e}")
   ```
   - Wrap the entire body in `try/except Exception`.
   - Prefix all log lines with `[cron] <job_name>:`.
   - Comment IST→UTC conversion on every schedule: `# 9:00 AM IST = 03:30 UTC`.

2. **Add an entry point** (if new file):
   ```python
   if __name__ == '__main__':
       run_my_job()
   ```

3. **Create a launchd plist** at `~/Library/LaunchAgents/com.rebalancer.<jobname>.plist`:
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
       <key>Label</key>
       <string>com.rebalancer.<jobname></string>
       <key>ProgramArguments</key>
       <array>
           <string>/usr/bin/python3</string>
           <string>-m</string>
           <string>agent.<module></string>
       </array>
       <key>WorkingDirectory</key>
       <string>/Users/pradeepreddyjilkapally/Documents/Pradeep/claude_repo/pyPMClient</string>
       <key>StartCalendarInterval</key>
       <dict>
           <key>Hour</key>
           <integer>2</integer>   <!-- UTC; comment IST equivalent -->
           <key>Minute</key>
           <integer>15</integer>
       </dict>
       <key>StandardOutPath</key>
       <string>/Users/pradeepreddyjilkapally/Documents/Pradeep/claude_repo/pyPMClient/logs/<jobname>.log</string>
       <key>StandardErrorPath</key>
       <string>/Users/pradeepreddyjilkapally/Documents/Pradeep/claude_repo/pyPMClient/logs/<jobname>.err</string>
       <key>EnvironmentVariables</key>
       <dict>
           <key>PATH</key>
           <string>/usr/local/bin:/usr/bin:/bin</string>
       </dict>
   </dict>
   </plist>
   ```

4. **Load the job**:
   ```bash
   launchctl load ~/Library/LaunchAgents/com.rebalancer.<jobname>.plist
   ```

5. **Update CLAUDE.md** — add a row to the Scheduled Jobs table with IST and UTC times.

## Existing jobs

| Job | IST | UTC | Module |
|---|---|---|---|
| Paytm daily review | 7:45 AM | 02:15 | `agent.daily_review --broker paytm` |
| Zerodha daily review | 8:00 AM | 02:30 | `agent.daily_review --broker zerodha` |
