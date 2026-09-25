"""
Retire the status values that no ordering code can place.

`STATUS_ORDER` is the vocabulary every ranking path in this repo assumes, and
`status_rank()` deliberately returns -1 for anything outside it so an unknown
status never counts as forward progress. 51 rows carry values that were never
in that list:

    Outreached              44
    Not Applied              4
    Applied & Outreached     2
    Outreached and Applied   1

Every one of them scores -1, so they sit outside the funnel, outside
`APPLIED_STATUSES`, and -- once the job view grows a status timeline -- would
render with nothing reached at all. `Outreached` alone is more common than
`Phone Screen`.

The mapping, and why it is not a straight rename:

`Outreached` means "I began the conversation". That is what `outreach_date`
exists to record, so the status was carrying a fact the schema already has a
column for. Mapping it to `Tracking` and stopping would erase that fact: of the
44 rows, only a handful have an `outreach_date` set, so for most of them the
status IS the only evidence. So this backfills `outreach_date` first, then
moves the status.

Evidence for the backfilled date, best first:
  1. the earliest recruiter message on a recruiter linked to that exact job --
     a real date, from the conversation itself;
  2. `date_added`, as a floor. Not the true date, but the row cannot have been
     outreached before it existed, and a date that is too early is a smaller
     lie than a blank.
Rows that already have an `outreach_date` are left alone.

`Not Applied` -> `Tracking` (saved, never applied). The two combined variants
mean both things happened, and applying is the further state, so they go to
`Applied` and take the same outreach backfill.

This writes to whatever database jobs_db is pointed at, which is Turso unless
TURSO_* are empty. Snapshot before --write:

    turso db shell job-tracker ".dump" > data/turso-snapshot-$(date +%Y%m%d-%H%M%S).sql

Usage:
    python scripts/migrate_status_vocabulary.py            # dry run (default)
    python scripts/migrate_status_vocabulary.py --write
"""

import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import jobs_db  # noqa: E402
from src.jobs_db import STATUS_ORDER  # noqa: E402

KEY = ("company", "date_added", "position_title", "link")

# Only these are migrated. A status outside STATUS_ORDER that is not in this
# map is reported and skipped rather than guessed at -- a new unknown value
# means someone typed something new, and inventing a mapping for it silently is
# how the four below came to exist in the first place.
MAPPING = {
    "Outreached": "Tracking",
    "Not Applied": "Tracking",
    "Applied & Outreached": "Applied",
    "Outreached and Applied": "Applied",
}

# The subset whose status asserts outreach happened. "Not Applied" says nothing
# about a conversation, so it gets no backfilled date.
ASSERTS_OUTREACH = {"Outreached", "Applied & Outreached", "Outreached and Applied"}


def _rows_to_migrate(conn):
    """Every row whose status is outside STATUS_ORDER, with outreach evidence.

    The recruiter join is LEFT: most of these rows have no linked recruiter,
    and they still need migrating. Matched on the four key columns copied into
    recruiter_jobs rather than a foreign key, because there isn't one -- see
    _ensure_recruiters_schema's docstring for why the key is copied in.
    """
    placeholders = ",".join("?" for _ in STATUS_ORDER)
    sql = f"""
        SELECT j.company, j.date_added, j.position_title, j.link,
               j.status, j.outreach_date, j.date_applied, j.archived,
               MIN(m.occurred_date) AS first_message
          FROM jobs j
          LEFT JOIN recruiter_jobs rj
                 ON rj.company        = j.company
                AND rj.date_added     = j.date_added
                AND rj.position_title = j.position_title
                AND rj.link           = j.link
          LEFT JOIN recruiter_messages m
                 ON m.recruiter_id = rj.recruiter_id
         WHERE j.status NOT IN ({placeholders})
      GROUP BY j.company, j.date_added, j.position_title, j.link,
               j.status, j.outreach_date, j.date_applied, j.archived
      ORDER BY j.status, j.company
    """
    return [dict(r) for r in conn.execute(sql, list(STATUS_ORDER)).fetchall()]


def plan_row(row: dict) -> dict | None:
    """What this row becomes, or None if its status isn't one we migrate."""
    old = (row.get("status") or "").strip()
    new = MAPPING.get(old)
    if new is None:
        return None

    outreach = (row.get("outreach_date") or "").strip()
    if outreach or old not in ASSERTS_OUTREACH:
        # Already dated, or the status never claimed a conversation happened.
        date, evidence = outreach, "kept" if outreach else "n/a"
    elif (row.get("first_message") or "").strip():
        date, evidence = row["first_message"].strip(), "recruiter message"
    else:
        date, evidence = (row.get("date_added") or "").strip(), "date_added (floor)"

    return {
        **{k: row[k] for k in KEY},
        "old_status": old,
        "new_status": new,
        "old_outreach": outreach,
        "new_outreach": date,
        "evidence": evidence,
        "archived": row.get("archived"),
    }


def apply_row(conn, change: dict) -> None:
    """One UPDATE, addressed by the full composite key.

    Deliberately raw SQL rather than jobs_db.update_status(): that helper
    refuses to move a row backwards and stamps date_applied as a side effect,
    both of which are right for an interactive edit and wrong for a migration,
    where the mapping above is the whole intent and nothing should happen that
    isn't written down here.
    """
    conn.execute(
        "UPDATE jobs SET status = ?, outreach_date = ? "
        "WHERE company = ? AND date_added = ? AND position_title = ? AND link = ?",
        [change["new_status"], change["new_outreach"],
         change["company"], change["date_added"],
         change["position_title"], change["link"]],
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help="apply the changes (default is a dry run that writes nothing)")
    args = ap.parse_args()

    conn = jobs_db._connect()
    if conn is None:
        print("No database to read.")
        return 1

    target = "Turso (LIVE)" if jobs_db._use_libsql() else "data/jobs.db"
    try:
        rows = _rows_to_migrate(conn)
        changes, unknown = [], []
        for row in rows:
            planned = plan_row(row)
            (changes if planned else unknown).append(planned or row)

        print(f"target: {target}   mode: {'WRITE' if args.write else 'DRY RUN'}")
        print(f"{len(rows)} row(s) outside STATUS_ORDER | "
              f"{len(changes)} to migrate | {len(unknown)} unrecognised")
        print()

        if changes:
            width = max(len(c["company"]) for c in changes)
            print(f"{'COMPANY'.ljust(width)}  {'STATUS':<24} -> "
                  f"{'':<8}  OUTREACH_DATE")
            print("-" * (width + 60))
            for c in changes:
                arrow = f"{c['old_status']} -> {c['new_status']}"
                if c["evidence"] in ("kept", "n/a"):
                    date = f"{c['new_outreach'] or '--':<12} ({c['evidence']})"
                else:
                    date = f"{c['new_outreach']:<12} <- {c['evidence']}"
                flag = " [archived]" if c.get("archived") else ""
                print(f"{c['company'].ljust(width)}  {arrow:<34}  {date}{flag}")
            print()

        if unknown:
            print("SKIPPED -- outside STATUS_ORDER and not in MAPPING:")
            for row in unknown:
                print(f"  {row['company']}: {row.get('status')!r}")
            print()

        backfilled = sum(1 for c in changes if c["evidence"] not in ("kept", "n/a"))
        print(f"{len(changes)} status change(s), {backfilled} outreach_date backfill(s)")

        if not args.write:
            print("\nDry run -- nothing written. Re-run with --write to apply.")
            return 0

        if jobs_db._use_libsql():
            print("\nWriting to the LIVE database. Snapshot first if you have not.")
        for change in changes:
            apply_row(conn, change)
        conn.commit()
        print(f"\nWrote {len(changes)} row(s) at "
              f"{datetime.datetime.now().isoformat(timespec='seconds')}.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
