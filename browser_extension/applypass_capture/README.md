# ApplyPass Capture

A Chrome DevTools panel that reads ApplyPass export responses straight out of the
network traffic, merges the paginated pages into one JSON file, and hands it to the
existing `applypass-inbound` skill.

It exists because the ApplyPass API pages at 100 records. Importing a full run used to
mean paginate → copy the response body by hand → paste into `data/applied_inbox.json` →
import, once per page. `data/applied_inbox_archive/` still shows the four separate
exports that took on 2026-08-16.

**It makes no Python changes and never touches the database.** Its only output is a JSON
file in the shape `scripts/parse_applied_jobs.py` already accepts, so the parser stays
the single implementation of the field mapping and a bug here can't write a bad row.

## Without DevTools: `inpage.js`

An agent driving Chrome can't open DevTools, so `inpage.js` captures from inside the
page instead. ApplyPass's Next.js board (it left Bubble in October 2026) fills its
**Application** column from one plain GET, `/api/jobListingMatches` with
`current_stage_type_key=job_applied`, authenticated by the session cookie. Injected into
the signed-in tab, the script asks for that list itself, newest submission first at 500
a page, and downloads the same merged file this panel does — no scrolling, no clicks.
The `applypass-inbound` skill's Step 0 drives it.

It refuses a page holding records from outside the Application column, stops at the
incremental cutoff, re-reads page 1 when applications land mid-run, and reports a
signed-out session rather than capturing nothing. Its helpers, the paging loop included,
are covered by `inpage.test.mjs` against a fake ApplyPass.

## Install

1. Open `chrome://extensions`, enable **Developer mode**.
2. **Load unpacked** → select this directory.

No permissions are requested — a DevTools panel reading its own inspected tab needs
none, so the manifest has no `permissions` block at all.

## Use

1. Open ApplyPass, open DevTools, select the **ApplyPass Capture** panel.
2. **Reload the page.** The panel only sees requests made while it is listening.
3. Scroll the Application column to the bottom. Each recognized response appears as a
   row showing how many records it held and how many were new. The board loads Job
   Matches from the same endpoint, so those responses appear too; their records are
   unsubmitted, and the parser drops them.
4. **Download JSON**, then move it into the inbox — the panel prints this exact command
   with the real filename after each download:

   ```bash
   mv ~/Downloads/applied_inbox_<timestamp>.json data/applied_inbox.json
   ```

5. Run the `applypass-inbound` skill as usual. It backs up the DB and checks the row
   delta, unchanged.

Captured records live in memory only — **closing DevTools discards them.** Download
after each run.

## How a response is recognized

Not by URL. `detect.mjs` walks the parsed body and returns the first array whose elements
carry a match id — `match_id` from the Next.js app, `_api_c2_match_id` from the Bubble
app before it — so the envelope's name and nesting depth don't matter and no
domain is hardcoded. `scripts/parse_applied_jobs.py:273-274` already unwraps `data`,
`results` *and* `matches` — three fallbacks nobody writes speculatively — which is why
keying on the records rather than their container is the safer bet.

Responses whose body Chrome has dropped appear as greyed rows. They can't be recognized
(detection reads the body), so without a row they'd vanish silently and take a page of
records with them — re-fetch those pages.

## Deduping

The panel dedupes on the match id so re-paginating is harmless. That is deduping
**this capture**, not the tracker's contents — the DB's key is
`(company, date_added, position_title, link)`, a different thing entirely. The parser's
NEW/DUP report and the skill's row-count check remain the only authority on real
duplicates.

## Tests

`detect.mjs` is kept free of Chrome APIs so it stays testable — it's the one piece whose
failure is silent, since a wrong walk yields an empty panel and no stack trace.

```bash
node --test browser_extension/applypass_capture/
```

No install, no `package.json`, no dependencies. Fixtures are synthetic: `.gitignore`
excludes `data/` because it holds personal info, so real captures must never be
committed as test data.
