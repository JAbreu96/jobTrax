"""
A sheet sync must not un-archive rows.

`archived` lives on the `jobs` table but not in the sheet, so it is absent from
sync_jobs_to_sqlite.COLUMNS. INSERT OR REPLACE is delete-then-insert, which means
writing only COLUMNS puts the column back at its DEFAULT 0 — silently clearing
the archive flag on every row the sheet still carries. 204 rows were exposed to
this in the live DB.

These tests drive the real sync() loop with the Sheets fetch stubbed out, so they
exercise the actual INSERT statement rather than a re-creation of it.
"""

import importlib
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src import jobs_db  # noqa: E402

sync_mod = importlib.import_module("scripts.sync_jobs_to_sqlite")


# Sheet column order is COLUMNS: company, position_title, job_summary, location,
# link, date_added, contacts, notes, outreach_date, date_applied, status,
# followup_log.
def _sheet_row(company, title="Engineer", link="http://x/1", added="2026-01-01",
               status="Applied"):
    return [company, title, "", "", link, added, "", "", "", "", status, ""]


@pytest.fixture
def synced(tmp_path, monkeypatch):
    """Runs sync() against a temp DB with a caller-supplied set of sheet rows."""
    db_path = str(tmp_path / "jobs.db")
    monkeypatch.setattr(sync_mod, "DB_PATH", db_path)
    monkeypatch.setattr(jobs_db, "DB_PATH", db_path)

    def run(rows):
        monkeypatch.setattr(sync_mod, "get_sheet_rows", lambda: rows)
        sync_mod.sync()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    run.db_path = db_path
    return run


def _archive(db_path, company):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE jobs SET archived = 1 WHERE company = ?", (company,))
    conn.commit()
    conn.close()


def test_sync_preserves_archived_flag(synced):
    """The regression: an archived row that is still in the sheet stays archived."""
    rows = [_sheet_row("Acme")]
    synced(rows).close()
    _archive(synced.db_path, "Acme")

    conn = synced(rows)
    archived = conn.execute("SELECT archived FROM jobs WHERE company = 'Acme'").fetchone()[0]
    conn.close()
    assert archived == 1, "sheet sync cleared the archive flag"


def test_sync_preserves_archived_across_many_rows(synced):
    """Only the archived rows keep the flag; the rest stay at 0."""
    rows = [_sheet_row(f"Co{i}", link=f"http://x/{i}") for i in range(5)]
    synced(rows).close()
    _archive(synced.db_path, "Co1")
    _archive(synced.db_path, "Co3")

    conn = synced(rows)
    flags = {r["company"]: r["archived"]
             for r in conn.execute("SELECT company, archived FROM jobs")}
    conn.close()
    assert flags == {"Co0": 0, "Co1": 1, "Co2": 0, "Co3": 1, "Co4": 0}


def test_sync_defaults_new_rows_to_unarchived(synced):
    """A row the DB has never seen has no prior value to carry forward."""
    conn = synced([_sheet_row("Fresh")])
    archived = conn.execute("SELECT archived FROM jobs WHERE company = 'Fresh'").fetchone()[0]
    conn.close()
    assert archived == 0


def test_sync_refuses_to_run_against_turso(monkeypatch):
    """The guard: this script only ever writes the local file, so it must not
    run at all once Turso is the real store -- silently succeeding would just
    repeat the 153-row split-brain this script caused once already."""
    monkeypatch.setattr(jobs_db, "_use_libsql", lambda: True)
    with pytest.raises(RuntimeError, match="TURSO_DATABASE_URL"):
        sync_mod.sync()


def test_sync_still_updates_the_other_columns(synced):
    """
    Guards the fix itself: carrying `archived` forward must not turn the write
    into a no-op for the columns the sheet does own.
    """
    synced([_sheet_row("Acme", status="Applied")]).close()
    _archive(synced.db_path, "Acme")

    conn = synced([_sheet_row("Acme", status="Rejected")])
    row = conn.execute("SELECT status, archived FROM jobs WHERE company = 'Acme'").fetchone()
    conn.close()
    assert row["status"] == "Rejected"
    assert row["archived"] == 1
