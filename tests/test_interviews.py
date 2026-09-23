"""
Interview-round classification.

The cases that matter here are the ones the real DB cannot exercise yet: onsite
loops, awaiting-outcome processes, offers, and rounds orphaned by a changed job link.
"""

import importlib

import pytest

from src import jobs_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    importlib.reload  # keep module identity; DB_PATH is read per-call
    return jobs_db


def _job(db, company, status, link="http://x/1", title="Engineer", added="2026-01-01"):
    db.upsert_job({
        "company": company, "position_title": title, "job_summary": "", "location": "",
        "link": link, "date_added": added, "contacts": "", "notes": "",
        "outreach_date": "", "date_applied": "", "status": status, "followup_log": "",
    })
    return dict(company=company, date_added=added, position_title=title, link=link)


def _round(db, key, itype, when, loop_id=""):
    return db.add_interview(interview_type=itype, scheduled_date=when, loop_id=loop_id, **key)


def _recent(days_ago=1):
    """
    Dates in these tests must be relative, not absolute. A hard-coded date silently
    ages past the ghosting threshold and turns an 'awaiting outcome' case into a 'ghosted'
    one — a test that passes today and fails next month for no code reason.
    """
    from datetime import date, timedelta
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _outcomes(db):
    return {(r["interview_type"], r["scheduled_date"]): r["outcome"]
            for r in db.classify_interviews()}


def test_earlier_round_advanced_last_round_failed_on_rejection(db):
    key = _job(db, "Acme", "Rejected")
    _round(db, key, "phone_screen", "2026-02-01")
    _round(db, key, "technical", "2026-02-08")
    out = _outcomes(db)
    assert out[("phone_screen", "2026-02-01")] == "advanced"
    assert out[("technical", "2026-02-08")] == "failed"


def test_last_round_of_live_process_is_awaiting_outcome_not_failed(db):
    key = _job(db, "Live Co", "Applied")
    when = _recent()
    _round(db, key, "system_design", when)
    assert _outcomes(db)[("system_design", when)] == "awaiting_outcome"

    stats = db.interview_stats()
    sd = next(r for r in stats["by_type"] if r["interview_type"] == "system_design")
    assert sd["total"]["awaiting_outcome"] == 1
    # Excluded from the denominator entirely, not counted as a loss.
    assert sd["total"]["rate"] is None


@pytest.mark.parametrize("status", ["Offer", "Accepted", "accepted"])
def test_terminal_win_counts_the_final_round_as_advanced(db, status):
    key = _job(db, "Winner Inc", status)
    _round(db, key, "final_round", "2026-04-01")
    assert _outcomes(db)[("final_round", "2026-04-01")] == "advanced"


def test_same_day_loop_resolves_as_one_unit(db):
    """
    Four rounds on one Thursday. Ordering them by date would mark three
    'advanced' purely for having siblings and pin the loss on whichever sorted
    last. All four share the loop's outcome instead.
    """
    key = _job(db, "Loop Co", "Rejected")
    for itype in ("technical", "system_design", "behavioral", "technical"):
        _round(db, key, itype, "2026-05-05", loop_id="onsite-1")
    outcomes = [r["outcome"] for r in db.classify_interviews()]
    assert outcomes == ["failed"] * 4


def test_round_before_a_loop_advanced_and_the_loop_fails(db):
    key = _job(db, "Deep Co", "Rejected")
    _round(db, key, "phone_screen", "2026-06-01")
    _round(db, key, "technical", "2026-06-10", loop_id="onsite-2")
    _round(db, key, "behavioral", "2026-06-10", loop_id="onsite-2")
    out = _outcomes(db)
    assert out[("phone_screen", "2026-06-01")] == "advanced"
    assert out[("technical", "2026-06-10")] == "failed"
    assert out[("behavioral", "2026-06-10")] == "failed"


def test_rate_excludes_awaiting_outcome_from_the_denominator(db):
    won = _job(db, "A Co", "Offer", link="http://a/1")
    lost = _job(db, "B Co", "Rejected", link="http://b/1")
    live = _job(db, "C Co", "Applied", link="http://c/1")
    for key in (won, lost, live):
        _round(db, key, "system_design", _recent())

    sd = next(r for r in db.interview_stats()["by_type"]
              if r["interview_type"] == "system_design")
    assert (sd["total"]["advanced"], sd["total"]["failed"], sd["total"]["awaiting_outcome"]) == (1, 1, 1)
    # The live round is excluded from the denominator; the other two are in it.
    assert sd["total"]["decided"] == 2


def test_loop_and_standalone_are_reported_separately(db):
    solo = _job(db, "Solo Co", "Offer", link="http://s/1")
    _round(db, solo, "behavioral", "2026-08-01")
    looped = _job(db, "Loopy Co", "Rejected", link="http://l/1")
    _round(db, looped, "behavioral", "2026-08-02", loop_id="onsite-3")

    b = next(r for r in db.interview_stats()["by_type"]
             if r["interview_type"] == "behavioral")
    assert (b["standalone"]["advanced"], b["standalone"]["decided"]) == (1, 1)
    assert (b["loop"]["advanced"], b["loop"]["decided"]) == (0, 1)
    assert (b["total"]["advanced"], b["total"]["decided"]) == (1, 2)


def test_interview_survives_deletion_of_its_job_row(db):
    """
    No foreign key, no cascade — deliberately. sync_jobs_to_sqlite.py writes with
    INSERT OR REPLACE (a delete then an insert), so a cascade would wipe interview
    history on a routine sync.
    """
    key = _job(db, "Gone Co", "Rejected")
    _round(db, key, "technical", "2026-09-01")
    db.delete_job_by_key(key["company"], key["date_added"],
                         position_title=key["position_title"], link=key["link"])

    rows = db.classify_interviews()
    assert len(rows) == 1
    assert rows[0]["job_orphaned"] is True
    # Never guessed at: an orphan is awaiting outcome, not a failure.
    assert rows[0]["outcome"] == "awaiting_outcome"
    assert db.interview_stats()["totals"]["orphaned"] == 1


def test_unknown_type_and_missing_date_are_rejected(db):
    key = _job(db, "Strict Co", "Applied")
    with pytest.raises(ValueError):
        _round(db, key, "coffee_chat", "2026-10-01")
    with pytest.raises(ValueError):
        _round(db, key, "technical", "")
    with pytest.raises(ValueError):
        db.add_interview(interview_type="technical", scheduled_date="2026-10-01",
                         self_rating=9, **key)


def test_sheet_sync_does_not_destroy_interview_history(db):
    """
    Reproduces what sync_jobs_to_sqlite.py does to every job row on every run.

    INSERT OR REPLACE is a delete followed by an insert, so each sync reassigns
    rowids. Had interviews been keyed on jobs.rowid with ON DELETE CASCADE, one
    routine sync would silently empty this table and still print "Sync complete".
    """
    key = _job(db, "Sync Co", "Rejected")
    _round(db, key, "system_design", _recent(30))

    conn = db._connect()
    try:
        db._ensure_schema(conn)  # what the sync script calls on startup
        conn.execute(
            "INSERT OR REPLACE INTO jobs (company, date_added, position_title, link, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (key["company"], key["date_added"], key["position_title"], key["link"], "Rejected"),
        )
        conn.commit()
    finally:
        conn.close()

    rows = db.classify_interviews()
    assert len(rows) == 1, "sync wiped the interview history"
    assert rows[0]["job_orphaned"] is False, "interview lost track of its job after sync"
    assert rows[0]["outcome"] == "failed"


def _age_round(db, key, itype, days_ago):
    from datetime import date, timedelta
    when = (date.today() - timedelta(days=days_ago)).isoformat()
    return db.add_interview(interview_type=itype, scheduled_date=when, **key)


def test_a_silent_round_becomes_ghosted_past_the_threshold(db):
    """
    A round with nothing after it, on a job that never closed, is only 'awaiting outcome'
    for so long. Past the silence threshold it is a decision that was made and
    never communicated.
    """
    key = _job(db, "Silent Co", "Applied")
    _age_round(db, key, "technical", jobs_db.GHOSTED_AFTER_DAYS + 1)
    assert db.classify_interviews()[0]["outcome"] == "ghosted"


def test_a_recent_silent_round_is_still_awaiting_outcome(db):
    key = _job(db, "Recent Co", "Applied")
    _age_round(db, key, "technical", jobs_db.GHOSTED_AFTER_DAYS - 1)
    assert db.classify_interviews()[0]["outcome"] == "awaiting_outcome"


def test_an_old_round_that_closed_is_not_ghosted(db):
    """A rejection is a rejection however old — silence is what defines ghosting."""
    key = _job(db, "Closed Co", "Rejected")
    _age_round(db, key, "technical", jobs_db.GHOSTED_AFTER_DAYS + 100)
    assert db.classify_interviews()[0]["outcome"] == "failed"

    won = _job(db, "Won Co", "Offer", link="http://w/1")
    _age_round(db, won, "final_round", jobs_db.GHOSTED_AFTER_DAYS + 100)
    outcomes = {r["company"]: r["outcome"] for r in db.classify_interviews()}
    assert outcomes["Won Co"] == "advanced"


def test_ghosted_counts_against_the_rate_but_awaiting_outcome_does_not(db):
    won = _job(db, "Adv Co", "Offer", link="http://a/1")
    _age_round(db, won, "technical", 1)
    ghost = _job(db, "Ghost Co", "Applied", link="http://g/1")
    _age_round(db, ghost, "technical", jobs_db.GHOSTED_AFTER_DAYS + 5)
    live = _job(db, "Live Co", "Applied", link="http://l/1")
    _age_round(db, live, "technical", 1)

    tech = next(r for r in db.interview_stats()["by_type"]
                if r["interview_type"] == "technical")["total"]
    assert (tech["advanced"], tech["ghosted"], tech["awaiting_outcome"]) == (1, 1, 1)
    # Denominator is (1 advanced + 0 failed + 1 ghosted). The live round is excluded,
    # the ghosted one is not. Asserted as `decided` rather than as a percentage,
    # which is withheld below INTERVIEW_RATE_MIN_ROUNDS.
    assert tech["decided"] == 2


def test_an_earlier_round_is_never_ghosted(db):
    """Ghosting applies to the last round only — an earlier one already advanced."""
    key = _job(db, "Progressed Co", "Applied")
    _age_round(db, key, "phone_screen", jobs_db.GHOSTED_AFTER_DAYS + 60)
    _age_round(db, key, "technical", jobs_db.GHOSTED_AFTER_DAYS + 40)

    outcomes = {r["interview_type"]: r["outcome"] for r in db.classify_interviews()}
    assert outcomes["phone_screen"] == "advanced"
    assert outcomes["technical"] == "ghosted"


# --- scheduled vs occurred --------------------------------------------------
# `in_flight` used to mean "a round happened, nothing followed yet", which reads
# as "an interview is coming up" — the opposite of what it meant. It is now
# `awaiting_outcome`, and the calendar sense has its own representation.

def test_a_booked_round_never_reaches_the_denominator(db):
    """
    THE guarantee. An invite is not evidence a round happened; invites get
    cancelled. Counting one would inflate the denominator with a round that may
    never occur.
    """
    key = _job(db, "Acme", "Phone Screen")
    db.add_interview(interview_type="phone_screen",
                     scheduled_date=_recent(-3), **key)  # 3 days from now
    assert db.classify_interviews() == []
    assert db.interview_stats()["totals"]["rounds"] == 0


def test_a_booked_round_shows_as_upcoming(db):
    key = _job(db, "Acme", "Phone Screen")
    db.add_interview(interview_type="phone_screen", scheduled_date=_recent(-3), **key)
    up = db.upcoming_interviews()
    assert len(up) == 1
    assert up[0]["days_away"] == 3
    assert up[0]["overdue"] is False


def test_a_held_round_is_not_upcoming(db):
    key = _job(db, "Acme", "Phone Screen")
    db.add_interview(interview_type="phone_screen", scheduled_date=_recent(2), **key)
    assert db.upcoming_interviews() == []


def test_a_round_is_booked_until_its_day_passes_then_it_counts(db):
    """
    The normal lifecycle, with no promotion step in the middle: a round ahead of
    us is upcoming and counts toward nothing, and the same row past its date is
    a held round. Two rows stand in for one row and the passage of time.
    """
    key = _job(db, "Acme", "Phone Screen")
    db.add_interview(interview_type="phone_screen", scheduled_date=_recent(-1), **key)

    assert db.classify_interviews() == []
    assert len(db.upcoming_interviews()) == 1

    db.add_interview(interview_type="technical", scheduled_date=_recent(1), **key)

    assert len(db.classify_interviews()) == 1
    assert len(db.upcoming_interviews()) == 1


def test_the_upcoming_query_runs_on_sqlite(db):
    """
    It once asked for GETDATE(), which is SQL Server and raises
    `no such function` here. Calling it at all is the assertion.
    """
    key = _job(db, "Acme", "Phone Screen")
    db.add_interview(interview_type="phone_screen", scheduled_date=_recent(-3), **key)
    assert len(db.get_upcoming_interviews()) == 1


def test_the_upcoming_query_keeps_today_and_drops_yesterday(db):
    """A round booked for today has not happened yet; the cutoff is inclusive."""
    today = _job(db, "Today", "Phone Screen", link="http://x/today")
    past = _job(db, "Past", "Phone Screen", link="http://x/past")
    db.add_interview(interview_type="phone_screen", scheduled_date=_recent(0), **today)
    db.add_interview(interview_type="phone_screen", scheduled_date=_recent(1), **past)

    assert [r["company"] for r in db.get_upcoming_interviews()] == ["Today"]
    assert {r["company"] for r in db.get_upcoming_interviews(include_past=True)} == {
        "Today", "Past"}


def test_the_upcoming_query_filters_the_past_without_a_company(db):
    """
    The date clause used to sit inside `if company:`, so the unscoped call the
    Insights card makes was filtered by nothing at all.
    """
    key = _job(db, "Acme", "Phone Screen")
    db.add_interview(interview_type="phone_screen", scheduled_date=_recent(30), **key)
    assert db.get_upcoming_interviews() == []


def test_a_past_round_is_not_upcoming_but_is_still_retrievable(db):
    """
    It is a held round, so it is not in the upcoming view -- but include_past
    still returns it. Silently dropping it is how the log drifts out of sync
    with reality, and this is how a caller assembles a full booking history.

    Nothing is `overdue` any more: that flag described a booking whose date had
    passed with no outcome recorded, and a past round now simply happened.
    """
    key = _job(db, "Acme", "Phone Screen")
    db.add_interview(interview_type="phone_screen", scheduled_date=_recent(9), **key)

    assert db.upcoming_interviews() == []
    history = db.upcoming_interviews(include_past=True)
    assert len(history) == 1
    assert history[0]["overdue"] is False


def test_a_round_with_neither_date_is_rejected(db):
    key = _job(db, "Acme", "Phone Screen")
    with pytest.raises(ValueError):
        db.add_interview(interview_type="phone_screen", **key)


def test_occurred_only_rounds_still_work_unchanged(db):
    """Regression: the existing call signature must keep behaving identically."""
    key = _job(db, "Acme", "Rejected")
    db.add_interview(interview_type="technical", scheduled_date=_recent(2), **key)
    out = db.classify_interviews()
    assert len(out) == 1 and out[0]["outcome"] == "failed"


# --- rate suppression on small samples --------------------------------------
# "0.0%" from two decided rounds reads as a verdict on your ability. The counts
# are a fact; the percentage is a claim the sample cannot support.

def _decided_rounds(db, n, advanced_of=0):
    """n rounds that reached a conclusion, `advanced_of` of them successfully."""
    for i in range(n):
        status = "Offer" if i < advanced_of else "Rejected"
        key = _job(db, f"Co{i}", status, link=f"http://x/{i}")
        db.add_interview(interview_type="technical", scheduled_date=_recent(2), **key)


def test_rate_is_withheld_below_the_floor(db):
    _decided_rounds(db, 2)
    row = db.interview_stats()["by_type"][0]["total"]
    assert row["rate"] is None
    assert row["decided"] == 2      # the counts are still reported
    assert row["advanced"] == 0


def test_rate_appears_once_the_sample_is_big_enough(db):
    _decided_rounds(db, jobs_db.INTERVIEW_RATE_MIN_ROUNDS, advanced_of=2)
    row = db.interview_stats()["by_type"][0]["total"]
    assert row["rate"] is not None
    assert row["decided"] == jobs_db.INTERVIEW_RATE_MIN_ROUNDS


def test_awaiting_rounds_never_count_toward_the_floor(db):
    """
    A round with no verdict is not evidence. Letting it count would unlock the
    percentage using rounds that have decided nothing.
    """
    _decided_rounds(db, 2)
    for i in range(10):
        key = _job(db, f"Open{i}", "Tracking", link=f"http://open/{i}")
        db.add_interview(interview_type="technical", scheduled_date=_recent(1), **key)
    row = db.interview_stats()["by_type"][0]["total"]
    assert row["decided"] == 2
    assert row["rate"] is None


def test_ghosted_rounds_do_count_toward_the_floor(db):
    """Silence is a decision that was made and never communicated."""
    for i in range(jobs_db.INTERVIEW_RATE_MIN_ROUNDS):
        key = _job(db, f"Ghost{i}", "Tracking", link=f"http://g/{i}")
        db.add_interview(interview_type="technical",
                         scheduled_date=_recent(jobs_db.GHOSTED_AFTER_DAYS + 2), **key)
    row = db.interview_stats()["by_type"][0]["total"]
    assert row["ghosted"] == jobs_db.INTERVIEW_RATE_MIN_ROUNDS
    assert row["rate"] == 0.0


def test_totals_report_decided_for_the_headline(db):
    _decided_rounds(db, 3, advanced_of=1)
    t = db.interview_stats()["totals"]
    assert (t["advanced"], t["decided"]) == (1, 3)
