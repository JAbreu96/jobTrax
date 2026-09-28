---
name: applypass-inbound
description: Import an auto-apply service export (ApplyPass-style JSON with `_api_c2_*` fields) into the local job tracker DB. Use when the user has pasted an export into the inbox file, says the inbox is ready to parse, asks to import auto-submitted applications, or asks to pull their applied jobs from ApplyPass.
---

Import the export sitting in the inbox into the job tracker.

The **inbox** is `data/applied_inbox.json` — a scratch file the user pastes each export into. Everything here runs from the repo root.

If the inbox is empty and Claude-in-Chrome is available, fill it yourself with Step 0.

---

## Step 0 — Capture from ApplyPass in the browser

`browser_extension/applypass_capture/inpage.js` pages through the **Job Applied** list
inside the ApplyPass tab and downloads one merged export. No DevTools, no clicking
through pages. It only reads; it never touches the database.

1. Open the user's ApplyPass dashboard in a new tab and wait until the job list and its
   page-size dropdown have rendered (~20s; the app is slow to boot).
2. Inject the script: pass the full contents of `inpage.js` to the `javascript_tool`.
   It installs `window.__applypassCapture` and starts listening. Inject **before**
   switching tabs so the first page is heard.
3. Click **Job Applied**. Use a coordinate click from a screenshot: the app ignores
   element-ref and synthetic clicks while it is still loading, and the dashboard opens on
   Job Matches, which answers in the same shape.
4. Get the cutoff, then start:

   ```bash
   python scripts/parse_applied_jobs.py --cutoff
   ```

   It prints the newest auto-applied `date_applied` in the tracker less two days, e.g.
   `2026-09-26`. Start with `__applypassCapture.start({stopBefore: "2026-09-26"})`: the
   list is newest-first, so paging stops at the first page holding an older submission
   and a weekly run is a handful of pages instead of all of them. It prints nothing
   when no export has been imported yet; then call `start()` with no cutoff.

   Poll `__applypassCapture.status()` until `state` is `done`. Pages take ~8s each. Wait between polls with the `computer` tool's `wait`
   action, **not** a `setTimeout` inside the page: Chrome throttles timers in a
   background tab to as little as once a minute, so an in-page 30s sleep can outlive the
   javascript tool's 45s limit. The same throttling slows the capture itself, so keep
   the tab in front if you can.
   - `error` naming **Job Matches**: the tab click did not take. Click Job Applied again
     (coordinates), wait, `start()` again. Pages it refused are counted in
     `wrongTabPagesRefused` and never kept.
   - `stuck`: the app ignored the synthetic click on the next arrow. Click the `›` arrow
     once by coordinates, then `__applypassCapture.resume()`. It continues from there.
5. Check `missing` is empty. A full run should also have `records == totalRecords`; an
   incremental one stops early by design, so check `stoppedAt` is set instead — if it
   is null the cutoff was never reached and the whole list was paged, which is correct
   but means the tracker was further behind than the cutoff suggested.
   `__applypassCapture.download()`
   saves `applied_inbox_<timestamp>.json` to `~/Downloads` and returns the filename —
   downloading is a user-visible action, so say what you are saving first.
6. `mv ~/Downloads/<that filename> data/applied_inbox.json` and close the tab.

---

## Step 1 — Read the inbox

```bash
python -c "
import json; d=json.load(open('data/applied_inbox.json'))
print(f'{len(d)} records, {sum(1 for r in d if r.get(\"_api_c2_application_submitted_bool\"))} submitted')"
```

An empty inbox (`[]`) means the user has not pasted yet — say so and stop. Offer to open it: `code data/applied_inbox.json`.

The inbox has a second source: the **ApplyPass Capture** DevTools panel
(`browser_extension/applypass_capture/`) writes a merged export to `~/Downloads`. If the
user captured with it rather than pasting, move it into place first — the panel prints
this command with the real filename:

```bash
mv ~/Downloads/applied_inbox_<timestamp>.json data/applied_inbox.json
```

Use the filename the panel showed, not a glob: Chrome appends ` (1)` to repeat downloads,
so a glob can pick up a stale file. Everything below is unchanged either way.

---

## Step 2 — Preview

```bash
set -a; source .env; set +a
python scripts/parse_applied_jobs.py
```

`src/jobs_db.py` loads `.env` itself, by absolute path, so the importer reaches
Turso from any shell. The `source` line is still here because the backup and
verification snippets below open `libsql` directly and read
`TURSO_DATABASE_URL` from the environment; keep it on every command so they all
agree. It does not override a variable you have set on purpose — `jobs_db` uses
`override=False`, and an *empty* `TURSO_DATABASE_URL` is what keeps you on a
local copy.

The script prints which database it wrote to. Read that line; do not assume it.
Before this was fixed, 101 rows once landed in `data/jobs.db`, a file nothing
reads, and every count still reconciled.

Dry run — writes nothing. It prints every row as NEW or DUP, plus within-file duplicates collapsed and records skipped.

Read the output before writing. Report to the user:
- the NEW / DUP counts
- every DUP and what existing row it matched
- every skipped record and why

Records skipped for **no company name** are unrecoverable by the parser — the source itself left `_api_c2_company_name` blank. Surface their job title and URL so the user can decide whether to add them by hand.

---

## Step 3 — Back up the DB

Back up **Turso**, the database being written. Copying `data/jobs.db` preserves a
file the import never touches.

```bash
set -a; source .env; set +a
python - <<'EOF'
import os, json, datetime, libsql
c = libsql.connect(os.environ["TURSO_DATABASE_URL"].strip(),
                   auth_token=os.environ["TURSO_AUTH_TOKEN"].strip())
cur = c.execute("select * from jobs")
cols = [d[0] for d in cur.description]
rows = [dict(zip(cols, r)) for r in cur.fetchall()]
path = "data/jobs.turso.bak-%s.json" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
json.dump(rows, open(path, "w"))
print("backed up %d rows -> %s" % (len(rows), path))
EOF
```

Keep that row count — Step 5 checks against it.

---

## Step 4 — Import

```bash
set -a; source .env; set +a
python scripts/parse_applied_jobs.py --write --clear
```

Confirm the final line says `in Turso`. If it says `in data/jobs.db`, the `.env`
did not load — nothing is lost, but re-run against the archived export (Step 4's
`--clear` already saved it) with the environment set before reporting success.

`--write` inserts new rows into the tracker DB and **merges** into rows already there. `--clear` copies the inbox to `data/applied_inbox_archive/applied_inbox_<timestamp>.json`, then resets the inbox to `[]` for the next export.

A merge only ever fills blanks, refreshes `location`, and moves a status *forward*. It never touches `contacts`, `notes`, `outreach_date` or `followup_log`, and never downgrades a status, so re-running the same export is safe. Rows matching an **archived** job are reported and skipped — nothing is resurrected. Every run writes `data/applied_inbox_archive/merge_<timestamp>.log` recording exactly which columns changed.

---

## Step 5 — Verify the row delta

```bash
set -a; source .env; set +a
python -c "
import os, libsql
c = libsql.connect(os.environ['TURSO_DATABASE_URL'].strip(),
                   auth_token=os.environ['TURSO_AUTH_TOKEN'].strip())
print(c.execute('select count(*) from jobs').fetchall()[0][0])"
```

**The row count must rise by exactly the number of rows the parser reported as new.** Updated rows must not move it at all — a merge edits a row in place, so a rise larger than the new count means a merge inserted instead of updating, which is the duplicate-row bug this path was built to end. A rise *smaller* than the new count means rows overwrote each other on the primary key `(company, date_added, position_title, link)` and data was silently lost. Either way, find the collisions before reporting success:

```bash
set -a; source .env; set +a
python - <<'EOF'
import json, collections, importlib.util, sys, glob
sys.path.insert(0, ".")
spec = importlib.util.spec_from_file_location("paj", "scripts/parse_applied_jobs.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
archive = max(glob.glob("data/applied_inbox_archive/applied_inbox_*.json"))
# include_unsubmitted must match the flags the import ran with. Left at its
# default against an --all export, parse_export drops every record and returns
# an empty list -- which reads as "no collisions" and proves nothing.
rows = m.parse_export(json.load(open(archive)), include_unsubmitted=True)["rows"]
print("parsed rows:", len(rows))
c = collections.Counter(
    (r["company"], r["date_added"], r["position_title"], r["link"]) for r in rows)
for k, v in c.items():
    if v > 1:
        print(f"{v}x  {k}")
EOF
```

Identical keys mean the same posting URL twice — a true duplicate in the source, which collapses correctly. Anything else is a bug in the parser's field mapping — report it rather than papering over it.

To confirm coverage, check the parsed rows against the DB directly. Do **not**
re-run `classify_rows` here: after a successful write every row classifies as
`unchanged`, so `groups["new"]` is empty and the loop passes without testing
anything. Rows marked `UPDT`/`SAME` keep their **original** `date_added`, so they
will not match the incoming record's key — that is the merge working, not a miss:

```bash
set -a; source .env; set +a
python - <<'EOF'
import json, importlib.util, sys, glob
sys.path.insert(0, ".")
spec = importlib.util.spec_from_file_location("paj", "scripts/parse_applied_jobs.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
archive = max(glob.glob("data/applied_inbox_archive/applied_inbox_*.json"))
rows = m.parse_export(json.load(open(archive)), include_unsubmitted=True)["rows"]
conn = m.get_all_jobs.__globals__["_connect"]()   # same driver the import used
# Build tuples explicitly: libSQL rows are _ShimRow, which is unhashable, so
# set(cursor) raises TypeError instead of giving you a set of keys.
have = {(r["company"], r["date_added"], r["position_title"], r["link"])
        for r in conn.execute(
            "select company, date_added, position_title, link from jobs").fetchall()}
miss = [r for r in rows
        if (r["company"], r["date_added"], r["position_title"], r["link"]) not in have]
print("present: %d/%d" % (len(rows) - len(miss), len(rows)))
for r in miss:
    print("MISSING:", r["company"], "|", r["position_title"])
EOF
```

Rows that matched an **archived** job are reported missing here and should be —
they were skipped on purpose. Expect the miss count to equal the archived-match
count from Step 2.

---

## Step 6 — Report

State:
- rows imported, and the tracker's before → after count
- rows **updated**, and which columns changed on each (the merge log has this)
- rows matching an archived job, which were skipped
- any ambiguous matches the parser refused to guess at
- records skipped for a blank company, with title and URL
- true duplicate postings that collapsed
- where the backup and the archived export live

---

## Unattended runs

`scripts/run-applypass-inbound.sh` runs this skill daily at 09:30 with nobody watching.
Its prompt pre-authorizes the download and the `--write --clear` import. Nothing else
is authorized. Steps 0–6 apply unchanged, with these rules on top, because no one is
there to ask:

- **Start from an empty inbox.** If `data/applied_inbox.json` is not `[]`, an earlier run
  stopped partway. Stop without touching it — someone has to look at what is in it.
- **Always incremental.** Use `--cutoff`, or no cutoff when it prints nothing.
- **Touch only three controls.** On the ApplyPass page, click only the Job Applied tab,
  the page-size dropdown and the pager arrows. Never click like/dislike, **Pause
  Applying**, Edit Profile, or anything that changes the account.
- **Never sign in.** If the page shows a login screen, the session has expired: stop.
  Credentials are the user's to enter.
- **Bounded recovery.** Allow one Job Matches retry and two `stuck` recoveries, each a
  single coordinate click. After that, stop without downloading.
- **Download only a complete capture.** `state` is `done` and `missing` is empty.
- **Close the tab** whether the run succeeded or not.
- **A row delta that does not match the NEW count** (Step 5) is still reported, as a
  stop. The write has happened by then, but the mismatch needs a person.

End with exactly one line the runner reads:

```
RESULT: imported <n> new, <m> updated
RESULT: stopped: <one-line reason>
```

The runner raises a macOS notification on any stop or failure. A clean import stays
silent.

---

## Field mapping

`scripts/parse_applied_jobs.py` owns this; it is recorded here only where the choice is not obvious from the code.

| Tracker column | Export field | Note |
|---|---|---|
| `date_added` | `datetime_matched` | when the service matched the job, not when it applied |
| `date_applied` | `application_submitted_date` | |
| `status` | — | `Applied` when submitted, else `Tracking` |
| `job_summary` | — | never imported; left blank. Look a posting up on demand, or fill blanks with `scripts/backfill_job_fields.py` |
| `location` | `location_name` + `location_type` | `California (On-site)` |
| `notes` | — | provenance, the export's own match score, seniority, board, source IDs |

The export's `match_score_combined` is the service's number, not a resume review. Notes label it as source-provided so it is never confused with a `/resume-review` score.

Records are dropped when `_api_c2_is_invalid` is set, when `company_name` is blank, or — absent `--all` — when the application was never submitted.

---

## Flags

| Flag | Effect |
|---|---|
| *(none)* | dry-run preview |
| `--write` | upsert new rows into the tracker DB — Turso when `TURSO_DATABASE_URL` is set (`.env` sets it), `data/jobs.db` when it is empty |
| `--clear` | with `--write`: archive the inbox, then empty it |
| `--all` | include records whose application was never submitted (they land as `Tracking`) |
| `--skip-existing` | do not merge into rows already in the tracker; report and ignore them |
| `--json PATH` | dump the parsed tracker rows for inspection |
| `PATH` | parse a file other than the inbox — use the archive path to re-run a past export |
