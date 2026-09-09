---
name: application-digest
description: Check Gmail for job application updates in the last 24 hours, match them to tracked jobs in the local job tracker DB, and send a digest email to the user. Run this on a schedule or on-demand.
argument-hint: "(no arguments required)"
---

Check Gmail for job application update emails from the last 24 hours, cross-reference them with the job tracker, and send a digest to {notify_email}.

## Step 0 — Load the profile

Read `config/profile.md`. Every `{placeholder}` below is a key in its front
matter.

If that file does not exist, stop and tell the user to run
`cp config/profile.example.md config/profile.md` and fill it in. Do not guess a
name, address or document ID — a wrong address here sends real mail to a
stranger.

---

## Step 1 — Pull tracked companies from the job tracker

Call `mcp__job_tracker__list_all_jobs` and extract the list of company names. You'll use these to match against emails found in Step 2.

---

## Step 2 — Search Gmail for application-related emails

Use `mcp__gmail_personal__search_emails` with this query to find relevant emails from the last 24 hours:

```
(subject:(interview OR offer OR "next steps" OR "application" OR "your application" OR "we reviewed" OR "moving forward" OR "unfortunately" OR "not moving forward" OR "thank you for applying" OR "hiring" OR "recruiter" OR "screening" OR "assessment" OR "take-home") newer_than:1d)
```

For each result, use `mcp__gmail_personal__read_email` to get the full content of the email thread.

---

## Step 3 — Categorize and match each email

For each email found, determine:

**Category** (pick the best fit):
- `Interview Invite` — they want to schedule a call or interview
- `Offer` — compensation, offer letter, or next steps toward offer
- `Rejection` — not moving forward, position filled, not a fit
- `Application Received` — auto-confirm that application was received
- `Recruiter Outreach` — cold recruiter reach out about a new role
- `Follow-up Needed` — they asked for something (availability, documents, etc.)
- `Other Update` — anything application-related that doesn't fit above

**Company match:** Check if the sender domain or email body mentions any company from the job tracker list (Step 1). If matched, note the company name. If no match, label as `Unknown / New`.

---

## Step 3b — Update the job tracker status

For each email that matched a tracked company, call `mcp__job_tracker__update_job_status` to write the new status to the tracker.

Map email category → Status value:
| Email Category | Status |
|---|---|
| `Interview Invite` | `Phone Screen` (if first interview) or `Technical` / `Behavioral` based on context |
| `Offer` | `Offer` |
| `Rejection` | `Rejected` |
| `Application Received` | `Applied` |
| `Follow-up Needed` | leave status unchanged |
| `Recruiter Outreach` | leave status unchanged |
| `Other Update` | leave status unchanged |

Only update if the new status represents a **forward progression** — do not downgrade (e.g., don't set `Applied` if status is already `Phone Screen`).

Skip companies labeled `Unknown / New` — no tracker row to update.

---

## Step 4 — Compose the digest

Write a clean digest email. Format:

```
Subject: Job Application Digest — [Today's Date]

Hi {owner_first_name},

Here's your application update digest for the last 24 hours.

──────────────────────────────
UPDATES (X emails found)
──────────────────────────────

[For each email, one block:]

Company: [Company name or "Unknown / New"]
Category: [Category from Step 3]
From: [Sender name & email]
Summary: [1–2 sentence summary of what the email says and any action needed]

──────────────────────────────

[If no emails found:]
No application-related emails found in the last 24 hours.
──────────────────────────────

Stay on it,
Claude
```

If there are action items (e.g., schedule an interview, submit documents), call them out explicitly at the top of the digest under an **ACTION NEEDED** section before the full list.

---

## Step 5 — Send the digest email

Use `mcp__gmail_personal__send_email` with:
- `to`: `{notify_email}`
- `subject`: `Job Application Digest — [Today's Date]`
- `body`: the digest from Step 4

---

## Step 6 — Confirm

Report back:
- How many emails were found and categorized
- How many matched tracked companies
- Which jobs had their status updated (company → new status)
- Whether the digest was sent successfully
- Any action items surfaced
