"""
List child rows whose job key matches no job, so they can be judged one by one.

`interviews` and `recruiter_jobs` copy the jobs primary key in rather than
referencing it, and nothing at the database level keeps them in step. Renaming
a company moved the parent and left the children behind; a census on
2026-09-24 found 5 orphaned interviews and 3 orphaned recruiter links already
in the live database. They are invisible in the GUI because every read joins
on the key, so a lost interview round looks exactly like one that never
happened.

api_update_job now carries children through a rename, so the set below should
stop growing. This reports what is already stranded.

Read-only, deliberately. There is no --fix: the only way to reattach an orphan
is to guess which job it belonged to, and a wrong guess silently files an
interview under the wrong company -- worse than leaving it orphaned, because
it looks like data rather than absence. The near-miss candidates are printed
to make a human decision cheap, not to make it automatic.

Usage:
    python scripts/report_orphaned_children.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import jobs_db  # noqa: E402

TABLES = {
    "interviews": ("id", "interview_type", "scheduled_date"),
    "recruiter_jobs": ("id", "recruiter_id", "sourced_date"),
}


def _orphans(conn, table):
    rows = conn.execute(f"""
        SELECT c.* FROM {table} c
         WHERE NOT EXISTS (
               SELECT 1 FROM jobs j
                WHERE j.company        = c.company
                  AND j.date_added     = c.date_added
                  AND j.position_title = c.position_title
                  AND j.link           = c.link)
         ORDER BY c.company
    """).fetchall()
    return [dict(r) for r in rows]


def _candidates(conn, orphan):
    """Jobs at the same company -- the likeliest home, for a human to confirm."""
    rows = conn.execute(
        "SELECT company, date_added, position_title FROM jobs "
        "WHERE company = ? ORDER BY date_added", [orphan["company"]]
    ).fetchall()
    return [dict(r) for r in rows]


def main() -> int:
    conn = jobs_db._connect()
    if conn is None:
        print("No database to read.")
        return 1

    target = "Turso (LIVE)" if jobs_db._use_libsql() else jobs_db.DB_PATH
    print(f"source: {target}\n")
    total = 0
    try:
        for table, extra in TABLES.items():
            orphans = _orphans(conn, table)
            total += len(orphans)
            print(f"{table}: {len(orphans)} orphan(s)")
            for o in orphans:
                detail = "  ".join(f"{k}={o.get(k)!r}" for k in extra if k in o)
                print(f"  - {o['company']!r} / {o['position_title']!r} "
                      f"/ {o['date_added']}")
                print(f"      {detail}")
                near = _candidates(conn, o)
                if near:
                    print(f"      same-company jobs that exist: "
                          f"{', '.join(repr(c['position_title']) for c in near)}")
                else:
                    print("      no job at that company at all -- "
                          "the company was renamed, or the job was deleted")
            print()
        print(f"{total} orphaned row(s) total.")
        if total:
            print("Reattach or delete these by hand; see the module docstring "
                  "for why this script will not guess.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
