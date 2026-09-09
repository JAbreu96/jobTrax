"""
Schema upgrades, exercised from OLD databases.

Every other test builds a database from the CURRENT DDL, so no test could ever
see a migration fail. That gap hid a real one: `interviews.occurred_date` stayed
NOT NULL on the live DB after scheduled rounds were added, because
CREATE TABLE IF NOT EXISTS does not alter an existing table and SQLite cannot
ALTER a column constraint. It surfaced only when a backfill hit the live file.

These tests construct databases at each historical schema, run _ensure_schema()
over them, and assert the upgrade happened without losing anything. They are the
only place the upgrade path is checked at all.
"""

import sqlite3

import pytest

from src import jobs_db


# --- historical schemas, as they actually shipped ---------------------------

JOBS_V1 = """
    CREATE TABLE jobs (
        company TEXT NOT NULL, date_added TEXT NOT NULL DEFAULT '',
        position_title TEXT, link TEXT, job_summary TEXT, location TEXT,
        contacts TEXT, notes TEXT, outreach_date TEXT, date_applied TEXT,
        status TEXT, followup_log TEXT,
        PRIMARY KEY (company, date_added)
    )
"""

JOBS_V2 = """
    CREATE TABLE jobs (
        company TEXT NOT NULL, date_added TEXT NOT NULL DEFAULT '',
        position_title TEXT NOT NULL DEFAULT '', link TEXT,
        job_summary TEXT, location TEXT, contacts TEXT, notes TEXT,
        outreach_date TEXT, date_applied TEXT, status TEXT, followup_log TEXT,
        PRIMARY KEY (company, date_added, position_title)
    )
"""

INTERVIEWS_V1 = """
    CREATE TABLE interviews (
        id INTEGER PRIMARY KEY, company TEXT NOT NULL,
        date_added TEXT NOT NULL DEFAULT '', position_title TEXT NOT NULL DEFAULT '',
        link TEXT NOT NULL DEFAULT '', interview_type TEXT NOT NULL,
        type_label TEXT, loop_id TEXT,
        occurred_date TEXT NOT NULL,
        self_rating INTEGER, notes TEXT
    )
"""


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    """Builds a database at an old schema, then hands back its path."""
    path = str(tmp_path / "jobs.db")
    monkeypatch.setattr(jobs_db, "DB_PATH", path)

    def build(*ddls, rows=(), interview_rows=()):
        conn = sqlite3.connect(path)
        for ddl in ddls:
            conn.execute(ddl)
        for r in rows:
            conn.execute(
                "INSERT INTO jobs (company, date_added, position_title, link, status) "
                "VALUES (?, ?, ?, ?, ?)", r)
        for r in interview_rows:
            conn.execute(
                "INSERT INTO interviews (company, date_added, position_title, link, "
                "interview_type, occurred_date) VALUES (?, ?, ?, ?, ?, ?)", r)
        conn.commit()
        conn.close()
        return path

    build.path = path
    return build


def _pk(path, table):
    conn = sqlite3.connect(path)
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    conn.close()
    return {c[1] for c in cols if c[5]}


def _notnull(path, table, column):
    conn = sqlite3.connect(path)
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    conn.close()
    return any(c[1] == column and c[3] for c in cols)


# --- jobs: the key widened twice --------------------------------------------

def test_v1_two_column_key_widens_to_four(legacy):
    path = legacy(JOBS_V1, rows=[("Acme", "2026-01-01", "Engineer", "http://x/1", "Applied")])
    jobs_db._connect()
    assert _pk(path, "jobs") == set(jobs_db.KEY_COLUMNS)
    assert len(jobs_db.get_all_jobs()) == 1


def test_v2_three_column_key_widens_to_four(legacy):
    path = legacy(JOBS_V2, rows=[("Acme", "2026-01-01", "Engineer", "http://x/1", "Applied")])
    jobs_db._connect()
    assert _pk(path, "jobs") == set(jobs_db.KEY_COLUMNS)


def test_widening_the_key_admits_rows_the_old_one_rejected(legacy):
    """
    The old 3-column key could not hold two requisitions posted under one title —
    the second INSERT was rejected outright, which is why the key was widened.
    The migration cannot recover a row that was never stored; what it must do is
    make the second row storable from now on.
    """
    path = legacy(JOBS_V2, rows=[("Acme", "2026-01-01", "Engineer", "http://x/1", "Applied")])

    conn = sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO jobs (company, date_added, position_title, link, status) "
                     "VALUES ('Acme', '2026-01-01', 'Engineer', 'http://x/2', 'Rejected')")
    conn.close()

    jobs_db._connect()
    for link in ("http://x/1", "http://x/2"):
        jobs_db.upsert_job({
            "company": "Acme", "position_title": "Engineer", "job_summary": "", "location": "",
            "link": link, "date_added": "2026-01-01", "contacts": "", "notes": "",
            "outreach_date": "", "date_applied": "", "status": "Applied", "followup_log": "",
        })
    assert len({j["link"] for j in jobs_db.get_all_jobs()}) == 2


def test_archived_column_is_added_and_defaults_to_zero(legacy):
    """`archived` postdates the original schema; old rows must not be lost to it."""
    legacy(JOBS_V1, rows=[("Acme", "2026-01-01", "Engineer", "http://x/1", "Applied")])
    jobs_db._connect()
    assert jobs_db.get_all_jobs()[0]["archived"] == 0


def test_jobs_migration_is_idempotent(legacy):
    legacy(JOBS_V1, rows=[("Acme", "2026-01-01", "Engineer", "http://x/1", "Applied")])
    for _ in range(3):
        jobs_db._reset_schema_cache()  # force the migration to actually re-run
        jobs_db._connect()
    assert len(jobs_db.get_all_jobs()) == 1


def test_the_list_order_is_read_from_an_index_not_sorted_by_hand(legacy):
    """
    idx_jobs_list is the whole reason the list query got faster, and nothing else
    would notice if it stopped being used -- the results stay correct, they just
    cost a scan and a sort of every row. Assert on the plan, because the wrong
    index still returns the right answer.
    """
    path = legacy(JOBS_V1, rows=[("Acme", "2026-01-01", "Engineer", "http://x/1", "Applied")])
    jobs_db._connect()

    conn = sqlite3.connect(path)
    cols = ", ".join(jobs_db.LIST_COLUMNS)
    plan = " ".join(
        str(r[3]) for r in conn.execute(
            f"EXPLAIN QUERY PLAN SELECT {cols} FROM jobs WHERE archived = 0 "
            "ORDER BY date_added DESC, company, position_title, link"
        ).fetchall()
    )
    conn.close()

    assert "idx_jobs_list" in plan, plan
    assert "TEMP B-TREE" not in plan.upper(), plan


# --- interviews: occurred_date became nullable ------------------------------

def test_occurred_date_notnull_is_dropped(legacy):
    """The exact failure that reached the live database."""
    path = legacy(JOBS_V2, INTERVIEWS_V1,
                  interview_rows=[("Acme", "2026-01-01", "Engineer", "http://x/1",
                                   "technical", "2026-02-01")])
    assert _notnull(path, "interviews", "occurred_date")  # precondition
    jobs_db._connect()
    assert not _notnull(path, "interviews", "occurred_date")


def test_migrating_interviews_preserves_every_round(legacy):
    """These rounds cannot be rebuilt from anywhere. Losing one is unrecoverable."""
    legacy(JOBS_V2, INTERVIEWS_V1, interview_rows=[
        ("Acme", "2026-01-01", "Engineer", "http://x/1", "technical", "2026-02-01"),
        ("Acme", "2026-01-01", "Engineer", "http://x/1", "behavioral", "2026-02-08"),
    ])
    jobs_db._connect()
    rounds = jobs_db.get_interviews()
    assert len(rounds) == 2
    assert {r["occurred_date"] for r in rounds} == {"2026-02-01", "2026-02-08"}


def test_a_booking_can_be_inserted_after_migrating(legacy):
    """
    The end-to-end regression. Before the migration this raised
    'NOT NULL constraint failed: interviews.occurred_date' on a real database
    while passing every test, because tests never started from the old schema.
    """
    legacy(JOBS_V2, INTERVIEWS_V1)
    jobs_db.upsert_job({
        "company": "Acme", "position_title": "Engineer", "job_summary": "", "location": "",
        "link": "http://x/1", "date_added": "2026-01-01", "contacts": "", "notes": "",
        "outreach_date": "", "date_applied": "", "status": "Phone Screen", "followup_log": "",
    })
    jobs_db.add_interview(company="Acme", date_added="2026-01-01",
                          position_title="Engineer", link="http://x/1",
                          interview_type="phone_screen", scheduled_date="2026-12-01")
    assert len(jobs_db.upcoming_interviews()) == 1


def test_interviews_migration_is_idempotent(legacy):
    legacy(JOBS_V2, INTERVIEWS_V1, interview_rows=[
        ("Acme", "2026-01-01", "Engineer", "http://x/1", "technical", "2026-02-01")])
    for _ in range(3):
        jobs_db._reset_schema_cache()  # force the migration to actually re-run
        jobs_db._connect()
    assert len(jobs_db.get_interviews()) == 1


def test_a_fresh_database_needs_no_migration(legacy):
    """The new-install path must not depend on any migration running."""
    jobs_db._connect(create=True)
    assert not _notnull(legacy.path, "interviews", "occurred_date")
    assert _pk(legacy.path, "jobs") == set(jobs_db.KEY_COLUMNS)
