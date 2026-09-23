"""
`date_applied` is maintained by the status write itself.

It used to be set in exactly one place — the GUI, on the exact transition to
"Applied" (src/jobs_gui.py). Every other writer, including the MCP
`update_job_status` that inbox-triage calls, left it blank. A job advanced
straight to "Phone Screen" therefore kept an empty date_applied forever, and
because the application funnel nests each stage inside the one above it, those
jobs dropped out of every stage below "applied". The audit found 22 such rows:
the funnel reported 7 jobs at a screen when 33 had actually reached one.
"""

import pytest

from datetime import date

from src import jobs_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    return jobs_db


def _job(db, company, *, status="Tracking", applied="", outreach=""):
    key = dict(company=company, date_added="2026-01-01",
               position_title="Engineer", link=f"http://x/{company}")
    db.upsert_job({
        **key, "job_summary": "", "location": "", "contacts": "", "notes": "",
        "outreach_date": outreach, "date_applied": applied, "status": status,
        "followup_log": "",
    })
    return key


def _applied_of(db, key):
    return next(
        r["date_applied"] for r in db.get_all_jobs(include_archived=True)
        if r["company"] == key["company"]
    )


def test_advancing_to_a_screening_status_stamps_date_applied(db):
    """The actual bug: triage moves a job to Phone Screen and it leaves the funnel."""
    key = _job(db, "Morgan Stanley")

    db.update_status(key["company"], key["date_added"], "Phone Screen",
                     key["position_title"], key["link"])

    assert _applied_of(db, key) == date.today().isoformat()


def test_advancing_to_applied_stamps_date_applied(db):
    key = _job(db, "Sciforium")

    db.update_status(key["company"], key["date_added"], "Applied",
                     key["position_title"], key["link"])

    assert _applied_of(db, key) == date.today().isoformat()


def test_an_existing_date_applied_is_never_overwritten(db):
    """Advancing through several rounds must not keep resetting the clock."""
    key = _job(db, "REALM", status="Applied", applied="2026-01-05")

    db.update_status(key["company"], key["date_added"], "Technical",
                     key["position_title"], key["link"])

    assert _applied_of(db, key) == "2026-01-05"


def test_rejected_does_not_invent_an_application(db):
    """A cold outreach can be turned down by a company never applied to."""
    key = _job(db, "Glocomms", status="Tracking", outreach="2026-01-03")

    db.update_status(key["company"], key["date_added"], "Rejected",
                     key["position_title"], key["link"])

    assert _applied_of(db, key) == ""


def test_tracking_does_not_stamp_date_applied(db):
    key = _job(db, "Plural")

    db.update_status(key["company"], key["date_added"], "Tracking",
                     key["position_title"], key["link"])

    assert _applied_of(db, key) == ""


@pytest.fixture
def client(tmp_path, monkeypatch):
    """The GUI writes status through its own request-scoped connection rather
    than update_status, so it needs its own coverage of the same invariant."""
    from src import jobs_gui

    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    jobs_db._reset_schema_cache()
    jobs_db.upsert_job({
        "company": "Acme", "position_title": "Engineer", "link": "",
        "date_added": "2026-01-01", "status": "Tracking", "notes": "",
    })
    jobs_gui.app.config["TESTING"] = True
    with jobs_gui.app.test_client() as c:
        yield c


def _set_status(client, value):
    return client.post("/api/jobs/update", json={
        "company": "Acme", "date_added": "2026-01-01",
        "position_title": "Engineer", "link": "", "field": "status", "value": value,
    })


def _acme(client):
    return next(r for r in client.get("/api/jobs").get_json()
                if r["company"] == "Acme")


def test_gui_advancing_to_a_screening_status_stamps_date_applied(client):
    _set_status(client, "Phone Screen")

    assert _acme(client)["date_applied"] == date.today().isoformat()


def test_gui_rejected_does_not_invent_an_application(client):
    _set_status(client, "Rejected")

    assert _acme(client)["date_applied"] == ""


def test_stamping_puts_the_job_into_the_funnel_applied_stage(db):
    """The end-to-end point of the fix, asserted on the page's own aggregate."""
    key = _job(db, "Usul")
    before = jobs_db.funnel_stats()["sources"]["all"]

    db.update_status(key["company"], key["date_added"], "Phone Screen",
                     key["position_title"], key["link"])
    after = jobs_db.funnel_stats()["sources"]["all"]

    def stage(payload, name):
        return next(s for s in payload["application_path"] if s["stage"] == name)

    assert stage(before, "applied")["count"] == 0
    assert stage(before, "at screen")["count"] == 0
    assert stage(after, "applied")["count"] == 1
    assert stage(after, "at screen")["count"] == 1
