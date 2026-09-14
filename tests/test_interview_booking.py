"""
Booking a round, as opposed to logging one that happened.

`interviews.scheduled_date` existed and was read by the "Coming up" card, but
nothing was allowed to write it: triage was told never to record an unheld
invite, the GUI returned a hard 400 without an occurred_date, and the MCP server
has no interview writer. A confirmed Morgan Stanley booking therefore sat in
free-text `notes` while the card showed every other screen.

The load-bearing test here is `test_a_booked_round_cannot_move_a_rate`. Lifting
the triage ban is only safe because classify_interviews() drops booked-but-unheld
rounds before any statistic sees them, so that guarantee is asserted rather than
trusted -- if it ever stops holding, the ban had a reason again.
"""

import datetime
import importlib.util
import os
import sys

import pytest

from src import jobs_db, jobs_gui

_spec = importlib.util.spec_from_file_location(
    "bfi", os.path.join(os.path.dirname(__file__), "..", "scripts", "backfill_interviews.py"))
bfi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bfi)

TODAY = datetime.date.today()
SOON = (TODAY + datetime.timedelta(days=9)).isoformat()

JOB = {"company": "Morgan Stanley", "position_title": "AI Integration Engineer",
       "link": "https://example.test/ms", "date_added": "2026-08-20"}
KEY = {k: JOB[k] for k in ("company", "date_added", "position_title", "link")}


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    jobs_db._reset_schema_cache()
    jobs_db.upsert_job(dict(JOB, status="Phone Screen"))
    return jobs_db


@pytest.fixture
def client(db):
    jobs_gui.app.config["TESTING"] = True
    with jobs_gui.app.test_client() as c:
        yield c


# --- the GUI accepts a booking ----------------------------------------------

def _post(client, **over):
    body = dict(KEY, interview_type="phone_screen")
    body.update(over)
    return client.post("/api/interviews/add", json=body)


def test_a_booking_is_accepted(client):
    assert _post(client, scheduled_date=SOON).status_code == 200


def test_a_held_round_is_still_accepted(client):
    """The path that already worked must keep working."""
    assert _post(client, occurred_date="2026-08-20").status_code == 200


def test_neither_date_is_rejected(client):
    """A round that is neither booked nor held is not an event."""
    res = _post(client)
    assert res.status_code == 400
    assert "required" in res.get_json()["error"]


def test_both_dates_are_rejected(client):
    """
    upcoming_interviews() reads an occurred_date as done, so a row carrying both
    claims to be simultaneously booked and held -- and vanishes from the card it
    was meant to appear on.
    """
    res = _post(client, occurred_date="2026-08-20", scheduled_date=SOON)
    assert res.status_code == 400
    assert "not both" in res.get_json()["error"]


def test_a_booking_reaches_the_coming_up_card(db, client):
    _post(client, scheduled_date=SOON)
    assert [r["scheduled_date"] for r in db.upcoming_interviews()] == [SOON]


# --- the guarantee that lets the triage ban go ------------------------------

def test_a_booked_round_is_invisible_to_classification(db, client):
    _post(client, scheduled_date=SOON)
    assert db.classify_interviews() == []


def test_a_booked_round_cannot_move_a_rate(db, client):
    """
    The assertion the whole change rests on. Record a held round, snapshot the
    stats, then book a future one: the numbers must be identical.
    """
    _post(client, occurred_date="2026-08-01")
    before = db.interview_stats()
    _post(client, scheduled_date=SOON)
    assert db.interview_stats() == before


# --- the drift guard ---------------------------------------------------------

def test_an_interview_status_with_no_round_is_reported(db):
    assert [r["company"] for r in db.jobs_missing_interview_rows()] == ["Morgan Stanley"]


def test_recording_the_round_clears_the_drift(db, client):
    _post(client, scheduled_date=SOON)
    assert db.jobs_missing_interview_rows() == []


def test_a_booking_alone_clears_it_too(db, client):
    """A booked round counts as recorded -- the drift line asks whether the
    booking is in the table, not whether it has happened."""
    _post(client, scheduled_date=SOON)
    assert db.jobs_missing_interview_rows() == []


def test_a_job_not_yet_interviewing_is_not_drift(db):
    db.upsert_job({"company": "Acme", "position_title": "Engineer", "link": "",
                   "date_added": "2026-01-01", "status": "Applied"})
    assert [r["company"] for r in db.jobs_missing_interview_rows()] == ["Morgan Stanley"]


def test_a_rejected_job_is_not_drift(db):
    """Its process is over: a missing round there is history, not a booking at
    risk of being forgotten."""
    db.upsert_job({"company": "Acme", "position_title": "Engineer", "link": "",
                   "date_added": "2026-01-01", "status": "Rejected"})
    assert [r["company"] for r in db.jobs_missing_interview_rows()] == ["Morgan Stanley"]


# --- extracting a booking from prose ----------------------------------------

MS_NOTES = """Match Score: 60/100 — below threshold, tracked anyway.

✅ INTERVIEW CONFIRMED
Wednesday, September 2, 2026 — 11:45 AM to 12:15 PM EDT (30 min)
Booked 2026-08-20. Reschedule/cancel links are in the confirmation email.

TIMELINE:
- 2026-08-17: Role posted
- 2026-08-19: Ajit requested availability for an HR screening call
"""


def test_the_booking_is_read_not_the_day_it_was_booked():
    """
    The failure the first draft of this script actually made: it matched
    "Booked 2026-08-20" and reported the day the booking was made as the
    interview date. The real date is on a line whose only booking word --
    "INTERVIEW CONFIRMED" -- sits on the line above it.
    """
    got = bfi.extract_rounds({"notes": MS_NOTES, "contacts": ""})
    assert [(r["date"].isoformat(), r["time"]) for r in got] == [("2026-09-02", "11:45")]


def test_a_requested_time_is_not_a_booking():
    """"Ajit requested availability" names a date and must produce nothing."""
    got = bfi.extract_rounds({"notes": "- 2026-08-19: requested availability for a call", "contacts": ""})
    assert got == []


def test_a_date_with_no_time_is_never_a_booking():
    got = bfi.extract_rounds({"notes": "Created by inbox-triage 2026-08-20 from an interview request.",
                              "contacts": ""})
    assert got == []


GTE_NOTES = """⚠️ BOTH booked calls on 2026-08-20:
- Maddison Jonas (Odiin) — InMail 2026-08-18, call at 10:30 AM ET
- Jack Dahler — InMail 2026-08-19, call at 11:00 AM ET
"""
GTE_CONTACTS = """TWO competing agency recruiters, both pitching this same role:
1) Maddison Jonas — Odiin. Phone screen 2026-08-20, 10:30-10:45 AM ET via Google Meet.
2) Jack Dahler — agency unconfirmed. Phone screen 2026-08-20, 11:00 AM ET — he calls you.
"""


def test_two_recruiters_booking_one_role_give_two_rounds():
    """
    GTE: competing agencies booked separate calls the same day. Deduping on the
    date alone would silently drop one, so the key is (date, time).
    """
    got = bfi.extract_rounds({"notes": GTE_NOTES, "contacts": GTE_CONTACTS})
    assert [(r["date"].isoformat(), r["time"]) for r in got] == [
        ("2026-08-20", "10:30"), ("2026-08-20", "11:00")]


def test_a_time_separated_from_its_date_is_not_a_booking():
    """
    "InMail 2026-08-18, call at 10:30 AM ET" is an InMail date and, separately, a
    time on another day. A real booking writes the two as one phrase.
    """
    got = bfi.extract_rounds({"notes": GTE_NOTES, "contacts": ""})
    assert got == []


# --- the backfill writes rounds, never jobs ---------------------------------

def _apply(db, rounds, key):
    today = datetime.date.today()
    for r in rounds:
        past = r["date"] <= today
        db.add_interview(company=key[0], date_added=key[1], position_title=key[2],
                         link=key[3], interview_type="phone_screen",
                         occurred_date=r["date"].isoformat() if past else "",
                         scheduled_date="" if past else r["date"].isoformat())


def test_the_backfill_creates_no_job_rows(db):
    before = len(db.get_all_jobs(include_archived=True))
    _apply(db, bfi.extract_rounds({"notes": MS_NOTES, "contacts": ""}),
           (JOB["company"], JOB["date_added"], JOB["position_title"], JOB["link"]))
    assert len(db.get_all_jobs(include_archived=True)) == before


def test_a_future_booking_is_still_ahead(db):
    """One date either way -- what separates the two cases is only the date."""
    rounds = [{"date": TODAY + datetime.timedelta(days=9), "time": "11:45"}]
    _apply(db, rounds, (JOB["company"], JOB["date_added"], JOB["position_title"], JOB["link"]))

    assert db.get_interviews(**KEY)[0]["scheduled_date"] == SOON
    assert len(db.get_upcoming_interviews(**KEY)) == 1


def test_a_past_booking_is_a_held_round(db):
    when = TODAY - datetime.timedelta(days=4)
    rounds = [{"date": when, "time": "10:30"}]
    _apply(db, rounds, (JOB["company"], JOB["date_added"], JOB["position_title"], JOB["link"]))

    assert db.get_interviews(**KEY)[0]["scheduled_date"] == when.isoformat()
    assert db.get_upcoming_interviews(**KEY) == []
