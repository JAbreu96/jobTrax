"""
`update_job_status` never downgrades a status.

SKILL.md states this as a core operating principle ("Never downgrade a
status... Only move a job forward, except for Rejected, which may always be
set") but the tool had no code enforcing it — a misclassified email could
silently regress Phone Screen back to Applied with nothing catching it.
"""

import pytest

from src import jobs_db
from mcp_servers.job_tracker import server


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    return jobs_db


def _job(db, company, title, link, status="Applied", added="2026-08-01"):
    db.upsert_job({
        "company": company, "position_title": title, "job_summary": "", "location": "",
        "link": link, "date_added": added, "contacts": "", "notes": "",
        "outreach_date": "", "date_applied": "", "status": status, "followup_log": "",
    })


def _status(db, company, title):
    return next(r["status"] for r in db.get_all_jobs()
                if r["company"] == company and r["position_title"] == title)


def test_forward_move_is_allowed(db):
    _job(db, "Acme", "Engineer", "http://acme/1", status="Applied")

    server.update_job_status("Acme", "Phone Screen", position_title="Engineer")

    assert _status(db, "Acme", "Engineer") == "Phone Screen"


def test_same_status_is_a_no_op_allowed(db):
    _job(db, "Acme", "Engineer", "http://acme/1", status="Phone Screen")

    server.update_job_status("Acme", "Phone Screen", position_title="Engineer")

    assert _status(db, "Acme", "Engineer") == "Phone Screen"


def test_backward_move_is_refused_and_row_is_unchanged(db):
    _job(db, "Acme", "Engineer", "http://acme/1", status="Phone Screen")

    with pytest.raises(ValueError, match="Refusing to downgrade"):
        server.update_job_status("Acme", "Applied", position_title="Engineer")

    assert _status(db, "Acme", "Engineer") == "Phone Screen"


def test_backward_move_to_rejected_is_allowed(db):
    """Rejected is the one status permitted to move backward — a company can
    turn down a candidate at any stage, including from Offer."""
    _job(db, "Acme", "Engineer", "http://acme/1", status="Offer")

    server.update_job_status("Acme", "Rejected", position_title="Engineer")

    assert _status(db, "Acme", "Engineer") == "Rejected"


def test_unranked_current_status_refuses_safely_rather_than_crashing(db):
    _job(db, "Acme", "Engineer", "http://acme/1", status="Some Legacy Value")

    with pytest.raises(ValueError, match="Cannot compare status ranks"):
        server.update_job_status("Acme", "Applied", position_title="Engineer")

    assert _status(db, "Acme", "Engineer") == "Some Legacy Value"
