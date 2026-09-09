---
owner_name: Jane Doe

# Where digests, reminders and archive summaries are SENT to you.
notify_email: you@example.com

# The mailbox you apply and send outreach FROM. Drafts land here.
outreach_email: you.apply@example.com

# Every address that is you. `src/triage_rules.is_from_owner()` matches on these,
# and a thread whose newest message is from one of them means you spoke last.
# Missing one makes inbox-triage re-surface threads you already answered, which
# reads as a triage bug rather than a config gap.
owner_emails:
  - you@example.com
  - you.apply@example.com

# Optional plus-alias that your second inbox forwards into. Gmail rewrites the
# envelope on forward, so inbox-triage filters on this rather than on the source
# address. Leave blank if you do not use the forwarding path.
linkedin_forward_email: ""

linkedin_url: linkedin.com/in/your-handle

# Optional Google Sheet mirror of the tracker. Blank means local database only;
# the sheet-backed scripts refuse to run rather than guess.
spreadsheet_id: ""
sheet_worksheet: Sheet1

# Google Doc holding your resume, and the Drive folder tailored copies land in.
# Both must be shared with your service account's client_email.
resume_doc_id: ""
resume_folder_id: ""

# NYS DOL WS-5 work-search record. Blank ws5_record_start disables the backfill.
# Only relevant if you claim New York unemployment.
ws5_record_start: ""
ws5_output_dir: ~/Desktop/WS5_work_search_records
---

# Profile

Copy this file to `config/profile.md` and fill it in. That copy is gitignored, so
your details stay out of the repo and an upstream pull never conflicts with them.

Two readers share this file: `src/config.py` parses the front matter above, and
the skills in `.claude/skills/` read the prose below. Keep both in sync by
editing here rather than in either consumer.

## Sender background

<!-- outreach-email reads this section. Lead with your strongest, most recent
     role; the skill will not invent anything you leave out. -->

**Current/recent role:** Software Engineer at Example Corp, 2024 - present

**Highlights (lead with these, in priority order):**

- Accomplished X, as measured by Y, by doing Z
- Accomplished X, as measured by Y, by doing Z

**Additional background:**

- Prior Co (2022-2024): what you did there

## Candidate profile (for scoring)

<!-- source-jobs reads this to score postings against you. The numeric scoring
     rules stay in that skill -- those are policy, not identity. -->

- **Stack:** React, TypeScript, Python
- **Experience:** ~2 years; target roles asking for 0-3
- **Strengths:** what you want to be matched on
- **Location:** City, ST

## Tone

<!-- Optional. One or two lines on how outreach should read. -->

Warm, direct, no more than five sentences. Never claim a mutual connection that
is not there.
