"""The one-off migration that retires statuses outside STATUS_ORDER.

The risky half is not the status rename -- it is the outreach_date backfill.
`Outreached` was carrying a fact (`I began the conversation`) that the schema
has a column for, and on most of those rows the status is the only record of
it. Map the status and stop, and the fact is gone. So these tests care mostly
about which date each row ends up with, and about the rows that must NOT be
touched.

conftest strips TURSO_* for the session, so everything here runs against a
local file.
"""

import importlib.util
import os
import sys

import pytest

from src import jobs_db

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts",
                       "migrate_status_vocabulary.py")


def _load_module():
    """Import the script by path -- scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location("migrate_status_vocabulary", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


migrate = _load_module()


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    jobs_db._reset_schema_cache()
    return tmp_path


def _add(company, status, date_added="2026-01-01", outreach_date="", **extra):
    jobs_db.upsert_job({
        "company": company, "position_title": "Engineer", "link": "",
        "date_added": date_added, "status": status,
        "outreach_date": outreach_date, **extra,
    })


def _status_of(company):
    conn = jobs_db._connect()
    try:
        row = conn.execute(
            "SELECT status, outreach_date FROM jobs WHERE company = ?", [company]
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def _run(write=False):
    argv = ["migrate_status_vocabulary.py"] + (["--write"] if write else [])
    old = sys.argv
    sys.argv = argv
    try:
        return migrate.main()
    finally:
        sys.argv = old


# --- the mapping ------------------------------------------------------------

@pytest.mark.parametrize("old,new", [
    ("Outreached", "Tracking"),
    ("Not Applied", "Tracking"),
    ("Applied & Outreached", "Applied"),
    ("Outreached and Applied", "Applied"),
])
def test_each_legacy_status_maps_to_its_replacement(db, old, new):
    _add("Acme", old)

    _run(write=True)

    assert _status_of("Acme")["status"] == new


def test_a_status_already_in_status_order_is_left_alone(db):
    _add("Acme", "Applied", outreach_date="2026-02-01")

    _run(write=True)

    assert _status_of("Acme") == {"status": "Applied", "outreach_date": "2026-02-01"}


def test_an_unrecognised_status_is_reported_not_guessed(db, capsys):
    """A value nobody has seen before must not be invented a mapping for.

    Silently mapping whatever turns up is how the four legacy values got here.
    """
    _add("Acme", "Ghosted??")

    _run(write=True)

    assert _status_of("Acme")["status"] == "Ghosted??"
    assert "SKIPPED" in capsys.readouterr().out


# --- the outreach_date backfill ---------------------------------------------

def test_outreach_date_is_backfilled_from_date_added_when_there_is_no_message(db):
    _add("Acme", "Outreached", date_added="2026-03-05")

    _run(write=True)

    row = _status_of("Acme")
    assert row["status"] == "Tracking"
    # Not the true date, but the row cannot have been outreached before it
    # existed -- a floor beats a blank.
    assert row["outreach_date"] == "2026-03-05"


def test_outreach_date_prefers_the_earliest_linked_recruiter_message(db):
    _add("Acme", "Outreached", date_added="2026-03-05")
    rid = jobs_db.upsert_recruiter(source="email", identity="r@acme.com",
                                   name="R", email="r@acme.com")
    jobs_db.link_recruiter_job(rid, company="Acme", date_added="2026-03-05",
                               position_title="Engineer", link="",
                               sourced_date="2026-02-20")
    for day, mid in (("2026-02-28", "m2"), ("2026-02-20", "m1")):
        jobs_db.record_recruiter_message(rid, direction="inbound",
                                         occurred_date=day, subject="hi",
                                         account="primary", message_id=mid)

    _run(write=True)

    # The conversation's own date, and the earliest of them -- a later reply
    # is not when outreach started.
    assert _status_of("Acme")["outreach_date"] == "2026-02-20"


def test_an_existing_outreach_date_is_never_overwritten(db):
    _add("Acme", "Outreached", date_added="2026-03-05", outreach_date="2026-01-09")

    _run(write=True)

    assert _status_of("Acme")["outreach_date"] == "2026-01-09"


def test_not_applied_gets_no_invented_outreach_date(db):
    """'Not Applied' claims nothing about a conversation, so there is nothing
    to preserve -- inventing a date here would be fabrication, not rescue."""
    _add("Acme", "Not Applied", date_added="2026-03-05")

    _run(write=True)

    row = _status_of("Acme")
    assert row["status"] == "Tracking"
    assert row["outreach_date"] == ""


# --- safety -----------------------------------------------------------------

def test_dry_run_is_the_default_and_writes_nothing(db, capsys):
    _add("Acme", "Outreached", date_added="2026-03-05")

    assert _run() == 0

    assert _status_of("Acme") == {"status": "Outreached", "outreach_date": ""}
    assert "Dry run" in capsys.readouterr().out


def test_running_twice_changes_nothing_the_second_time(db, capsys):
    _add("Acme", "Outreached", date_added="2026-03-05")
    _run(write=True)
    after_first = _status_of("Acme")

    capsys.readouterr()
    _run(write=True)

    assert _status_of("Acme") == after_first
    # Nothing is left outside the vocabulary, so there is nothing to report.
    assert "0 row(s) outside STATUS_ORDER" in capsys.readouterr().out


def test_only_the_targeted_rows_are_touched(db):
    _add("Acme", "Outreached", date_added="2026-03-05")
    _add("Globex", "Applied", date_added="2026-03-05", outreach_date="")
    _add("Initech", "Rejected", date_added="2026-03-05")

    _run(write=True)

    assert _status_of("Globex") == {"status": "Applied", "outreach_date": ""}
    assert _status_of("Initech") == {"status": "Rejected", "outreach_date": ""}


def test_archived_rows_migrate_too(db):
    """All seven of the rarest legacy values are archived; skipping archived
    rows would leave the vocabulary dirty forever."""
    _add("Acme", "Applied & Outreached", date_added="2026-03-05", archived=1)

    _run(write=True)

    assert _status_of("Acme")["status"] == "Applied"
