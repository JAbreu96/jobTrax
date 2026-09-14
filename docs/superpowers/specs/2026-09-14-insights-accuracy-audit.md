# Insights page — accuracy audit

**Date:** 2026-09-14
**Scope:** read-only audit of every metric on `/insights`. No code changed, no DB writes.
**Verdict:** the measurement code is correct. The page is inaccurate because the data it
measures is never fully written. Do not rebuild the stats layer.

> **Status:** Finding 1 is fixed (branch `fix/date-applied-on-advance`). `update_status` now
> maintains the invariant for every writer, and 78 pre-existing rows were backfilled — the
> audit originally scoped this at 22, having counted only screening-status rows and missed 56
> rows sitting at `Applied` with no date. The application funnel now reads
> **tracked 1280 → applied 912 → at screen 29 → interviewed 3**. Findings 2-7 are open.

---

## Summary

Every stats function on this page computes what its tests say it computes. I found no
arithmetic or query defect in `funnel_stats`, `classify_interviews`, `interview_stats`,
`job_silence_stats` or `recruiter_coverage`. The existing test suite pins the subtle
definitions correctly.

The page is nonetheless misleading, because three fields are effectively never populated:

| Field | Who should write it | Reality |
|---|---|---|
| `jobs.date_applied` | any status advance | only the GUI, only on the exact transition to `Applied` |
| `interviews.occurred_date` | inbox-triage on an outcome email | 27 of 40 rounds never get it; 24 are past-due |
| recruiter replies | inbox-triage | 6 replies logged across 85 recruiters |

Because the funnel is nested — each stage is a subset of the one above — an unwritten
`date_applied` silently deletes a job from every stage below it. That is the single largest
distortion on the page.

---

## Finding 1 — The application funnel understates screening by 4.7x

**Severity: high.** This is the headline number on the page.

The page renders:

```
tracked 1280 → applied 834 (65.2%) → at screen 7 (0.8%) → interviewed 2
```

Ground truth: **33 jobs have actually reached a screen** (25 currently sit at a screening
status; the rest have a logged screening round). The funnel says 7.

### Root cause

`funnel_stats` computes `at_screen(applied)` — nested inside the applied subset
(`src/jobs_db.py:1360`). That nesting is correct funnel semantics. The problem is that
**only 3 of the 25 jobs at a screening status have a `date_applied`**. The other 22 are not
in the `applied` list, so they cannot be counted at any stage below it.

`date_applied` is written in exactly one place — `src/jobs_gui.py:464`:

```python
if field == "status" and value == "Applied":
```

An exact-string match, in the GUI only. Meanwhile inbox-triage advances jobs through
`mcp__job_tracker__update_job_status` (`.claude/skills/inbox-triage/SKILL.md:311`), and that
path **never sets `date_applied`** — `mcp_servers/job_tracker/server.py:189` only carries an
existing value forward. Any job that goes straight to `Phone Screen`, or is advanced by
triage rather than by a human clicking in the GUI, keeps an empty `date_applied` forever.

So the 0.8% screen-conversion rate is an artifact of a missing write, not a real outcome.

### Knock-on

`interviewed` shows 2 on the application path; `interviewed_total` is 3. The gap is
`interviewed_unattributed = 1` — a job with neither an application nor an outreach date.
The page does surface this honestly in the "Where the paths meet" footer, which is good
design working as intended.

---

## Finding 2 — The interview table runs on 13 of 40 rounds

**Severity: high.**

```
rounds 13 · advanced 2 · failed 5 · ghosted 2 · awaiting 4 · decided 9
```

`INTERVIEW_RATE_MIN_ROUNDS` is 8 and `decided` is 9. Every advance rate on this card is one
row away from being withheld entirely.

### Root cause

40 interview rows exist. **13 have an `occurred_date`; 27 are scheduled-only.**
`classify_interviews` (`src/jobs_db.py:1147`) deliberately drops booked-but-not-held rounds —
correct, since an unheld round has no outcome.

But of those 27 scheduled-only rounds, **24 are already in the past**, idle up to 19 days.
They are bookings nobody ever marked as happened.

inbox-triage knows how to do this — `SKILL.md:573` calls `mark_interview_occurred()`. It only
fires when an email references the outcome. Nothing ever sweeps for "this was scheduled
19 days ago and was never resolved." The page shows these in the "N booked before today with
no outcome" line, so the signal is visible; nothing acts on it.

### Also

- 5 interview rows point at job keys that no longer exist. These classify as
  `awaiting_outcome` with `job_orphaned=True`, which is the right conservative call, but they
  are permanently stuck in the denominator-free bucket.
- 10 jobs sit at `Phone Screen` with no interview row at all.

---

## Finding 3 — The outreach path measures nothing below stage two

**Severity: medium** — the path is structurally incomplete, not wrong.

```
tracked 1280 → outreached 69 (5.4%) → replied (none) → interviewed 0
```

`replied` is hardcoded `None` (`src/jobs_db.py:1366`) because no reply field exists on `jobs`.
The code handles this well: the `None` propagates so no rate is computed across the gap, and
`buildChart` drops the stage rather than plotting a zero.

The reply data *does* exist, in `recruiter_messages.direction = 'reply'` — but only **6 replies
across 85 recruiters**, and 33 recruiters have no linked role at all. So the path terminates
at 0 interviewed. That 0 is real, not a bug, but it reflects under-recording rather than
under-performance.

---

## Finding 4 — 51 rows carry a status outside the vocabulary

**Severity: medium.**

| Status | Rows |
|---|---|
| `Outreached` | 44 |
| `Not Applied` | 4 |
| `Applied & Outreached` | 2 |
| `Outreached and Applied` | 1 |

None appear in `STATUS_ORDER` (`src/jobs_db.py:89`), so `status_rank()` returns -1 and they
match no stage set. 30 of them have an `outreach_date`.

*(Note: blank status is **not** a defect — the empty string is a legitimate first entry in
`STATUS_ORDER`. An earlier count of 106 was wrong on this point.)*

### Root cause

`scripts/sync_jobs_to_sqlite.py:87` copies the Google Sheet's `status` cell verbatim via
`INSERT OR REPLACE`, with no validation. These are hand-typed spreadsheet cells. The MCP
write path does validate (`server.py:150`, `VALID_STATUSES`), so these did not come through it.

### There are two competing vocabularies

`scripts/ws5/build_ws5.py:272` defines its own `CONTACTED` list by **substring** match —
`"outreach"`, `"interview"`, `"offer"` — which happily accepts `Outreached` and
`Applied & Outreached`. So the DOL work-search form counts rows the insights funnel cannot
see. Two parts of this project disagree about what a status is.

---

## Finding 5 — Silence buckets are dominated by auto-applies

**Severity: low** — accurate, but easy to misread.

```
ghosted     hand 21 · auto 3   · total 24
no_response hand 15 · auto 283 · total 298
waiting     hand 50 · auto 362 · total 412
```

The 283 is real: bulk auto-applies past the 30-day `NO_RESPONSE_AFTER_DAYS` threshold that
genuinely never replied. The page already splits hand from auto and never sums them silently
(pinned by `tests/test_job_silence.py`), so this is working as designed. Flagged only because
the total is what the eye lands on first, and it is ~95% auto.

---

## Finding 6 — Latent: partial-key writes can hit sibling roles

**Severity: low now, high if it fires. Has not fired yet.**

`archive_jobs()` (`src/jobs_db.py:755`) matches on `company` + `date_added` only, not the
four-column key:

```python
"UPDATE jobs SET archived = 1 WHERE company = ? AND date_added = ?"
```

`update_field()` has the same shape — `position_title` and `link` are optional, and omitting
them updates every row sharing what was given.

Exposure: **114 `(company, date_added)` pairs cover more than one distinct role, spanning 295
job rows.** I checked all 226 currently-archived rows: **no multi-role pair has been
archived**, so no data is currently corrupted. The hazard is latent.

---

## Finding 7 — A second, untested stats implementation

**Severity: low.**

`mcp_servers/job_tracker/server.py:315` `get_stats()` re-implements counting in a Python loop
instead of calling `jobs_db`. It has no test. MCP and GUI can drift apart silently.

`server.py:393` `interview_rates()` documents `advanced / (advanced + failed)`. The code it
wraps uses `advanced / (advanced + failed + ghosted)`. The docstring is stale.

---

## What is correct

Worth stating, since it bounds the remediation:

- Nested funnel semantics, and rate suppression below `RATE_MIN_DENOMINATOR = 30`.
- `None` propagation across the unmeasured `replied` stage — no rate is computed over a gap.
- `interviewed_total` as a distinct-job count, with `interviewed_unattributed` surfaced rather
  than hidden.
- Ghosted in the advance-rate denominator, `awaiting_outcome` excluded.
- Hand/auto never silently summed.
- `recruiter_coverage` reporting two counts and refusing to render a ratio.
- Archived rows deliberately included in the funnel, excluded from silence.

---

## Recommendations, ranked

1. ~~**Set `date_applied` wherever a job advances past `Applied`**~~ — **done.** The invariant
   now lives in `jobs_db.update_status` (covering MCP/inbox-triage) and in the GUI's own write
   path, both keyed off the derived `APPLIED_STATUSES`. `scripts/backfill_date_applied.py`
   repaired 78 rows using each row's `date_added`.
2. **Sweep for past-due bookings.** 24 rounds are scheduled, past, and unresolved. Either
   prompt on them in inbox-triage or let the page's existing "booked before today" line drive
   a task. *(Process.)*
3. **Validate status on sheet import** (`sync_jobs_to_sqlite.py`) and normalize the 51
   off-vocabulary rows. Decide first whether `Outreached` should join `STATUS_ORDER` — 44 rows
   suggest the vocabulary is what is out of date, not the data. *(Definition, then code.)*
4. **Reconcile the two status vocabularies** — `STATUS_ORDER` vs `build_ws5.py:272`. One
   should derive from the other.
5. **Use the full four-column key** in `archive_jobs` and default it in `update_field`.
   Latent, but 295 rows are exposed.
6. **Make MCP `get_stats()` delegate to `jobs_db`** and fix the `interview_rates` docstring.

None of this requires rebuilding the measurement layer.
