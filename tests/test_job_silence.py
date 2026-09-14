"""
Job-level silence: `ghosted` vs `no_response`.

Two states because two different things happen. Someone who wrote and went quiet
DISENGAGED; a portal application nobody answered was never engaged with. The
tests that matter are the ones pinning that boundary — and the ones proving the
two thresholds stay distinct, since collapsing them is the failure mode that
would quietly relabel ~350 auto-submitted rows as ghosted.
"""

from datetime import date, timedelta

import pytest

from src import jobs_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    return jobs_db


def _ago(days: int) -> str:
    """Relative, never hard-coded — a fixed date silently ages past a threshold."""
    return (date.today() - timedelta(days=days)).isoformat()


def _job(db, company, status="Applied", applied_days=None, added_days=90,
         link="http://x/1", title="Engineer", notes=""):
    db.upsert_job({
        "company": company, "position_title": title, "job_summary": "", "location": "",
        "link": link, "date_added": _ago(added_days), "contacts": "", "notes": notes,
        "outreach_date": "", "date_applied": "" if applied_days is None else _ago(applied_days),
        "status": status, "followup_log": "",
    })
    return dict(company=company, date_added=_ago(added_days),
                position_title=title, link=link)


def _state(db, company):
    for r in db.classify_job_silence():
        if r["company"] == company:
            return r["state"]
    return None


def _row(db, company):
    return next((r for r in db.classify_job_silence() if r["company"] == company), None)


# --- ghosted: a relationship existed and went quiet --------------------------

def test_logged_interview_gone_quiet_is_ghosted(db):
    key = _job(db, "Acme", status="Tracking")
    db.add_interview(interview_type="technical",
                     scheduled_date=_ago(jobs_db.GHOSTED_AFTER_DAYS + 5), **key)
    assert _state(db, "Acme") == "ghosted"


def test_recent_interview_is_still_waiting(db):
    key = _job(db, "Acme", status="Tracking")
    db.add_interview(interview_type="technical",
                     scheduled_date=_ago(jobs_db.GHOSTED_AFTER_DAYS - 5), **key)
    assert _state(db, "Acme") == "waiting"


def test_screening_status_counts_even_with_no_interview_row(db):
    """
    Eight of the ten live screens have no `interviews` row. Requiring one would
    make the state blind to exactly the jobs it exists to watch.
    """
    _job(db, "Acme", status="Phone Screen", applied_days=jobs_db.GHOSTED_AFTER_DAYS + 5)
    row = _row(db, "Acme")
    assert row["state"] == "ghosted"
    assert row["signal"] == "screening_status"


def test_recruiter_message_gone_quiet_is_ghosted(db):
    key = _job(db, "Kastech SSG", status="Tracking",
               link="recruiter:email:laxmano@kastechssg.com/frontend-engineer")
    rid = db.upsert_recruiter("email", "laxmano@kastechssg.com")
    db.link_recruiter_job(rid, sourced_date=_ago(40), **key)
    db.record_recruiter_message(rid, "inbound", _ago(jobs_db.GHOSTED_AFTER_DAYS + 3),
                                message_id="m1")
    row = _row(db, "Kastech SSG")
    assert row["state"] == "ghosted"
    assert row["signal"] == "recruiter_message"


def test_a_relationship_job_is_never_no_response(db):
    """
    A job with a conversation uses the ghosted threshold, not the longer one.
    Falling through to no_response would make a 20-day-silent recruiter thread
    read as 'waiting' for another ten days.
    """
    _job(db, "Acme", status="Phone Screen", applied_days=20)
    assert _state(db, "Acme") == "ghosted"


# --- no_response: nobody ever engaged ---------------------------------------

def test_old_application_with_no_relationship_is_no_response(db):
    _job(db, "Notion", applied_days=jobs_db.NO_RESPONSE_AFTER_DAYS + 5)
    row = _row(db, "Notion")
    assert row["state"] == "no_response"
    assert row["signal"] == "application"


def test_the_two_thresholds_are_distinct(db):
    """
    THE regression. At 20 days a blind application is still waiting, while a
    conversation at 20 days is already ghosted. Collapsing the thresholds would
    relabel every auto-submitted row the moment it crossed 15 days.
    """
    gap = (jobs_db.GHOSTED_AFTER_DAYS + jobs_db.NO_RESPONSE_AFTER_DAYS) // 2
    assert jobs_db.GHOSTED_AFTER_DAYS < gap < jobs_db.NO_RESPONSE_AFTER_DAYS

    _job(db, "Blind", applied_days=gap, link="http://x/1")
    _job(db, "Talked", status="Phone Screen", applied_days=gap, link="http://x/2")
    assert _state(db, "Blind") == "waiting"
    assert _state(db, "Talked") == "ghosted"


def test_auto_applied_rows_are_included_but_flagged(db):
    _job(db, "BulkCo", applied_days=jobs_db.NO_RESPONSE_AFTER_DAYS + 1,
         notes="Imported from auto-apply export (auto-submitted application).")
    row = _row(db, "BulkCo")
    assert row["state"] == "no_response"
    assert row["auto_applied"] is True
    assert db.job_silence_stats()["counts"]["no_response"]["auto"] == 1


# --- what must never be classified ------------------------------------------

def test_tracking_row_never_applied_is_not_classified(db):
    """
    34 rows are 30+ days old, Tracking, never applied. They are not awaiting a
    reply, and labelling them silent would count a decision nobody made.
    """
    _job(db, "Someday", status="Tracking", applied_days=None, added_days=400)
    assert _row(db, "Someday") is None


def test_rejected_is_never_ghosted_or_no_response(db):
    key = _job(db, "Acme", status="Rejected", applied_days=200)
    db.add_interview(interview_type="technical", scheduled_date=_ago(150), **key)
    assert _row(db, "Acme") is None


def test_offer_and_accepted_are_never_classified(db):
    _job(db, "WinCo", status="Offer", applied_days=200, link="http://x/1")
    _job(db, "GotIt", status="Accepted", applied_days=200, link="http://x/2")
    assert _row(db, "WinCo") is None and _row(db, "GotIt") is None


def test_outreach_date_alone_is_not_a_relationship(db):
    """
    outreach_date is a manual flag and four of seventeen have no contact
    recorded, so it cannot evidence a two-way exchange. Garage has it set and
    must still fall through to the application clock.
    """
    db.upsert_job({
        "company": "Garage", "position_title": "Engineer", "job_summary": "", "location": "",
        "link": "http://x/1", "date_added": _ago(60), "contacts": "", "notes": "",
        "outreach_date": _ago(45), "date_applied": _ago(20), "status": "Applied",
        "followup_log": "",
    })
    row = _row(db, "Garage")
    assert row["signal"] == "application"
    assert row["state"] == "waiting"  # 20d < NO_RESPONSE_AFTER_DAYS


def test_stats_never_sum_hand_and_auto_silently(db):
    _job(db, "HandCo", applied_days=jobs_db.NO_RESPONSE_AFTER_DAYS + 1, link="http://x/1")
    _job(db, "BulkCo", applied_days=jobs_db.NO_RESPONSE_AFTER_DAYS + 1, link="http://x/2",
         notes="Imported from auto-apply export")
    c = db.job_silence_stats()["counts"]["no_response"]
    assert (c["hand"], c["auto"], c["total"]) == (1, 1, 2)
