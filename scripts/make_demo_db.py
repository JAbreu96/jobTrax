"""Build a scrubbed local copy of the tracker, for the README screenshots.

The screenshots need a database that looks like a real job search, because the
insights page hides most of what it computes below a minimum sample: funnel
percentages need 30 rows in the stage above, interview rates need 8 rounds,
"ghosted" needs 15 days of silence. A handful of invented rows screenshots as a
page full of blanks.

So this reads the real tracker and scrubs the parts that identify anyone else.
Kept: company, title, location, status, dates, links, and every interview -- the
shape of the funnel is the thing worth showing, and it has to be true.
Replaced: recruiter names and emails, the contacts column, notes, follow-up logs
and message subjects. Those are other people's details, and the screenshots go
in a public README.

Deterministic: a fixed seed, so re-running reproduces the same screenshots
rather than silently changing them under a committed image.

    # read the live tracker, write a scrubbed local copy
    python3 scripts/make_demo_db.py

    # then, pointed at the copy:
    TURSO_DATABASE_URL="" TURSO_AUTH_TOKEN="" JOBS_DB=data/demo.db \
        python3 src/jobs_gui.py

Writing to the live database is impossible here: the destination is opened only
after TURSO_DATABASE_URL is forced empty, and the source connection is read-only
by construction (nothing but SELECT is ever issued against it).
"""

import os
import random
import sqlite3
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)

DEST = os.path.join(REPO, "data", "demo.db")
SEED = 20260909

FIRST = [
    "Avery", "Blake", "Cameron", "Dana", "Elliot", "Frankie", "Gray", "Harper",
    "Indigo", "Jules", "Kai", "Logan", "Marlow", "Nico", "Onyx", "Parker",
    "Quinn", "Reese", "Sage", "Tatum", "Umber", "Vale", "Wren", "Yuki",
]
LAST = [
    "Alder", "Brooks", "Calder", "Devlin", "Ellery", "Fenwick", "Garro",
    "Hollis", "Ibarra", "Jessop", "Karas", "Linden", "Mercer", "Novak",
    "Orsini", "Pike", "Quill", "Rowe", "Salter", "Thorne", "Vance", "Whitlock",
]
AGENCIES = [
    "Northwind Talent", "Beacon Search", "Kestrel Partners", "Lantern Recruiting",
    "Vantage Staffing", "Ridgeline Talent", "Copperfield Search", "",
]
NOTES = [
    "Referred by a former colleague.",
    "Applied through the careers page; no ATS confirmation.",
    "Recruiter reached out first.",
    "Role reposted after two weeks.",
    "Team looked strong on the eng blog.",
    "",
    "",
]
SUBJECTS = [
    "Quick intro", "Following up", "Role at your company",
    "Re: Quick intro", "Availability this week", "Next steps",
]


def _person(rng):
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def _email(name, rng):
    handle = name.lower().replace(" ", ".")
    return f"{handle}@example.com"


def read_source():
    """SELECT everything from whatever database the environment points at."""
    from src import jobs_db

    print(f"reading from {'Turso (cloud)' if jobs_db._use_libsql() else jobs_db.DB_PATH}")
    conn = jobs_db._connect()
    if conn is None:
        sys.exit("no source database found")

    tables = {}
    for table in ("jobs", "interviews", "recruiters", "recruiter_jobs",
                  "recruiter_messages"):
        try:
            cur = conn.execute(f"SELECT * FROM {table}")
            cols = [d[0] for d in cur.description]
            # Index by name, not tuple(row): the libSQL shim yields mapping-like
            # rows, so tuple() hands back the column *names* and every value in
            # the copy silently becomes its own header.
            tables[table] = (cols, [tuple(r[c] for c in cols) for r in cur.fetchall()])
        except Exception as exc:                      # table may not exist yet
            print(f"  skipping {table}: {exc}")
            tables[table] = ([], [])
        else:
            print(f"  {table}: {len(tables[table][1])} rows")
    return tables


def scrub(tables, rng):
    """Replace the columns that identify someone other than the repo owner."""
    out = {}

    def blank(table, names):
        cols, rows = tables[table]
        idx = {c: i for i, c in enumerate(cols)}
        new_rows = []
        for row in rows:
            row = list(row)
            for name, make in names.items():
                if name in idx:
                    row[idx[name]] = make(row[idx[name]])
            new_rows.append(tuple(row))
        out[table] = (cols, new_rows)

    def _contact(v):
        if not v:
            return ""
        name = _person(rng)
        return f"{name} <{_email(name, rng)}>"

    blank("jobs", {
        "contacts": _contact,
        "notes": lambda v: (rng.choice(NOTES) if v else ""),
        "followup_log": lambda v: ("Followed up once." if v else ""),
    })

    # Interviews carry no third-party detail beyond free-text notes.
    blank("interviews", {"notes": lambda v: ("Went well." if v else "")})

    # Recruiters are entirely other people. Identity is the key the rest of the
    # schema joins on, so it has to stay internally consistent: one generated
    # person per real id, reused everywhere that id appears.
    cols, rows = tables["recruiters"]
    idx = {c: i for i, c in enumerate(cols)}
    new_rows = []
    for row in rows:
        row = list(row)
        name = _person(rng)
        # Suffix with the real row id before generating the address. Without it
        # two generated people collide on UNIQUE(source, identity) and the
        # INSERT OR REPLACE quietly merges them -- 77 recruiters became 72,
        # which would have put a wrong coverage count in a screenshot.
        tag = row[idx["id"]] if "id" in idx else rng.randrange(10**6)
        if "name" in idx:
            row[idx["name"]] = name
        handle = f"{name.lower().replace(' ', '.')}.{tag}@example.com"
        if "email" in idx and row[idx["email"]]:
            row[idx["email"]] = handle
        if "identity" in idx and row[idx["identity"]]:
            row[idx["identity"]] = handle
        if "agency" in idx and row[idx["agency"]]:
            row[idx["agency"]] = rng.choice(AGENCIES)
        if "agency_domain" in idx and row[idx["agency_domain"]]:
            row[idx["agency_domain"]] = "example.com"
        if "notes" in idx:
            row[idx["notes"]] = ""
        new_rows.append(tuple(row))
    out["recruiters"] = (cols, new_rows)

    out["recruiter_jobs"] = tables["recruiter_jobs"]

    blank("recruiter_messages", {
        "subject": lambda v: (rng.choice(SUBJECTS) if v else ""),
        "message_id": lambda v: "",
        "thread_id": lambda v: "",
    })
    return out


def write_dest(tables):
    """Create data/demo.db with the current schema and fill it."""
    # Forced empty, not unset: jobs_db calls load_dotenv(override=False), so an
    # absent key gets refilled from .env and reconnects to the live database.
    os.environ["TURSO_DATABASE_URL"] = ""
    os.environ["TURSO_AUTH_TOKEN"] = ""

    from src import jobs_db

    assert not jobs_db._use_libsql(), "refusing to write: still pointed at the cloud"

    if os.path.exists(DEST):
        os.remove(DEST)
    os.makedirs(os.path.dirname(DEST), exist_ok=True)

    jobs_db.DB_PATH = DEST
    jobs_db._reset_schema_cache()
    conn = jobs_db._connect(create=True)

    for table, (cols, rows) in tables.items():
        if not rows:
            continue
        placeholders = ",".join("?" for _ in cols)
        names = ",".join(cols)
        conn.executemany(
            f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({placeholders})",
            rows,
        )
        print(f"  wrote {len(rows)} -> {table}")
    conn.commit()
    conn.close()
    print(f"\n{DEST}")


def main():
    rng = random.Random(SEED)
    tables = read_source()
    write_dest(scrub(tables, rng))


if __name__ == "__main__":
    main()
