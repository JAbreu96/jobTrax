"""
The Insights card's two counting rules.

Both exist because the page puts two numbers side by side and a reader assumes
they measure the same thing:

`captured` sits next to `suspected uncaptured`, and the second counts roles. So
the first has to count roles too -- but recruiter_jobs is many-to-many, and GTE
arrived from two agencies within a day. COUNT(*) would have reported it twice.

"Coming up" shows a 14-day window, and a window that drops rows would contradict
the note printed directly beneath it. The table is future-only, so a booking whose
date has gone by has to surface as a count instead of vanishing -- and live data
drifts through these states too quietly for anything but a test to hold the line.
"""

import pytest

from src import jobs_db
# Imported here, at collection, and never inside a test. jobs_gui imports
# job_agent, which calls load_dotenv() at import -- so importing it mid-test
# re-adds TURSO_DATABASE_URL *after* conftest stripped it, and the render tests
# quietly start reading the production database instead of the tmp one. At
# module scope the conftest fixture still pops it before each test runs.
from src import jobs_gui


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    jobs_db._reset_schema_cache()
    jobs_db.upsert_job({
        "company": "GTE", "position_title": "Product Engineer", "link": "thread-1",
        "date_added": "2026-08-19", "status": "Phone Screen",
    })
    return jobs_db


def _recruiter(name, identity):
    return jobs_db.upsert_recruiter(source="linkedin", identity=identity,
                                    name=name, seen_date="2026-08-19")


# --- captured counts roles, not recruiter-role links ------------------------

def test_two_recruiters_on_one_role_count_as_one_captured(db):
    """
    GTE's actual shape: Jack Dahler and Maddison Jonas both pitched it. Two
    relationships, one role -- and the number beside it counts roles.
    """
    key = dict(company="GTE", date_added="2026-08-19",
               position_title="Product Engineer", link="thread-1")
    jobs_db.link_recruiter_job(_recruiter("Jack Dahler", "jack-dahler"), **key)
    jobs_db.link_recruiter_job(_recruiter("Maddison Jonas", "maddison-jonas"), **key)

    assert jobs_db.recruiter_coverage()["captured"] == 1


def test_both_recruiters_are_still_recorded(db):
    """Counting the role once must not cost us either relationship."""
    key = dict(company="GTE", date_added="2026-08-19",
               position_title="Product Engineer", link="thread-1")
    jobs_db.link_recruiter_job(_recruiter("Jack Dahler", "jack-dahler"), **key)
    jobs_db.link_recruiter_job(_recruiter("Maddison Jonas", "maddison-jonas"), **key)

    assert len(jobs_db.get_recruiters()) == 2


def test_distinct_roles_still_count_separately(db):
    """The fix must not collapse genuinely different roles."""
    rid = _recruiter("Jack Dahler", "jack-dahler")
    jobs_db.link_recruiter_job(rid, company="GTE", date_added="2026-08-19",
                               position_title="Product Engineer", link="thread-1")
    jobs_db.link_recruiter_job(rid, company="GTE", date_added="2026-08-19",
                               position_title="Backend Engineer", link="thread-2")
    assert jobs_db.recruiter_coverage()["captured"] == 2


def test_linking_a_recruiter_creates_no_job_row(db):
    """
    The backfill links rows that already exist. If link_recruiter_job ever began
    inserting, the nine tracked rows would gain nine duplicates -- the failure
    this whole change set exists to avoid.
    """
    before = len(jobs_db.get_all_jobs(include_archived=True))
    jobs_db.link_recruiter_job(_recruiter("Jack Dahler", "jack-dahler"),
                               company="GTE", date_added="2026-08-19",
                               position_title="Product Engineer", link="thread-1")
    assert len(jobs_db.get_all_jobs(include_archived=True)) == before


def test_relinking_the_same_pair_is_idempotent(db):
    """Re-running the backfill must change nothing."""
    key = dict(company="GTE", date_added="2026-08-19",
               position_title="Product Engineer", link="thread-1")
    rid = _recruiter("Jack Dahler", "jack-dahler")
    jobs_db.link_recruiter_job(rid, **key)
    jobs_db.link_recruiter_job(rid, **key)
    assert jobs_db.recruiter_coverage()["captured"] == 1
    assert len(jobs_db.get_recruiter_jobs()) == 1


# --- the 14-day window ------------------------------------------------------

def _book(db, company, days_from_today, itype="recruiter_screen"):
    from datetime import date, timedelta
    when = (date.today() + timedelta(days=days_from_today)).isoformat()
    db.upsert_job({"company": company, "position_title": "Engineer", "link": company,
                   "date_added": "2026-08-01", "status": "Phone Screen"})
    return db.add_interview(company=company, date_added="2026-08-01",
                            position_title="Engineer", link=company,
                            interview_type=itype, scheduled_date=when)


def _split(rows, window):
    """Mirrors the template's partition, so the rule is asserted in one place."""
    soon = [r for r in rows if r["days_away"] <= window]
    later = [r for r in rows if r["days_away"] > window]
    return soon, later


def test_a_booking_inside_the_window_is_in_the_table(db):
    _book(db, "Inside", 14)
    soon, later = _split(jobs_db.upcoming_interviews(), jobs_db.UPCOMING_WINDOW_DAYS)
    assert [r["company"] for r in soon] == ["Inside"] and later == []


def test_a_booking_past_the_window_moves_to_the_overflow(db):
    _book(db, "Later", 15)
    soon, later = _split(jobs_db.upcoming_interviews(), jobs_db.UPCOMING_WINDOW_DAYS)
    assert soon == [] and [r["company"] for r in later] == ["Later"]


def test_nothing_is_dropped_by_the_window(db):
    """The window narrows the table, never the truth."""
    _book(db, "Soon", 3)
    _book(db, "Later", 40)
    rows = jobs_db.upcoming_interviews()
    soon, later = _split(rows, jobs_db.UPCOMING_WINDOW_DAYS)
    assert len(soon) + len(later) == len(rows) == 2


def test_a_past_booking_is_not_in_either_half(db):
    """
    A booking whose date has gone by is not upcoming, so it belongs to neither
    the table nor the overflow count -- the card is about what is still ahead.
    """
    _book(db, "Forgotten", -90)
    soon, later = _split(jobs_db.upcoming_interviews(), jobs_db.UPCOMING_WINDOW_DAYS)
    assert soon == [] and later == []


# --- the template itself ----------------------------------------------------
# The tests above assert the partition rule; these assert the page implements it.
# Without them the rule could hold in Python while the Jinja diverged, and every
# test would still pass.

def _render(db):
    assert not jobs_db._use_libsql(), "render test is pointed at the remote database"
    jobs_gui.app.config["TESTING"] = True
    with jobs_gui.app.test_client() as client:
        return client.get("/insights").get_data(as_text=True)


def test_the_page_puts_coming_up_before_the_filter_bar(db):
    """
    The filter toggles do not apply to interviews, so rendering the bar first
    would state something false about what the list is showing.
    """
    html = _render(db)
    assert html.index("Coming up") < html.index('class="source-bar"')


def test_the_overflow_line_sits_under_the_table(db):
    """Something inside the window and something past it: table plus a +N line."""
    _book(db, "Inside", 3)
    _book(db, "Later", 40)
    html = _render(db)
    coming_up = html.split("Coming up")[1].split("source-bar")[0]
    assert "Inside" in coming_up
    assert "booked beyond 14 days" in coming_up
    # the far booking is counted, not tabled
    assert "Later" not in coming_up.split("booked beyond")[0]


def test_only_far_bookings_still_says_so(db):
    """
    Nothing inside the window but something past it. The card must not read
    "Nothing booked" -- there is something booked, just not soon.
    """
    _book(db, "Later", 40)
    html = _render(db)
    assert "Nothing in the next 14 days" in html
    assert "1 booked later" in html
    assert "Nothing booked." not in html


def test_the_page_tables_a_booking_inside_the_window(db):
    _book(db, "Inside", 5)
    html = _render(db)
    assert "Inside" in html and "booked beyond" not in html


def _card(html):
    """The Coming up card, and the table inside it, as separate strings."""
    card = html.split("Coming up")[1].split("source-bar")[0]
    table = card.split("<table>")[1].split("</table>")[0] if "<table>" in card else ""
    return card, table


def test_the_card_shows_nothing_for_a_round_already_held(db):
    """
    The card is only what is ahead. A past-dated round is a held round now -- it
    belongs to the outcome table further down the page, not to "Coming up" --
    so it appears nowhere in this card, not even as a count.

    This replaces a pair of tests covering the state between those two: booked,
    the date gone by, no outcome recorded. That state no longer exists.
    """
    _book(db, "Forgotten", -90)
    card, table = _card(_render(db))

    assert "Forgotten" not in card
    assert "Forgotten" not in table
    assert "overdue" not in card
    assert "no outcome recorded" not in card
    assert "Nothing booked." in card


def test_the_count_line_is_absent_when_every_booking_is_ahead(db):
    _book(db, "Inside", 5)
    card, _ = _card(_render(db))
    assert "no outcome recorded" not in card


def test_a_booking_with_an_unreadable_date_does_not_break_the_page(db):
    """
    days_away is None when the date will not parse, and the Jinja `le` filter
    raises on None. The card is the only path that partitions on it.
    """
    company = "Garbled"
    db.upsert_job({"company": company, "position_title": "Engineer", "link": company,
                   "date_added": "2026-08-01", "status": "Phone Screen"})
    db.add_interview(company=company, date_added="2026-08-01", position_title="Engineer",
                     link=company, interview_type="recruiter_screen",
                     scheduled_date="whenever")
    card, table = _card(_render(db))
    # Rendering at all is the assertion; before the guard this raised in Jinja.
    assert "1 booked later" in card
    assert "Garbled" not in table


def test_the_empty_state_stays_one_line(db):
    """
    At the top of the page an empty full card would push the funnel below the
    fold on every day with nothing booked.
    """
    html = _render(db)
    assert "Nothing booked." in html
    coming_up = html.split("Coming up")[1].split("source-bar")[0]
    assert "<table>" not in coming_up


# --- rounds recorded twice ---------------------------------------------------

def _dup_pair(db, company="NACE Partners", when="2026-08-25"):
    key = dict(company=company, date_added="2026-08-19",
               position_title="Product Engineer", link="thread-dup")
    db.upsert_job({**key, "status": "Phone Screen"})
    return [db.add_interview(**key, interview_type="recruiter_screen",
                             scheduled_date=when) for _ in range(2)]


def test_a_double_recorded_round_is_surfaced_for_deletion(db):
    _dup_pair(db)
    html = _render(db)

    assert "recorded twice" in html
    assert "NACE Partners" in html
    assert 'class="dup-del"' in html


def test_the_card_is_absent_when_no_round_is_doubled(db):
    key = dict(company="Solo Co", date_added="2026-08-19",
               position_title="Product Engineer", link="thread-solo")
    db.upsert_job({**key, "status": "Phone Screen"})
    db.add_interview(**key, interview_type="recruiter_screen",
                     scheduled_date="2026-08-25")

    assert "recorded twice" not in _render(db)


def test_the_delete_button_targets_the_newer_copy(db):
    first, second = _dup_pair(db)
    html = _render(db)

    assert f'data-dup-id="{second}"' in html
    assert f'data-dup-id="{first}"' not in html
