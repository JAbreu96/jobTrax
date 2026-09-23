"""
Every company named on Insights links into the job list's search.

The page names companies in seven places and, until now, none of them went
anywhere -- reading "NACE Partners, silent 34 days" meant switching tabs and
retyping the name. The link carries the company only: the list matches one
substring against company/title/notes/location joined together, so a
"Company Role" query would match nothing at all.

include_archived rides along because the tables these links sit in are not
filtered on archived -- unlinked_recruiter_rows has no archived clause, and an
interview round can outlive the job row it points at. Without it a link to an
archived company lands on an empty table, which reads as "no such job".
"""

import pytest

from src import jobs_db
# Imported at module scope for the reason test_insights_view.py documents:
# importing jobs_gui mid-test re-runs load_dotenv and repoints the render at
# production.
from src import jobs_gui


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    jobs_db._reset_schema_cache()
    return jobs_db


def _job(db, company, title="Engineer", status="Phone Screen", link="thread-1"):
    db.upsert_job({"company": company, "position_title": title, "link": link,
                   "date_added": "2026-08-19", "status": status,
                   "date_applied": "2026-08-19"})
    return dict(company=company, date_added="2026-08-19",
                position_title=title, link=link)


def _render(db):
    assert not jobs_db._use_libsql(), "render test is pointed at the remote database"
    jobs_gui.app.config["TESTING"] = True
    with jobs_gui.app.test_client() as client:
        return client.get("/insights").get_data(as_text=True)


def test_an_upcoming_rounds_company_links_to_the_search(db):
    from datetime import date, timedelta
    key = _job(db, "Sciforium")
    db.add_interview(**key, interview_type="phone_screen",
                     scheduled_date=(date.today() + timedelta(days=3)).isoformat())

    assert 'href="/?q=Sciforium&amp;include_archived=1"' in _render(db)


def test_a_company_with_a_space_is_encoded(db):
    """A raw space in an href is the difference between a link and a 404."""
    from datetime import date, timedelta
    key = _job(db, "NACE Partners")
    db.add_interview(**key, interview_type="phone_screen",
                     scheduled_date=(date.today() + timedelta(days=3)).isoformat())

    html = _render(db)

    assert "/?q=NACE%20Partners" in html or "/?q=NACE+Partners" in html
    assert 'href="/?q=NACE Partners' not in html


def test_a_duplicate_rounds_company_links_without_eating_the_delete_button(db):
    """
    The row owns a Delete button. A whole-row link would have swallowed it --
    which is why only the company cell is linked.
    """
    key = _job(db, "NACE Partners")
    db.add_interview(**key, interview_type="recruiter_screen", scheduled_date="2026-08-25")
    db.add_interview(**key, interview_type="recruiter_screen", scheduled_date="2026-08-25")

    html = _render(db)

    assert "/?q=NACE" in html
    assert 'class="dup-del"' in html


def test_a_silent_companys_row_links(db):
    _job(db, "Quietco", status="Applied")

    html = _render(db)

    assert "/?q=Quietco" in html


def test_the_round_type_table_grows_no_links(db):
    """
    'technical' is a round type, not a company. Linking it would search the
    notes of every job for the word.
    """
    key = _job(db, "Sciforium")
    db.add_interview(**key, interview_type="technical", scheduled_date="2026-08-01")

    assert "/?q=technical" not in _render(db)
