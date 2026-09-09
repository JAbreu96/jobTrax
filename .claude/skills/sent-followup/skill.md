---
name: sent-followup
description: Scan the {outreach_email} sent folder for outreach and interview emails with no reply in 7+ days, check follow-up count via Gmail, draft follow-ups (max 2 per thread), and log dates to the local job tracker DB.
argument-hint: "[days=7]"
---

Scan the sent folder for emails that haven't received a reply in `$ARGUMENTS` days (default: 7), then draft follow-ups. Cap at 2 follow-ups per thread. Log follow-up dates to the job tracker.

## Step 0 — Load the profile

Read `config/profile.md`. Every `{placeholder}` below is a key in its front
matter.

If that file does not exist, stop and tell the user to run
`cp config/profile.example.md config/profile.md` and fill it in. Do not guess a
name, address or document ID — a wrong address here sends real mail to a
stranger.

---

## Step 1 — Find sent emails in the follow-up window

Use `mcp__gmail_personal__search_emails` with query:
```
in:sent older_than:{days}d newer_than:30d -to:{notify_email}
```

Where `{days}` is the argument passed (default: 7).

For each result, collect:
- `id` — message ID
- `threadId` — thread ID
- `subject` — email subject
- `to` — recipient email address(es)
- `date` — sent date
- `snippet` — preview of body

Deduplicate by `threadId` — keep only the **original sent email** per thread (earliest message, not the most recent Re:).

**Skip immediately:**
- Threads where the subject already starts with `Re:` — these are follow-ups, not originals
- Emails to any `@gmail.com` address
- Subjects containing: `Reminder`, `Digest`, `Archive`, `Summary`, `Complete`

---

## Step 2 — Filter out threads that already have a reply

For each unique thread from Step 2, check for an inbound reply:

Use `mcp__gmail_personal__search_emails` with:
```
from:{recipient_email} newer_than:30d
```

If any result shares the same `threadId` as the sent email → **skip it** (reply received).

If no matching inbound message found → keep the thread as a candidate.

---

## Step 3 — Check follow-up count (Gmail source of truth)

For each candidate thread, count how many follow-ups have already been sent by searching:

```
in:sent subject:"Re: {original_subject}" to:{recipient_email}
```

- Count the results → this is `followup_count`
- **If `followup_count >= 2`**: skip this thread. Log it in the final report as "Max follow-ups reached."
- **If `followup_count < 2`**: continue to Step 5

This ensures the 2-follow-up cap is enforced from Gmail itself, regardless of what's in the tracker.

---

## Step 4 — Categorize each eligible thread

Classify each remaining thread as one of two types:

**Interview** — subject or snippet contains any of:
`interview`, `offer`, `onsite`, `phone screen`, `technical screen`, `hiring`, `next steps`, `thank you for`, `thanks for meeting`, `following up on our`

**Outreach** — everything else (default)

---

## Step 5 — Draft follow-up emails

For each eligible thread, draft an appropriate follow-up.

### Parsing contact info
- Extract the recipient's **first name** from the `to` field (e.g. `Dana <dana@example.com>` → Dana; if only an email, use the part before `@`)
- Infer the **company name** from the email domain (e.g. `@doorlist.app` → Doorlist, `@sony.com` → Sony) or from the original subject

---

### Outreach follow-up

Keep under 80 words. Casual, warm, zero pressure.

```
Subject: Re: [original subject]

Hi [first name],

Just wanted to follow up on my earlier note. If you ever have a few minutes to connect about [Company] and what you're working on, I'd love to chat.

Hope things are going well!

{owner_name}
{outreach_email}
{linkedin_url}
```

**Rules:**
- Do NOT mention job hunting, referrals, urgency, or timelines
- Do NOT restate your background — that's in the original email
- Keep it human — this should read like a genuine person, not a template

---

### Interview follow-up

Keep under 100 words. Professional but warm — not pushy.

```
Subject: Re: [original subject]

Hi [first name],

I wanted to follow up and reiterate my interest in the opportunity at [Company]. I enjoyed our conversation and remain excited about the direction of the work.

Please don't hesitate to reach out if there's any additional information I can provide or if there's an update on timing — I'm happy to be flexible.

Thanks,
{owner_name}
{outreach_email}
{linkedin_url}
```

**Rules:**
- Use "our conversation" only if an interview actually took place — otherwise say "my application"
- Do NOT mention competing offers, deadlines, or urgency

---

### Saving drafts

For each thread, call `mcp__gmail_personal__draft_email` with:
- `to`: the original recipient email
- `subject`: `Re: [original subject]`
- `body`: the follow-up text from the template above

---

## Step 6 — Log follow-up dates to the tracker

After saving each draft, record today's date in the local job tracker DB.

Run the following Python snippet, replacing `{Company}` and `{today}` with actual values:

```python
import sys
sys.path.insert(0, '.')
from src.jobs_db import update_followup_log

try:
    updated = update_followup_log("{Company}", "{today}")
    print(f"Tracker updated: {updated}")
except ValueError as e:
    print(f"Skipped (cap reached): {e}")
except RuntimeError as e:
    print(f"Tracker DB unavailable: {e}")
```

- `update_followup_log` enforces the 2-follow-up cap and returns the new log string (e.g. `2026-07-05, 2026-07-12`)
- If it raises `ValueError`, the cap was already reached — skip this thread and log it in the report
- If the company isn't found in the tracker at all, note it in the report as "not in tracker."

---

## Step 7 — Report back

After all drafts are saved, report:

```
Sent Follow-Up Drafts — [Today's Date]
──────────────────────────────────────
[N] draft(s) saved to {outreach_email}

OUTREACH FOLLOW-UPS ([n]):
• [First Name] @ [Company] — originally sent [X] days ago | follow-up #[1 or 2] | tracker updated

INTERVIEW FOLLOW-UPS ([n]):
• [First Name] @ [Company] — originally sent [X] days ago | follow-up #[1 or 2] | tracker updated

SKIPPED — already replied ([n]):
• [First Name] @ [Company]

SKIPPED — max follow-ups reached ([n]):
• [First Name] @ [Company] — [N] follow-ups already sent

SKIPPED — not in tracker ([n]):
• [First Name] @ [Company] — draft saved, tracker not updated
──────────────────────────────────────
```

If no eligible threads are found:
> No unreplied sent emails found in the follow-up window — nothing to draft.
