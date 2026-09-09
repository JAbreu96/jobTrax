---
name: follow-up-reminder
description: Scan the job tracker for applications with no status progression in 7+ days, send a follow-up nudge email, and draft low-pressure follow-up emails for any outreach with no reply. Run on a schedule or on-demand.
argument-hint: "[days=7]"
---

Scan the job tracker for stale applications and send a follow-up reminder email to {notify_email}. For jobs where outreach was already sent, also draft a low-pressure follow-up email per contact.

## Step 0 — Load the profile

Read `config/profile.md`. Every `{placeholder}` below is a key in its front
matter.

If that file does not exist, stop and tell the user to run
`cp config/profile.example.md config/profile.md` and fill it in. Do not guess a
name, address or document ID — a wrong address here sends real mail to a
stranger.

---

## Step 1 — Find jobs needing follow-up

Call `mcp__job_tracker__list_jobs_needing_followup` with `days=7` (or the value passed as an argument).

This returns jobs where:
- `date_applied` is set
- `status` is still `Applied` (no progression)
- `date_applied` was more than `days` days ago

---

## Step 2 — Split by outreach status

For each job returned, check whether `outreach_date` is set:

- **Has outreach** (`outreach_date` is set): note the contact info from the `contacts` field (may include name and/or email). These will get a drafted follow-up email in Step 3.
- **No outreach** (`outreach_date` is blank): flag these for the reminder email only.

---

## Step 3 — Draft follow-up emails for outreach with no reply

For each job in the "has outreach" group, draft a short, low-pressure follow-up email.

### Parsing contact info
The `contacts` field may be a name, a name + email (e.g. `Jane Doe <jane@company.com>`), or just an email. Extract whatever is available. If no email is present, skip drafting for that job and note it in the final report.

### Email template

Keep it under 80 words. Warm, casual, zero pressure — this is a "just circling back" nudge, not a sales pitch.

```
Subject: Re: Quick intro — {owner_name}

Hi [contact first name],

Just wanted to follow up on my earlier note. If you ever have a few minutes to connect about [Company] and what you're working on, I'd love to chat.

Hope things are going well!

{owner_name}
{outreach_email}
{linkedin_url}
```

- Personalize `[Company]` with the actual company name.
- If a role was noted, you can optionally reference it naturally (e.g. "the [Role] role at [Company]") but keep it light.
- Do NOT mention job hunting, referrals, or urgency.
- Do NOT mention Meta or any employer in the subject line.

### Saving drafts

For each contact with a valid email, call `mcp__gmail_personal__draft_email` with:
- `to`: contact's email address
- `subject`: `Re: Quick intro — {owner_name}`
- `body`: the follow-up email from the template above

---

## Step 4 — Compose the reminder email

```
Subject: Follow-Up Reminder — [X] Applications Need Attention ([Today's Date])

Hi {owner_first_name},

You have [X] application(s) with no status update in the last [days] days.

──────────────────────────────
APPLICATIONS NEEDING FOLLOW-UP
──────────────────────────────

[For each job, one line:]
• [Company] — [Title] | Applied: [date_applied] ([N] days ago) | Outreach: [outreach_date or "None"]

──────────────────────────────

[If any outreach follow-ups were drafted:]
Follow-up drafts created for: [Company1], [Company2], ...
Check your Gmail drafts ({outreach_email}) to review and send.

[If no outreach follow-ups:]
No outreach follow-ups were needed.

Consider sending a follow-up note to your contact or checking the company's applicant portal.

[If no jobs found:]
No stale applications found — you're all caught up.
──────────────────────────────

Claude
```

---

## Step 5 — Send the reminder email

Use `mcp__gmail_personal__send_email` with:
- `to`: `{notify_email}`
- `subject`: `Follow-Up Reminder — [X] Applications Need Attention ([Today's Date])`
- `body`: the email from Step 4

Skip sending if no stale jobs were found — just report back that everything is current.

---

## Step 6 — Confirm

Report back:
- How many stale applications were found
- Which companies were listed
- How many follow-up drafts were created (and for which companies)
- Whether the reminder email was sent
