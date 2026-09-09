---
name: work-search-record
description: Fill out the NYS DOL WS-5 Work Search Record for any closed week that does not have one yet. Reads Gmail for job application confirmations, appends them to the evidence file, generates the filled PDF, and emails a summary. Runs daily as a backfill, or on-demand.
argument-hint: "(optional) week-ending Sunday as YYYY-MM-DD; defaults to the week that just closed"
---

Fill out the New York State DOL **WS-5 Work Search Record** for the week that just ended, using Gmail application confirmations as evidence.

## Step 0 — Load the profile

Read `config/profile.md`. Every `{placeholder}` below is a key in its front
matter.

If that file does not exist, stop and tell the user to run
`cp config/profile.example.md config/profile.md` and fill it in. Do not guess a
name, address or document ID — a wrong address here sends real mail to a
stranger.

## Why accuracy matters here

This is a government benefits form. It states that DOL **"will check the information on the form with the contacts listed"** and that knowingly false statements **constitute fraud**. Two hard rules:

1. **Never invent an entry.** Only list applications backed by a real confirmation email or a tracker row showing actual contact.
2. **Never pad a short week.** NYS requires 3 activities/week. If a week has fewer, report it as short — do not top it up to reach 3.

---

## Step 0 — Find which weeks need a form

This runs **daily**, not just on Sunday, so most runs have nothing to do.

```bash
cd scripts/ws5
python3 build_ws5.py --list-missing
```

This prints the week-ending Sundays that have closed but have no PDF yet, one per line.

- **If the output is empty: stop here.** Do not send an email, do not report anything. The run is a no-op.
- Otherwise you have a list of `WEEK_END` dates. **Run Steps 1–5 once per week in that list**, oldest first, then send a single email in Step 6.

If the user passed a date argument, skip this step and use that date instead (it must be a Sunday).

### Idempotency

**The presence of `WS5_week_ending_<date>.pdf` is the marker that a week is done.** A week is generated exactly once, so running twice in a day does nothing the second time. This is what lets the daily schedule backfill a laptop that was closed for weeks without duplicating work or re-emailing.

---

## Step 1 — Determine the week window

The NYS benefit week **ends on Sunday**. For the `WEEK_END` you are processing, the window is `WEEK_END - 6 days` through `WEEK_END`.

---

## Step 2 — Search Gmail for that week's applications

Use `mcp__gmail_personal__search_emails`. Gmail's `after:`/`before:` are date-exclusive at the edges, so pad by a day and filter by the returned `Date:` headers:

```
("thank you for applying" OR "thanks for applying" OR "thank you for your application" OR "application received" OR "we received your application" OR "your application has been received" OR "Indeed Application" OR "we've received your application" OR "application to") -from:{outreach_email} after:<WEEK_END-7> before:<WEEK_END+1>
```

Set `maxResults` to 100.

---

## Step 3 — Classify each result (this is the step that goes wrong)

**A confirmation subject line does not mean it is a confirmation.** Rejections routinely use warm "thank you for applying" phrasing. Real examples that are actually rejections:

- `"Thanks for applying to Roblox - we hope to connect again soon"`
- `"Optimum - Thank You for your application"`

**Read the body with `mcp__gmail_personal__read_email` for anything ambiguous.** Look for "moving forward with other candidates", "not the right fit", "won't be able to invite you".

Sort each email into:

| Type | Action |
|---|---|
| **New application confirmation** | Add to evidence (Step 4) |
| **Rejection / status update** | Do NOT add as an activity. Instead, update the `result` of the original application entry to `Not hired`. |
| **Interview invite** | Add — an attended interview is a qualifying activity. Set `result` to `Interview`. |
| **Job alert / newsletter / marketing** | Ignore |

Also capture, where the email states it:
- **Position title** — often only in the body, not the subject.
- **Named human sender** — a real recruiter name goes in the "person contacted" column. Generic `no-reply@` addresses do not.

---

## Step 4 — Append to the evidence file

Edit `scripts/ws5/evidence.json`, appending to `applications`:

```json
{
  "date": "2026-08-07",
  "company": "Watershed",
  "position": "Software Engineer, Platform",
  "contact": "jobs.ashbyhq.com",
  "person": "",
  "result": ""
}
```

- `date` — the date the application was submitted (the confirmation email's date).
- `company` — the employer, not the ATS vendor.
- `position` / `contact` — leave out if unknown; the generator backfills from the job tracker DB by company name.
- **Do not duplicate** an entry already present for the same date + company.

---

## Step 5 — Generate the form

```bash
cd scripts/ws5
python3 build_ws5.py --week <WEEK_END>
```

Writes `~/Desktop/WS5_work_search_records/WS5_week_ending_<WEEK_END>.pdf`.

The script pulls position titles and URLs from the local tracker DB, and only counts tracker rows whose status shows real contact (`Applied`, `Outreached`, `Rejected`, `Interview`, …) — never blank/`Tracking`/`Not Applied`, which mean the job was merely sourced.

It **exits 2 if the week is short** of 3 activities.

---

## Step 6 — Email one summary for the whole run

Only send an email if **at least one form was generated**. Never email on a no-op run.

Send via `mcp__gmail_personal__send_email` to `{notify_email}`:

- Subject for a single week: `Work Search Record — week ending <WEEK_END>`
- Subject when backfilling several: `Work Search Record — <N> weeks generated`

Body, covering every week generated in this run:

- **Any week under 3 activities goes at the very top**, stated plainly as not meeting the NYS minimum, with a reminder to add career-center visits, job fairs, or networking to the "Other Work Search Activities" box by hand.
- Per week: the activity count and the employer names.
- Where the PDFs were saved.
- Any rejections seen, and which application each one resolves.
- If this was a backfill covering more than one week, say so and note the likely cause (the Mac was closed or off on those days).

---

## Step 7 — Report back

For each week generated: the week covered, the activity count, whether it meets the 3-activity minimum, and the PDF path. If nothing was missing, just say the records are up to date.

---

## Notes

- The **NYS ID / SSN fields are intentionally left blank.** The user fills those via `fill_my_id.py` in the output folder, so the number never passes through a chat or a log.
- The **"Other Work Search Activities"** box is always left blank — only the user knows about non-application activity.
- Records must be **kept for one year** and not sent to DOL unless requested.
- Font size is a single knob: `FONT_PT` at the top of `build_ws5.py`.
