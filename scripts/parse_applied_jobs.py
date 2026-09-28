#!/usr/bin/env python3
"""
Parse an auto-apply service export (records with `_api_c2_*` keys) into rows
shaped for the local job tracker DB (src/jobs_db.COLUMNS).

Paste each export into the inbox file (data/applied_inbox.json), then:

    python scripts/parse_applied_jobs.py                  # preview (dry run)
    python scripts/parse_applied_jobs.py --write --clear   # import, archive, empty the inbox
    python scripts/parse_applied_jobs.py other.json        # or parse any other file
    python scripts/parse_applied_jobs.py --all             # include not-yet-submitted
    python scripts/parse_applied_jobs.py --cutoff          # date an incremental capture can stop at
"""

import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.jobs_db import (  # noqa: E402
    COLUMNS, _is_auto, _use_libsql, get_all_jobs, shared_connection, status_rank,
    update_job_fields, upsert_jobs
)

P = "_api_c2_"
STATUS_APPLIED = "Applied"
STATUS_TRACKING = "Tracking"

# How far before the newest imported application an incremental capture reaches.
# date_applied is stored as a local date and ApplyPass stamps UTC, so the two can
# disagree by a day at either end; a second day covers an import taken while the
# service was still submitting that day's batch. Re-capturing them is free -- the
# merge reports them unchanged.
CUTOFF_BUFFER_DAYS = 2

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
# Scratch file to paste each export into; emptied after a successful --write --clear.
INBOX_PATH = os.path.join(_DATA_DIR, "applied_inbox.json")
ARCHIVE_DIR = os.path.join(_DATA_DIR, "applied_inbox_archive")


def _get(rec: dict, field: str, default=None):
    """Read a field with the `_api_c2_` prefix stripped from the caller's view."""
    return rec.get(P + field, default)


def _iso_to_date(value: str) -> str:
    """'2026-08-16T23:49:34.987Z' -> '2026-08-16' (local date). '' if unparseable."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:10]
    if dt.tzinfo:
        dt = dt.astimezone()
    return dt.date().isoformat()


def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value if v]


def _location(rec: dict) -> str:
    """['California'] + ['On-site'] -> 'California (On-site)'."""
    names = _as_list(_get(rec, "location_name"))
    types = _as_list(_get(rec, "location_type"))
    base = ", ".join(names)
    if types:
        suffix = "/".join(types)
        return f"{base} ({suffix})" if base else suffix
    return base


def _notes(rec: dict) -> str:
    """Provenance + the export's own scoring, so an imported row is recognizable."""
    lines = ["Imported from auto-apply export (auto-submitted application)."]

    score = _get(rec, "match_score_combined")
    if isinstance(score, (int, float)):
        lines.append(f"Match Score: {round(score * 100)}/100 (source-provided, not resume-reviewed)")

    meta = []
    for label, field in (("Seniority", "seniority_level"), ("Board", "job_source")):
        val = _get(rec, field)
        if val:
            meta.append(f"{label}: {val}")
    site = _get(rec, "company_website")
    if site:
        meta.append(f"Website: {site}")
    if meta:
        lines.append(" | ".join(meta))

    if _get(rec, "application_submission_error"):
        lines.append("⚠️ Export flagged a submission error — verify the application went through.")
    if _get(rec, "user_marked_match_bad"):
        lines.append("Marked as a bad match in the source tool.")

    note = (_get(rec, "notes") or "").strip()
    if note:
        lines.append(f"Source notes: {note}")

    ids = [f"match_id={_get(rec, 'match_id')}", f"job_id={_get(rec, 'job_id')}"]
    lines.append("Source IDs: " + ", ".join(i for i in ids if not i.endswith("=None")))
    return "\n".join(lines)


def parse_record(rec: dict) -> dict:
    """Map one export record onto the tracker's column shape."""
    submitted = bool(_get(rec, "application_submitted_bool"))
    applied_date = _iso_to_date(_get(rec, "application_submitted_date", "")) if submitted else ""
    return {
        "company": (_get(rec, "company_name") or "").strip(),
        "position_title": (_get(rec, "job_title") or "").strip(),
        # Deliberately blank. The export carries a full description per record
        # (~5KB of HTML each), but it is read rarely enough that looking it up
        # on demand beats storing ~2,800 of them; backfill_job_fields.py fills a
        # blank summary from the posting URL when one is wanted.
        "job_summary": "",
        "location": _location(rec),
        "link": (_get(rec, "job_url") or "").strip(),
        "date_added": _iso_to_date(_get(rec, "datetime_matched", "")),
        "contacts": "",
        "notes": _notes(rec),
        "outreach_date": "",
        "date_applied": applied_date,
        "status": STATUS_APPLIED if submitted else STATUS_TRACKING,
        "followup_log": "",
    }


def _skip_reason(rec: dict, include_unsubmitted: bool) -> str | None:
    if not (_get(rec, "company_name") or "").strip():
        return "no company name"
    if _get(rec, "is_invalid"):
        return "flagged invalid by source"
    if not include_unsubmitted and not _get(rec, "application_submitted_bool"):
        return "application not submitted"
    return None


def _norm_link(link: str) -> str:
    return (link or "").strip().rstrip("/").lower()


def parse_export(records: list[dict], include_unsubmitted: bool = False) -> dict:
    """
    Returns {"rows": [...], "skipped": [(company, reason)], "dupes_in_file": [...]}.
    Within-file duplicates keep the most recently applied record.
    """
    rows: dict[str, dict] = {}
    order: list[str] = []
    skipped, dupes = [], []

    for rec in records:
        reason = _skip_reason(rec, include_unsubmitted)
        if reason:
            skipped.append(((_get(rec, "company_name") or "?"), reason))
            continue

        row = parse_record(rec)
        key = _norm_link(row["link"]) or f"{row['company'].lower()}|{row['position_title'].lower()}"
        prev = rows.get(key)
        if prev:
            dupes.append(f"{row['company']} — {row['position_title']}")
            if row["date_applied"] <= prev["date_applied"]:
                continue
        else:
            order.append(key)
        rows[key] = row

    return {"rows": [rows[k] for k in order], "skipped": skipped, "dupes_in_file": dupes}


# Which columns an export may touch on a row that already exists, and which it
# may never touch. The export is a machine's view of a posting; contacts,
# outreach dates and followup logs are work done by hand or by another skill,
# and an import that flattens them is worse than an import that does nothing.
EXPORT_WINS = ("location",)
FILL_IF_BLANK = ("date_applied", "link")
CURATED = ("contacts", "notes", "outreach_date", "followup_log")


def merge_updates(incoming: dict, existing: dict) -> dict:
    """
    The columns an export record may change on the tracker row it matched.

    `date_applied` is fill-if-blank rather than export-wins: a date read off a
    real confirmation email outranks the export's. `job_summary` is never
    written at all -- see parse_record.
    """
    updates: dict[str, str] = {}

    for col in EXPORT_WINS:
        value = (incoming.get(col) or "").strip()
        if value and value != (existing.get(col) or "").strip():
            updates[col] = value

    for col in FILL_IF_BLANK:
        value = (incoming.get(col) or "").strip()
        if value and not (existing.get(col) or "").strip():
            updates[col] = value

    # Never downgrade a status: the rule the skills have stated in prose since
    # inbox-triage was written. The export only ever emits Applied or Tracking,
    # so this can only ever move a row forward.
    incoming_status = (incoming.get("status") or "").strip()
    if status_rank(incoming_status) > status_rank(existing.get("status")):
        updates["status"] = incoming_status

    return updates


def incremental_cutoff(jobs: list[dict], buffer_days: int = CUTOFF_BUFFER_DAYS) -> str:
    """
    The oldest submission date an incremental capture still needs: the newest
    date_applied among rows this importer wrote, less a buffer. '' when nothing
    has been imported yet, which means capture everything.

    Only auto-applied rows count. A job you applied to by hand yesterday says
    nothing about how far the export has been imported, and letting it set the
    cutoff would skip every export record older than it.
    """
    newest = None
    for job in jobs:
        if not _is_auto(job):
            continue
        try:
            applied = date.fromisoformat((job.get("date_applied") or "")[:10])
        except ValueError:
            continue
        if newest is None or applied > newest:
            newest = applied
    if newest is None:
        return ""
    return (newest - timedelta(days=buffer_days)).isoformat()


def _pick(candidates: list[dict]) -> dict | None:
    """Most recently added live row, the preference find_job_by_link encodes."""
    live = [c for c in candidates if not c.get("archived")]
    if not live:
        return None
    return sorted(live, key=lambda r: r.get("date_added") or "")[-1]


def classify_rows(rows: list[dict]) -> dict:
    """
    Partition parsed rows against the tracker DB.

    A link identifies a posting, so a row that has one is matched on link first
    -- a company posting several requisitions under one title yields distinct
    URLs, and matching those on company+title would collapse them as false
    duplicates. On a link miss we fall back to company+title but accept only
    rows whose link is blank: those are unreachable by link forever otherwise,
    so without this every export would insert a duplicate beside them. A row
    holding a *different* non-blank link is a different requisition, not a match.

    Archived rows are matched but frozen. Previously find_job_by_link filtered
    them out while the company+title path did not, so a record matching an
    archived row was reported new and inserted next to the job you had
    deliberately archived.
    """
    tracker = get_all_jobs(include_archived=True)

    by_link: dict[str, list[dict]] = {}
    by_pair: dict[tuple, list[dict]] = {}
    blank_by_pair: dict[tuple, list[dict]] = {}
    for job in tracker:
        pair = ((job.get("company") or "").strip().lower(),
                (job.get("position_title") or "").strip().lower())
        by_pair.setdefault(pair, []).append(job)
        link = _norm_link(job.get("link") or "")
        if link:
            by_link.setdefault(link, []).append(job)
        else:
            blank_by_pair.setdefault(pair, []).append(job)

    out = {"new": [], "updates": [], "unchanged": [], "archived": [], "ambiguous": []}

    for row in rows:
        pair = (row["company"].strip().lower(), row["position_title"].strip().lower())
        link = _norm_link(row["link"])

        if link:
            candidates = by_link.get(link, [])
            if not candidates:
                # Blank-link rows only; see the docstring.
                fallback = blank_by_pair.get(pair, [])
                live = [c for c in fallback if not c.get("archived")]
                if len(live) > 1:
                    out["ambiguous"].append((row, live))
                    continue
                candidates = fallback
        else:
            candidates = by_pair.get(pair, [])

        if not candidates:
            out["new"].append(row)
            continue

        match = _pick(candidates)
        if match is None:
            # Every candidate is archived: report it, touch nothing.
            out["archived"].append((row, candidates[0]))
            continue

        updates = merge_updates(row, match)
        (out["updates"] if updates else out["unchanged"]).append((row, match, updates))

    return out


def _print_report(result: dict, groups: dict) -> None:
    rows = result["rows"]
    print(f"Parsed {len(rows)} record(s) → {len(groups['new'])} new, "
          f"{len(groups['updates'])} to update, {len(groups['unchanged'])} unchanged, "
          f"{len(groups['archived'])} archived, {len(groups['ambiguous'])} ambiguous\n")

    matched = {id(r): (m, u) for r, m, u in groups["updates"] + groups["unchanged"]}
    archived = {id(r): m for r, m in groups["archived"]}
    ambiguous = {id(r): c for r, c in groups["ambiguous"]}

    for row in rows:
        if id(row) in archived:
            flag = "ARCH"
        elif id(row) in ambiguous:
            flag = "AMBG"
        elif id(row) in matched:
            flag = "UPDT" if matched[id(row)][1] else "SAME"
        else:
            flag = "NEW "
        print(f"{flag} {row['company']} — {row['position_title']}")
        print(f"    applied {row['date_applied'] or '—'} | {row['location'] or 'location n/a'} "
              f"| {row['status']}")
        print(f"    {row['link'] or '(no link)'}")

        if id(row) in archived:
            m = archived[id(row)]
            print(f"    ↳ matches ARCHIVED row: {m['company']} / {m.get('date_added')} "
                  f"— skipped, neither inserted nor updated")
        elif id(row) in ambiguous:
            print(f"    ↳ {len(ambiguous[id(row)])} linkless rows share this company and "
                  f"title — refusing to guess; fill the link by hand")
        elif id(row) in matched:
            m, updates = matched[id(row)]
            print(f"    ↳ matches existing row: {m['company']} / {m.get('date_added')} "
                  f"(status: {m.get('status') or '—'})")
            if updates:
                kept = ""
                if "status" not in updates and m.get("status"):
                    kept = f" (status {m['status']} kept)"
                print(f"    ↳ would set: {', '.join(sorted(updates))}{kept}")
            else:
                print("    ↳ nothing to change")
        print()

    if result["dupes_in_file"]:
        print("Duplicates collapsed within the file (kept latest applied):")
        for d in result["dupes_in_file"]:
            print(f"  - {d}")
        print()
    if result["skipped"]:
        print("Skipped records:")
        for company, reason in result["skipped"]:
            print(f"  - {company}: {reason}")
        print()


def write_merge_log(groups: dict, source: str) -> str:
    """
    Record what a --write run changed, beside the export archive it came from.
    A merge is otherwise invisible afterwards: the preview scrolls away and the
    tracker has no updated-at column. Provenance does not go in `notes` -- that
    is a curated field this importer promises never to write.
    """
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    dest = os.path.join(ARCHIVE_DIR, f"merge_{stamp}.log")
    with open(dest, "w", encoding="utf-8") as f:
        f.write(f"source: {source}\n")
        f.write(f"written: {datetime.now().isoformat(timespec='seconds')}\n\n")
        f.write(f"inserted {len(groups['new'])} new row(s)\n")
        for row in groups["new"]:
            f.write(f"  NEW  {row['company']} — {row['position_title']}\n")
        f.write(f"\nupdated {len(groups['updates'])} existing row(s)\n")
        for row, match, updates in groups["updates"]:
            f.write(f"  UPDT {match['company']} / {match.get('date_added')} — "
                    f"{match.get('position_title')}\n")
            for col in sorted(updates):
                before = (match.get(col) or "")[:60]
                after = (updates[col] or "")[:60]
                f.write(f"         {col}: {before!r} -> {after!r}\n")
        if groups["archived"]:
            f.write(f"\nskipped {len(groups['archived'])} archived match(es)\n")
            for row, match in groups["archived"]:
                f.write(f"  ARCH {match['company']} — {match.get('position_title')}\n")
        if groups["ambiguous"]:
            f.write(f"\nrefused {len(groups['ambiguous'])} ambiguous match(es)\n")
            for row, candidates in groups["ambiguous"]:
                f.write(f"  AMBG {row['company']} — {row['position_title']} "
                        f"({len(candidates)} candidates)\n")
    return dest


def archive_and_clear(path: str) -> str:
    """Copy the inbox to a timestamped archive file, then reset it to an empty array."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    dest = os.path.join(ARCHIVE_DIR, f"applied_inbox_{stamp}.json")
    shutil.copy2(path, dest)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[]\n")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json_file", nargs="?", default=INBOX_PATH,
                    help=f"Export JSON to parse (default: {os.path.relpath(INBOX_PATH)})")
    ap.add_argument("--write", action="store_true",
                    help="Upsert parsed rows into data/jobs.db (default is a dry-run preview)")
    ap.add_argument("--all", action="store_true", dest="include_unsubmitted",
                    help="Include records where the application was not submitted")
    ap.add_argument("--skip-existing", action="store_true",
                    help="do not merge into rows already in the tracker; report and ignore them")
    ap.add_argument("--json", dest="json_out", metavar="PATH",
                    help="Write the parsed tracker rows to PATH as JSON")
    ap.add_argument("--clear", action="store_true",
                    help="After a successful --write, archive the input file and empty it")
    ap.add_argument("--cutoff", action="store_true",
                    help="Print the submission date an incremental capture can stop at, "
                         "then exit")
    args = ap.parse_args()

    if args.cutoff:
        cutoff = incremental_cutoff(get_all_jobs(include_archived=True))
        if cutoff:
            print(cutoff)
        else:
            print("No imported applications yet -- capture everything.", file=sys.stderr)
        return 0

    if not os.path.exists(args.json_file):
        print(f"No such file: {args.json_file}", file=sys.stderr)
        if args.json_file == INBOX_PATH:
            print("Paste the export into that file first (create it with '[]' if missing).",
                  file=sys.stderr)
        return 1

    with open(args.json_file, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"{args.json_file} is not valid JSON: {e}", file=sys.stderr)
            return 1
    if isinstance(data, dict):
        data = data.get("data") or data.get("results") or data.get("matches") or [data]
    if not isinstance(data, list):
        print("Expected a JSON array of records.", file=sys.stderr)
        return 1

    if not data:
        print(f"{os.path.relpath(args.json_file)} is empty — nothing to parse.")
        return 0

    result = parse_export(data, include_unsubmitted=args.include_unsubmitted)
    groups = classify_rows(result["rows"])
    if args.skip_existing:
        # Opt out of merging: matched rows revert to being reported and ignored.
        groups["unchanged"] += groups["updates"]
        groups["updates"] = []
    _print_report(result, groups)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump([{c: r[c] for c in COLUMNS} for r in result["rows"]], f, indent=2)
        print(f"Wrote {len(result['rows'])} row(s) to {args.json_out}")

    if not args.write:
        print("Dry run — nothing written. Re-run with --write to add these to the tracker.")
        if args.clear:
            print("(--clear only takes effect alongside --write; the input file is untouched.)")
        return 0

    # One connection for the whole write pass. upsert_jobs and update_job_fields
    # each open their own otherwise, and against Turso that is ~84ms apiece --
    # 8.5s of pure connecting on a 101-row import, dwarfing the writes. New rows
    # are batched for the same reason: a round trip per row is what made a
    # 2,023-row import take over ten minutes.
    updated = 0
    with shared_connection(create=True):
        upsert_jobs(groups["new"])

        # Address each update to the key of the row we FOUND, never the key implied
        # by the incoming record: date_added comes from ApplyPass's datetime_matched,
        # which drifts when a job is re-matched, and keying off it made INSERT OR
        # REPLACE miss the row and insert a duplicate carrying the same link.
        for _row, match, updates in groups["updates"]:
            if update_job_fields(match["company"], match.get("date_added") or "", updates,
                                 position_title=match.get("position_title"),
                                 link=match.get("link")):
                updated += 1

    # Name the database actually written to: with TURSO_DATABASE_URL set this
    # is the cloud DB, and reporting the local path there is how you end up
    # verifying a row delta against a file nothing touched.
    target = "Turso" if _use_libsql() else "data/jobs.db"
    print(f"Wrote {len(groups['new'])} new row(s) and updated {updated} existing row(s) "
          f"in {target} ({len(groups['unchanged'])} unchanged, "
          f"{len(groups['archived'])} archived match(es) skipped, "
          f"{len(groups['ambiguous'])} ambiguous)")
    log = write_merge_log(groups, args.json_file)
    print(f"Merge log: {os.path.relpath(log)}")

    if args.clear:
        dest = archive_and_clear(args.json_file)
        print(f"Archived input to {os.path.relpath(dest)} and emptied "
              f"{os.path.relpath(args.json_file)} — ready for the next export.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
