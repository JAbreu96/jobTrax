"""
Application-funnel aggregation.

Every test here except the last two locks down a bug that reached the rendered
page: an interview belonging to neither path vanished from the totals, a
conversion rate was computed straight across a stage we admit we cannot measure,
and the funnel counted a different population than the table it linked to.
"""

import pytest

from src import jobs_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    return jobs_db


def _job(db, company, *, status="Applied", applied="", outreach="", notes="",
         link=None, archived=False):
    key = dict(company=company, date_added="2026-01-01",
               position_title="Engineer", link=link or f"http://x/{company}")
    db.upsert_job({
        **key, "job_summary": "", "location": "", "contacts": "", "notes": notes,
        "outreach_date": outreach, "date_applied": applied, "status": status,
        "followup_log": "",
    })
    if archived:
        conn = db._connect()
        try:
            conn.execute(
                "UPDATE jobs SET archived = 1 WHERE company = ? AND date_added = ? "
                "AND position_title = ? AND link = ?",
                (key["company"], key["date_added"], key["position_title"], key["link"]),
            )
            conn.commit()
        finally:
            conn.close()
    return key


def _interview(db, key, itype="technical", when="2026-02-01"):
    return db.add_interview(interview_type=itype, scheduled_date=when, **key)


def _stage(payload, path, name):
    return next(s for s in payload[path] if s["stage"] == name)


def test_interview_on_neither_path_still_counts_in_the_total(db):
    """
    A job sourced through a contact has no application date and no outreach date,
    so it sits on neither path. Summing the two paths' 'interviewed' stages would
    drop it and make this card disagree with the interview table on the same page.
    """
    key = _job(db, "ContactCo", applied="", outreach="")
    _interview(db, key)

    s = db.funnel_stats()["sources"]["all"]
    assert _stage(s, "application_path", "interviewed")["count"] == 0
    assert _stage(s, "outreach_path", "interviewed")["count"] == 0
    assert s["interviewed_total"] == 1
    assert s["interviewed_unattributed"] == 1


def test_a_job_on_both_paths_is_not_counted_twice(db):
    key = _job(db, "BothCo", applied="2026-01-05", outreach="2026-01-05")
    _interview(db, key)

    s = db.funnel_stats()["sources"]["all"]
    assert _stage(s, "application_path", "interviewed")["count"] == 1
    assert _stage(s, "outreach_path", "interviewed")["count"] == 1
    assert s["interviewed_total"] == 1, "summing the paths double-counts this row"
    assert s["both_paths"] == 1


def test_no_rate_is_computed_across_an_unmeasured_stage(db):
    """
    'replied' has no field backing it. A rate leaping that gap would claim to
    measure what the gap says is unmeasurable — and would render outreach as 0%.
    """
    for i in range(40):
        _job(db, f"Out{i}", outreach="2026-01-05", link=f"http://o/{i}")

    s = db.funnel_stats()["sources"]["all"]
    assert _stage(s, "outreach_path", "outreached")["rate"] == pytest.approx(100.0)
    assert _stage(s, "outreach_path", "replied")["count"] is None
    assert _stage(s, "outreach_path", "replied")["rate"] is None
    assert _stage(s, "outreach_path", "interviewed")["rate"] is None, \
        "a rate here would read as '0% of outreach converts', which is unknown, not zero"


def test_archived_rows_are_included(db):
    """
    The funnel is a historical record. Excluding archived rows drops finished
    outcomes — the most useful input — and makes long-running channels look inert.
    """
    _job(db, "Old", applied="2025-11-01", archived=True)
    _job(db, "New", applied="2026-01-05")

    s = db.funnel_stats()["sources"]["all"]
    assert _stage(s, "application_path", "tracked")["count"] == 2
    assert _stage(s, "application_path", "applied")["count"] == 2


def test_rate_is_suppressed_below_the_minimum_denominator(db):
    for i in range(5):
        _job(db, f"Small{i}", applied="2026-01-05", link=f"http://s/{i}")

    s = db.funnel_stats()["sources"]["all"]
    assert _stage(s, "application_path", "tracked")["count"] == 5
    assert _stage(s, "application_path", "applied")["rate"] is None, \
        "5 rows cannot support a percentage"

    for i in range(jobs_db.RATE_MIN_DENOMINATOR):
        _job(db, f"Big{i}", applied="2026-01-05", link=f"http://b/{i}")
    s = db.funnel_stats()["sources"]["all"]
    assert _stage(s, "application_path", "applied")["rate"] is not None


def test_source_split_separates_auto_from_hand(db):
    _job(db, "Auto1", applied="2026-01-05", notes="Imported via ApplyPass export")
    _job(db, "Auto2", applied="2026-01-05", notes="auto-applied by service")
    _job(db, "Hand1", applied="2026-01-05", notes="found on Ashby")

    src = db.funnel_stats()["sources"]
    assert _stage(src["auto"], "application_path", "tracked")["count"] == 2
    assert _stage(src["hand"], "application_path", "tracked")["count"] == 1
    assert _stage(src["all"], "application_path", "tracked")["count"] == 3


def test_rejections_are_reported_beside_the_paths_not_inside_them(db):
    _job(db, "Gone", applied="2026-01-05", status="Rejected")
    _job(db, "Live", applied="2026-01-05", status="Applied")

    s = db.funnel_stats()["sources"]["all"]
    assert s["rejected"] == 1
    # A rejection is an exit, not a step toward an interview: it must not thin out
    # the stage counts on the path itself.
    assert _stage(s, "application_path", "applied")["count"] == 2


def test_at_screen_reads_current_status_only(db):
    _job(db, "Screening", applied="2026-01-05", status="Phone Screen")
    _job(db, "WasScreened", applied="2026-01-05", status="Rejected")

    s = db.funnel_stats()["sources"]["all"]
    # 'WasScreened' may well have reached a screen before being rejected, but
    # status holds current state only. This stage is a floor, never a total.
    assert _stage(s, "application_path", "at screen")["count"] == 1


def test_a_screen_does_not_count_as_interviewed(db):
    """
    A recruiter or phone screen filters for plausibility; it is not an evaluation.
    Counting it at the funnel's last stage would inflate 'interviewed' with calls
    that reject almost nobody. Screens stop at the screen stage.
    """
    key = _job(db, "ScreenedCo", applied="2026-01-05")
    _interview(db, key, itype="phone_screen")

    s = db.funnel_stats()["sources"]["all"]
    assert _stage(s, "application_path", "interviewed")["count"] == 0
    assert _stage(s, "application_path", "at screen")["count"] == 1
    assert s["interviewed_total"] == 0


def test_a_logged_screen_counts_at_screen_even_after_rejection(db):
    """
    Status is current state: a job screened and then rejected reads only as
    'Rejected'. The logged round is what remembers it reached the stage.
    """
    key = _job(db, "ScreenedThenGone", applied="2026-01-05", status="Rejected")
    _interview(db, key, itype="phone_screen")

    s = db.funnel_stats()["sources"]["all"]
    assert _stage(s, "application_path", "at screen")["count"] == 1, \
        "status alone forgets this job was ever screened"


def test_an_evaluation_round_does_graduate_the_job(db):
    key = _job(db, "RealInterview", applied="2026-01-05")
    _interview(db, key, itype="system_design")

    s = db.funnel_stats()["sources"]["all"]
    assert _stage(s, "application_path", "interviewed")["count"] == 1
    assert s["interviewed_total"] == 1
