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

An agent driving Chrome can't open DevTools, so `inpage.js` does the same capture from
inside the page: injected into the ApplyPass tab, it wraps `XMLHttpRequest`/`fetch`,
sets 100 per page, clicks through every page of **Job Applied**, and downloads the same
merged file this panel does. The `applypass-inbound` skill's Step 0 drives it.

It refuses pages that aren't from Job Applied (the same endpoint answers for Job
Matches), picks the next arrow by position because both arrows share a class, and parks
as `stuck` rather than failing when the app ignores a synthetic click. Its pure helpers
are covered by `inpage.test.mjs`.

## Install

1. Open `chrome://extensions`, enable **Developer mode**.
2. **Load unpacked** → select this directory.

No permissions are requested — a DevTools panel reading its own inspected tab needs
none, so the manifest has no `permissions` block at all.

## Use

1. Open ApplyPass, open DevTools, select the **ApplyPass Capture** panel.
2. **Reload the page.** The panel only sees requests made while it is listening.
3. Page through your matches. Each recognized response appears as a row showing how many
   records it held and how many were new.
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
carry `_api_c2_match_id`, so the envelope's name and nesting depth don't matter and no
domain is hardcoded. `scripts/parse_applied_jobs.py:273-274` already unwraps `data`,
`results` *and* `matches` — three fallbacks nobody writes speculatively — which is why
keying on the records rather than their container is the safer bet.

Responses whose body Chrome has dropped appear as greyed rows. They can't be recognized
(detection reads the body), so without a row they'd vanish silently and take a page of
records with them — re-fetch those pages.

## Deduping

The panel dedupes on `_api_c2_match_id` so re-paginating is harmless. That is deduping
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
