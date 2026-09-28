#!/bin/bash

# Daily ApplyPass import: capture the new Job Applied pages in Chrome, then run
# the importer. Unlike every other scheduled job this one cannot run in the
# cloud -- the capture drives the user's own Chrome, logged in to ApplyPass, via
# the Claude in Chrome extension. So it runs at 09:30, when the Mac is actually
# on, and inbox-triage's morning run sits after it at 10:00 so that rejections
# for yesterday's applications find their rows.

# launchd starts jobs with a minimal environment, so PATH is rebuilt here.
# See run-inbox-triage.sh for why each of these lines exists.
: "${HOME:=$(cd ~ && pwd)}"
export HOME
: "${USER:=$(id -un)}"
export USER
PYENV_BIN="$HOME/.pyenv/versions/3.10.3/bin"
export PATH="$PYENV_BIN:$HOME/.nvm/versions/node/v18.20.4/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LOG_DIR="$HOME/Library/Logs/applypass-inbound"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

# Nobody watches this run, and a failure here is silent in the worst way: the
# tracker just stops growing and triage starts missing rejections. A banner is
# the cheapest way to make that visible. Only failures and skips raise one.
notify() {
  osascript -e "display notification \"$1\" with title \"ApplyPass import\"" \
    >/dev/null 2>&1 || true
}

echo "=== applypass-inbound run: $(date) ===" >> "$LOG_FILE"

if [ ! -x "$PYENV_BIN/python3" ]; then
  echo "=== FAILED: $PYENV_BIN/python3 is missing (pyenv version changed?) ===" >> "$LOG_FILE"
  notify "Failed: pyenv Python is missing. See $LOG_FILE"
  exit 1
fi

# Without a running Chrome the model would spend a whole run discovering that
# the browser tools cannot connect. A missed day is not lost: the capture's
# cutoff comes from the tracker, not from the last run, so the next run reaches
# back further on its own.
if ! pgrep -xq "Google Chrome"; then
  echo "=== SKIPPED: Chrome is not running; the next run will catch up ===" >> "$LOG_FILE"
  notify "Skipped: Chrome was not running. The next run will catch up."
  exit 0
fi

run_start=$(wc -l < "$LOG_FILE")

# The prompt grants what the skill otherwise asks for, because nobody is there
# to answer: the download and the Turso write. Everything else -- the backup,
# the row-delta check, stopping on anything unexpected -- is the skill's own,
# in its "Unattended runs" section.
#
# Chrome tools are listed one by one rather than by wildcard. This run opens a
# tab, reads and clicks it, and runs the capture script; form_input,
# file_upload and the rest have no business in an unattended session holding a
# logged-in browser.
#
# Sonnet pinned by full name for the reason run-inbox-triage.sh gives.
claude -p "/applypass-inbound This is the unattended daily run. Follow the skill's 'Unattended runs' section: capture incrementally in Chrome from Step 0 using the --cutoff date, then import. You are pre-authorized to download the capture to ~/Downloads, move it into the inbox, and run the import with --write --clear after the backup. End your report with exactly one line: RESULT: imported <n> new, <m> updated -- or RESULT: stopped: <reason>." \
  --chrome \
  --mcp-config .mcp.json \
  --strict-mcp-config \
  --model claude-sonnet-5 \
  --allowedTools "mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__tabs_close_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__find,mcp__claude-in-chrome__javascript_tool,Read,Bash" \
  >> "$LOG_FILE" 2>&1

status=$?
run_output=$(tail -n +$((run_start + 1)) "$LOG_FILE")

# Same two-part check as inbox-triage -- a run interrupted by sleep exits 0 and
# reports the interruption in its output -- plus the skill's own verdict, since
# a run that stopped short on purpose also exits 0.
if [ "$status" -ne 0 ] || grep -q "API Error" <<<"$run_output"; then
  echo "=== FAILED (exit $status) ===" >> "$LOG_FILE"
  notify "Failed (exit $status). See $LOG_FILE"
elif grep -q "^RESULT: stopped" <<<"$run_output"; then
  echo "=== STOPPED ===" >> "$LOG_FILE"
  notify "$(grep -m1 '^RESULT: stopped' <<<"$run_output" | cut -c9- | cut -c1-120)"
elif ! grep -q "^RESULT: imported" <<<"$run_output"; then
  echo "=== FAILED: no RESULT line ===" >> "$LOG_FILE"
  notify "Failed: the run ended without a result. See $LOG_FILE"
else
  echo "=== done ===" >> "$LOG_FILE"
fi
