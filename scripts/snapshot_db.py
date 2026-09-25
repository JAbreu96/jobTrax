"""
Dump the configured database to a .sql file, and refuse to produce a bad one.

CLAUDE.md tells you to snapshot before a schema change with:

    turso db shell job-tracker ".dump" > data/turso-snapshot-$(date ...).sql

That command has a failure mode worth taking seriously: when the CLI's session
has expired it prints

    You are not logged in, please login with turso auth login ...

to *stdout* and exits *0*. The redirect captures the sentence, the shell
reports success, and you are left holding an 89-byte file named like a backup.
The next person to need it discovers this at the worst possible moment.

This reads through jobs_db instead, so it uses the same credentials the
application already has -- no separate CLI login to expire -- and it verifies
what it wrote before leaving the file in place. A snapshot that cannot be
verified is deleted rather than kept, because a missing backup is an honest
state and a fake one is not.

Usage:
    python scripts/snapshot_db.py                    # data/turso-snapshot-<ts>.sql
    python scripts/snapshot_db.py --out path.sql
"""

import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import jobs_db  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")

# A real dump of this tracker is megabytes. Anything this small means the dump
# produced schema and no rows, which is the failure this script exists to catch.
MIN_PLAUSIBLE_BYTES = 4096


def _literal(value) -> str:
    """One value as a SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, bytes):
        return "X'" + value.hex() + "'"
    return "'" + str(value).replace("'", "''") + "'"


def _tables(conn) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [(dict(r)["name"], dict(r)["sql"]) for r in rows]


def dump(conn, out) -> dict:
    """Write the dump; return {table: row_count}."""
    counts = {}
    out.write("BEGIN TRANSACTION;\n")
    for name, create_sql in _tables(conn):
        out.write(f"{create_sql};\n")
        rows = conn.execute(f'SELECT * FROM "{name}"').fetchall()
        counts[name] = len(rows)
        for row in rows:
            data = dict(row)
            cols = ",".join(f'"{c}"' for c in data)
            vals = ",".join(_literal(v) for v in data.values())
            out.write(f'INSERT INTO "{name}" ({cols}) VALUES ({vals});\n')
    # Indexes after the data: recreating them per-row on restore is slower and
    # buys nothing, and a UNIQUE index added before its rows would reject a
    # dump that the source database considered valid.
    for r in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' "
            "AND sql IS NOT NULL ORDER BY name").fetchall():
        out.write(f"{dict(r)['sql']};\n")
    out.write("COMMIT;\n")
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="output path (default: data/turso-snapshot-<timestamp>.sql)")
    args = ap.parse_args()

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = args.out or os.path.join(REPO_ROOT, "data", f"turso-snapshot-{stamp}.sql")
    path = os.path.abspath(path)

    conn = jobs_db._connect()
    if conn is None:
        print("No database to snapshot.", file=sys.stderr)
        return 1

    target = "Turso (LIVE)" if jobs_db._use_libsql() else jobs_db.DB_PATH
    print(f"source: {target}")
    try:
        with open(path, "w") as out:
            counts = dump(conn, out)
    finally:
        conn.close()

    size = os.path.getsize(path)
    for name, n in sorted(counts.items()):
        print(f"  {name:<22} {n:>6} row(s)")
    print(f"\n{path}  ({size / 1024:.0f} KB)")

    # The whole point: verify, and refuse to leave a file that misrepresents
    # itself as a backup.
    problems = []
    if size < MIN_PLAUSIBLE_BYTES:
        problems.append(f"only {size} bytes")
    if not counts:
        problems.append("no tables found")
    if counts.get("jobs", 0) == 0:
        problems.append("the jobs table dumped zero rows")
    if problems:
        os.remove(path)
        print(f"\nSNAPSHOT REJECTED and deleted: {'; '.join(problems)}.",
              file=sys.stderr)
        return 1

    print("verified: non-empty, jobs rows present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
