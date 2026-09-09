#!/bin/bash

# launchd starts jobs with a minimal environment, so PATH is rebuilt here.
# Derive HOME and the repo root rather than hard-coding them, so this runs for
# any user and survives the repo being relocated (e.g. out of ~/Documents,
# which macOS TCC blocks launchd from reading).
: "${HOME:=$(cd ~ && pwd)}"
export HOME
# The Claude CLI resolves its stored credentials through USER. Strip it and the
# CLI reports "Not logged in - please run /login", which sends you hunting for
# an auth problem that does not exist. launchd does supply USER, so this is a
# guard rather than a fix -- but the failure it prevents is a badly misleading
# one, and the cost is two lines.
: "${USER:=$(id -un)}"
export USER
# pyenv's interpreter goes first because it is the only one with the `mcp`
# package. A bare `python3` under launchd's PATH resolves to
# /usr/local/opt/python@3.10/bin/python3.10, which does not have it, so the
# job_tracker server in .mcp.json dies on import and simply never registers.
# Nothing announces that: the run continues, falls back to writing the tracker
# through src.jobs_db, and quietly loses find_job_for_email's fuzzy matching.
# Interactive shells resolve python3 via pyenv shims and were always fine,
# which is exactly why this stayed invisible.
PYENV_BIN="$HOME/.pyenv/versions/3.10.3/bin"
export PATH="$PYENV_BIN:$HOME/.nvm/versions/node/v18.20.4/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LOG_DIR="$HOME/Library/Logs/inbox-triage"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

echo "=== inbox-triage run: $(date) ===" >> "$LOG_FILE"

# Fail loudly on a pyenv upgrade rather than silently degrading again.
if [ ! -x "$PYENV_BIN/python3" ]; then
  echo "=== FAILED: $PYENV_BIN/python3 is missing (pyenv version changed?) ===" >> "$LOG_FILE"
  exit 1
fi

# Where this run's output begins. The log is per-day and there are now three
# scheduled runs, so the failure check below must look only at our own lines --
# grepping the whole file would inherit an earlier run's error.
run_start=$(wc -l < "$LOG_FILE")

# No send_email on purpose: triage reports to this log, never to the inbox
# it exists to keep quiet. Bash is needed for the watermark read/write and for
# the predicates in src/triage_rules.py.
#
# gmail_alt is the secondary inbox (LinkedIn). Read tools only -- no
# draft_email -- until the user decides which address replies to those threads.
# gtasks__update is for appending [SUPERSEDED ...] notes; there is deliberately
# no gtasks__delete or completion path, so triage can never destroy work.
# Pin the model rather than inheriting it. Without this the scheduled run uses
# whatever model was last chosen interactively, so typing /model in a terminal
# silently changes what the cron job does -- which is how all five scheduled
# jobs came to be pointed at Opus by an unrelated `/model opus`.
#
# The full name, not the `sonnet` alias: the alias tracks the latest Sonnet and
# would reintroduce the same drift this line exists to stop.
#
# Sonnet is enough here because the error-prone half of triage is not model
# judgement any more. Rejection, ask and sign-off detection, subject
# normalisation and quoted-chain stripping all live in src/triage_rules.py
# behind tests, and the Simplify labels route the rejection path. What is left
# is following a long, prescriptive spec.
claude -p "/inbox-triage" \
  --mcp-config .mcp.json \
  --strict-mcp-config \
  --model claude-sonnet-5 \
  --allowedTools "mcp__gmail_personal__search_emails,mcp__gmail_personal__draft_email,mcp__gmail_alt__search_emails,mcp__job_tracker__find_job_for_email,mcp__job_tracker__update_job_status,mcp__job_tracker__update_notes,mcp__job_tracker__add_job,mcp__job_tracker__record_recruiter_outreach,mcp__job_tracker__record_recruiter_reply,mcp__job_tracker__list_recruiters,mcp__job_tracker__list_all_jobs,mcp__gtasks__list,mcp__gtasks__list_task_lists,mcp__gtasks__create,mcp__gtasks__update,Bash" \
  >> "$LOG_FILE" 2>&1

status=$?

# "Your computer went to sleep mid-response" exits 0 -- the CLI reports the
# interruption in its output, not its status code. Checking only $? is how an
# aborted run came to be logged as "done".
if [ "$status" -ne 0 ] || tail -n +$((run_start + 1)) "$LOG_FILE" | grep -q "API Error"; then
  echo "=== FAILED (exit $status) ===" >> "$LOG_FILE"
else
  echo "=== done ===" >> "$LOG_FILE"
fi
