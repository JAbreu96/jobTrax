"""
Finding rounds that were recorded twice.

Triage records a round from whatever mail names it, and the same call gets
named twice often enough -- a confirmation and then a reminder, or a thread
re-read after the watermark moved. Nothing noticed, because a duplicate round
is indistinguishable from a real one except by looking at its neighbours. Two
sat in the live table.

A duplicate costs more now than it did: every round whose date has passed
counts toward the outcomes, so a double-recorded screen is a double-counted
one. It cannot be resolved automatically -- two rounds of the same type on one
day is unusual but not impossible -- so these are surfaced for a human to
delete, never removed on their own.
"""

import pytest

from src import jobs_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    jobs_db._reset_schema_cache()
    return jobs_db


def _job(db, company, link="http://x/1", title="Engineer"):
    key = dict(company=company, date_added="2026-01-01",
               position_title=title, link=link)
    db.upsert_job({**key, "job_summary": "", "location": "", "contacts": "",
                   "notes": "", "outreach_date": "", "date_applied": "2026-01-01",
                   "status": "Phone Screen", "followup_log": ""})
    return key


def test_the_same_round_recorded_twice_is_reported(db):
    key = _job(db, "NACE Partners")
    db.add_interview(**key, interview_type="recruiter_screen", scheduled_date="2026-08-25")
    db.add_interview(**key, interview_type="recruiter_screen", scheduled_date="2026-08-25")

    groups = db.duplicate_interview_rounds()

    assert len(groups) == 1
    assert len(groups[0]["rounds"]) == 2
    assert groups[0]["company"] == "NACE Partners"
    assert groups[0]["scheduled_date"] == "2026-08-25"


def test_a_single_round_is_not_a_duplicate(db):
    key = _job(db, "Solo")
    db.add_interview(**key, interview_type="phone_screen", scheduled_date="2026-08-25")

    assert db.duplicate_interview_rounds() == []


def test_two_round_types_on_one_day_are_not_duplicates(db):
    """A same-day loop is two real rounds, not one recorded twice."""
    key = _job(db, "Usul")
    db.add_interview(**key, interview_type="recruiter_screen", scheduled_date="2026-09-08")
    db.add_interview(**key, interview_type="phone_screen", scheduled_date="2026-09-08")

    assert db.duplicate_interview_rounds() == []


def test_two_roles_at_one_company_are_not_duplicates(db):
    """Same company, same day, same type -- but two different postings."""
    a = _job(db, "Highlight AI", link="http://h/1", title="Frontend")
    b = _job(db, "Highlight AI", link="http://h/2", title="Backend")
    db.add_interview(**a, interview_type="recruiter_screen", scheduled_date="2026-08-27")
    db.add_interview(**b, interview_type="recruiter_screen", scheduled_date="2026-08-27")

    assert db.duplicate_interview_rounds() == []


def test_the_same_type_on_different_days_is_not_a_duplicate(db):
    key = _job(db, "Two Screens")
    db.add_interview(**key, interview_type="phone_screen", scheduled_date="2026-08-25")
    db.add_interview(**key, interview_type="phone_screen", scheduled_date="2026-09-01")

    assert db.duplicate_interview_rounds() == []


def test_every_round_in_the_group_carries_its_id_so_one_can_be_deleted(db):
    key = _job(db, "NACE Partners")
    first = db.add_interview(**key, interview_type="recruiter_screen",
                             scheduled_date="2026-08-25")
    second = db.add_interview(**key, interview_type="recruiter_screen",
                              scheduled_date="2026-08-25")

    ids = [r["id"] for r in db.duplicate_interview_rounds()[0]["rounds"]]

    assert sorted(ids) == sorted([first, second])
    db.delete_interview(second)
    assert db.duplicate_interview_rounds() == []


def test_nothing_is_deleted_just_by_looking(db):
    key = _job(db, "NACE Partners")
    db.add_interview(**key, interview_type="recruiter_screen", scheduled_date="2026-08-25")
    db.add_interview(**key, interview_type="recruiter_screen", scheduled_date="2026-08-25")

    db.duplicate_interview_rounds()

    assert len(db.get_interviews()) == 2
