#!/usr/bin/env python3
"""
One-off backfill: date the applications that were never dated.

date_applied used to be written only by the GUI, on the exact transition to
"Applied" (see jobs_db.update_status for the full history). Every other writer
left it blank, so rows advanced by inbox-triage -- and rows moved straight to a
screening status -- kept it empty forever. Because the application funnel nests
each stage inside the one above it, those rows fell out of every stage below
"applied": the insights page reported 7 jobs at a screen when 33 had reached one.

jobs_db.update_status now maintains the invariant going forward. This script
repairs the rows that predate the fix.

The value used is the row's own date_added: the only evidence available, a true
lower bound (no logged interview round predates it), and honest with the silence
thresholds in a way that stamping today would not be.

Targets rows by the full four-column key, never a partial one, so it cannot
touch a sibling role that happens to share a company and date.

    python3 scripts/backfill_date_applied.py           # dry run, prints the plan
    python3 scripts/backfill_date_applied.py --apply   # writes
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import jobs_db  # noqa: E402


def rows_needing_a_date(rows: list[dict]) -> list[dict]:
    """Rows whose status implies an application that carries no date."""
    return [
        r for r in rows
        if (r.get("status") or "").strip() in jobs_db.APPLIED_STATUSES
        and not (r.get("date_applied") or "").strip()
        and (r.get("date_added") or "").strip()
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the changes; without it this only prints the plan")
    args = ap.parse_args()

    live = jobs_db._use_libsql()
    with jobs_db.shared_connection():
        targets = rows_needing_a_date(jobs_db.get_all_jobs(include_archived=True))

    print(f"database: {'LIVE (Turso)' if live else 'local data/jobs.db'}")
    print(f"rows to backfill: {len(targets)}\n")
    print(f"{'company':32} {'status':14} {'date_applied :=':15}")
    for r in sorted(targets, key=lambda x: (x["status"], x["date_added"])):
        print(f"{r['company'][:31]:32} {r['status']:14} {r['date_added']:15}")

    if not targets:
        return 0
    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to write.")
        return 0

    written = 0
    for r in targets:
        if jobs_db.update_field(r["company"], r["date_added"], "date_applied",
                                r["date_added"], r["position_title"], r["link"]):
            written += 1

    print(f"\nwrote {written} of {len(targets)} rows")
    with jobs_db.shared_connection():
        left = rows_needing_a_date(jobs_db.get_all_jobs(include_archived=True))
    print(f"rows still violating the invariant: {len(left)}")
    return 0 if written == len(targets) and not left else 1


if __name__ == "__main__":
    raise SystemExit(main())
