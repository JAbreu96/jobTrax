"""
An interview round has one date: the day it is booked for.

The table used to carry two — `scheduled_date` for a booking and `occurred_date`
for a round that happened — which made three states out of two useful ones. The
third was limbo: booked, the date long past, nobody having promoted it. Nothing
swept for those, so they accumulated. The audit found 24 of them, and because
classify_interviews counts only rounds with an `occurred_date`, the interview
table was running on 13 of 40 rounds with its advance rate one row away from
being withheld entirely.

A round now simply happens on its date. Past it, it happened; before it, it is
booked; if it never happened at all, the row is deleted. `occurred_date` is gone.
"""

import pytest

from datetime import date, timedelta

from src import jobs_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    jobs_db._reset_schema_cache()
    return jobs_db


def _day(offset):
    return (date.today() + timedelta(days=offset)).isoformat()


def _job(db, company, *, status="Phone Screen"):
    key = dict(company=company, date_added="2026-01-01",
               position_title="Engineer", link=f"http://x/{company}")
    db.upsert_job({**key, "job_summary": "", "location": "", "contacts": "",
                   "notes": "", "outreach_date": "", "date_applied": "2026-01-01",
                   "status": status, "followup_log": ""})
    return key


def test_a_round_whose_date_has_passed_counts_as_held(db):
    """The whole point: no promotion step, so nothing can sit in limbo."""
    key = _job(db, "Morgan Stanley")
    db.add_interview(**key, interview_type="phone_screen", scheduled_date=_day(-3))

    assert jobs_db.interview_stats()["totals"]["rounds"] == 1


def test_a_round_still_in_the_future_does_not_count(db):
    key = _job(db, "Sciforium")
    db.add_interview(**key, interview_type="phone_screen", scheduled_date=_day(+3))

    assert jobs_db.interview_stats()["totals"]["rounds"] == 0


def test_a_round_dated_today_is_still_ahead(db):
    """
    Held is strictly past, so "held" and "upcoming" cannot both claim a round.
    Today's round is booked until the day is over -- a 5pm call has not happened
    at 9am, and counting it early would assert an outcome that does not exist.
    """
    key = _job(db, "Usul")
    db.add_interview(**key, interview_type="phone_screen", scheduled_date=_day(0))

    assert jobs_db.interview_stats()["totals"]["rounds"] == 0
    assert len(db.get_upcoming_interviews()) == 1


def test_upcoming_returns_only_rounds_still_ahead(db):
    key = _job(db, "REALM")
    db.add_interview(**key, interview_type="phone_screen", scheduled_date=_day(-2))
    db.add_interview(**key, interview_type="technical", scheduled_date=_day(+2))

    upcoming = db.get_upcoming_interviews()

    assert [r["interview_type"] for r in upcoming] == ["technical"]


def test_no_past_round_is_ever_reported_as_overdue(db):
    """`overdue` described the limbo state, which no longer exists."""
    key = _job(db, "Rivers")
    db.add_interview(**key, interview_type="phone_screen", scheduled_date=_day(-9))

    assert [r for r in db.upcoming_interviews(include_past=True) if r["overdue"]] == []


def test_the_interviews_table_has_no_occurred_date_column(db):
    db.add_interview(**_job(db, "Alma"), interview_type="phone_screen",
                     scheduled_date=_day(-1))
    conn = db._connect()
    try:
        names = [c[1] for c in conn.execute("PRAGMA table_info(interviews)").fetchall()]
    finally:
        conn.close()

    assert "occurred_date" not in names
    assert "scheduled_date" in names


def test_migration_folds_a_held_rounds_real_date_into_scheduled_date(db):
    """
    A rescheduled round holds two different dates. The one that matters is the
    day it actually ran, so occurred_date wins over the booking it drifted from.
    """
    _job(db, "Rescheduled")           # creates the database file
    conn = db._connect()
    try:
        conn.execute("DROP TABLE IF EXISTS interviews")
        conn.execute("""
            CREATE TABLE interviews (
                id INTEGER PRIMARY KEY, company TEXT NOT NULL,
                date_added TEXT NOT NULL DEFAULT '', position_title TEXT NOT NULL DEFAULT '',
                link TEXT NOT NULL DEFAULT '', interview_type TEXT NOT NULL,
                type_label TEXT, loop_id TEXT, scheduled_date TEXT,
                occurred_date TEXT, self_rating INTEGER, notes TEXT)
        """)
        conn.execute(
            "INSERT INTO interviews (company, date_added, position_title, link, "
            "interview_type, scheduled_date, occurred_date) VALUES "
            "('Rescheduled','2026-01-01','Engineer','','technical','2026-02-01','2026-02-09'),"
            "('Booked','2026-01-01','Engineer','','phone_screen','2026-02-03',NULL)"
        )
        conn.commit()
    finally:
        conn.close()
    db._reset_schema_cache()

    rounds = {r["company"]: r for r in db.get_interviews()}

    assert rounds["Rescheduled"]["scheduled_date"] == "2026-02-09"
    assert rounds["Booked"]["scheduled_date"] == "2026-02-03"
