---
name: archive-jobs
description: Archive job tracker entries older than 60 days by soft-archiving them in the local DB. Runs on the 1st of every month. Sends a summary email after archiving.
argument-hint: "(no arguments required)"
---

Archive jobs older than 60 days from the active job tracker, then send a summary email to {notify_email}.

## Step 0 — Load the profile

Read `config/profile.md`. Every `{placeholder}` below is a key in its front
matter.

If that file does not exist, stop and tell the user to run
`cp config/profile.example.md config/profile.md` and fill it in. Do not guess a
name, address or document ID — a wrong address here sends real mail to a
stranger.

---

## Step 1 — Archive old jobs

Call `mcp__job_tracker__archive_old_jobs` with default settings (days=60).

The tool will:
- Find all non-archived jobs where Date Added is more than 60 days ago
- Mark them `archived` in the local DB (soft-delete — they stay in the DB but drop out of normal listings/the GUI)
- Return the count and list of archived companies

---

## Step 2 — Send summary email

Use `mcp__gmail_personal__send_email` with:
- `to`: `{notify_email}`
- `subject`: `Job Tracker — Monthly Archive Complete ([Month Year])`
- `body`: the summary below

```
Hi {owner_first_name},

The monthly job tracker cleanup ran on [today's date].

──────────────────────────────
ARCHIVE SUMMARY
──────────────────────────────

Jobs archived: [count]
Threshold: 60 days old

Companies archived:
[bulleted list of company names, or "None — no jobs met the threshold." if count is 0]

──────────────────────────────

These jobs are still in the tracker DB, just hidden from active listings (the GUI and normal MCP queries) going forward.

Claude
```

---

## Step 3 — Confirm

Report back:
- How many jobs were archived
- Which companies were archived
- Whether the summary email was sent
