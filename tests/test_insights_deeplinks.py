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


def _section(html, start, end):
    """
    The slice of the page strictly between `start` and the following `end`.

    Mirrors test_insights_view.py's _card() helper: several tables share a
    page, and a plain substring check on the whole page would pass through
    whichever OTHER table happens to also carry the company. Returns "" if
    `start` never appears -- a section the template didn't render at all
    trivially cannot contain the company either.
    """
    if start not in html:
        return ""
    return html.split(start, 1)[1].split(end, 1)[0]


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


def test_a_missing_rounds_company_links(db):
    """
    'Missing rounds' names jobs at Phone Screen or later with no round in
    `interviews`. Its line was a `join(", ")` over a list of company strings,
    so it took a loop rather than a single macro call to keep each company
    its own link.

    date_applied is pinned to today rather than reused from `_job()`'s
    hardcoded 2026-08-19: that date is permanently stale against
    date.today(), and a stale Phone-Screen row also crosses into
    job_silence_stats()['ghosted_rows'] -- which would let this test pass
    even if the missing-rounds call site regressed, as long as the ghosted
    one still worked. A fresh date keeps this fixture out of the silence
    tables entirely, so the assertion below can only be satisfied by the
    missing-rounds call site.
    """
    from datetime import date
    today = date.today().isoformat()
    db.upsert_job({"company": "Sciforium", "position_title": "Engineer",
                   "link": "thread-missing", "date_added": today,
                   "status": "Phone Screen", "date_applied": today})
    assert [r["company"] for r in jobs_db.jobs_missing_interview_rows()] == ["Sciforium"], \
        "fixture did not land in jobs_missing_interview_rows()"
    assert jobs_db.job_silence_stats()["ghosted_rows"] == [], \
        "fixture leaked into ghosted_rows -- fixture is not isolated to missing rounds"

    html = _render(db)

    missing = _section(html, "no round recorded", "</p>")
    ghosted_table = _section(html, "Ghosted</h2>", "</table>")

    assert 'href="/?q=Sciforium&amp;include_archived=1"' in missing
    assert "Sciforium" not in ghosted_table


def test_a_ghosted_companys_row_links(db):
    """
    Ghosted means someone engaged and then went quiet. Built via a recruiter
    message rather than a Phone-Screen status: a screening status makes the
    job unconditionally qualify for jobs_missing_interview_rows() too (that
    query has no date filter), which would let this test pass on the
    missing-rounds call site alone. A recruiter_message signal on an
    "Applied" job ghosts the row without ever touching an interviewing
    status, so only the Ghosted call site can satisfy the assertion below.
    """
    from datetime import date, timedelta
    stale = (date.today() - timedelta(days=jobs_db.GHOSTED_AFTER_DAYS + 5)).isoformat()
    key = dict(company="Fadeaway Inc", date_added=stale,
               position_title="Engineer", link="thread-fade")
    db.upsert_job({**key, "status": "Applied"})
    rid = jobs_db.upsert_recruiter(source="linkedin", identity="fade-scout",
                                   name="Fade Scout", seen_date=stale)
    jobs_db.link_recruiter_job(rid, sourced_date=stale, **key)
    jobs_db.record_recruiter_message(rid, direction="inbound", occurred_date=stale)

    assert [r["company"] for r in jobs_db.job_silence_stats()["ghosted_rows"]] == ["Fadeaway Inc"], \
        "fixture did not land in job_silence_stats()['ghosted_rows']"
    assert jobs_db.jobs_missing_interview_rows() == [], \
        "fixture leaked into jobs_missing_interview_rows() -- fixture is not isolated to ghosted"

    html = _render(db)

    ghosted_table = _section(html, "Ghosted</h2>", "</table>")
    missing = _section(html, "no round recorded", "</p>")

    assert ('href="/?q=Fadeaway Inc' in ghosted_table
            or 'href="/?q=Fadeaway%20Inc' in ghosted_table)
    assert "Fadeaway Inc" not in missing


def test_no_response_auto_marker_stays_outside_the_link(db):
    """
    (auto) describes how the job was applied to, not where the link goes --
    it has to sit outside the <a>, or clicking near the marker would silently
    carry the reader to the same place as clicking the company.
    """
    from datetime import date, timedelta
    stale = (date.today() - timedelta(days=jobs_db.NO_RESPONSE_AFTER_DAYS + 5)).isoformat()
    db.upsert_job({"company": "Autosilent Co", "position_title": "Engineer",
                   "link": "thread-auto", "date_added": stale, "status": "Applied",
                   "date_applied": stale, "notes": "Imported from auto-apply export"})
    no_response = jobs_db.job_silence_stats()["no_response_rows"]
    assert len(no_response) == 1 and no_response[0]["auto_applied"] is True, \
        "fixture did not land as an auto-applied no_response row"

    html = _render(db)

    assert 'href="/?q=Autosilent Co' in html or 'href="/?q=Autosilent%20Co' in html
    # The marker must not be inside the anchor's text.
    assert '(auto)</a>' not in html
    assert '<span class="muted">(auto)</span>' in html
    link_end = html.index('Autosilent')
    anchor_close = html.index("</a>", link_end)
    marker_pos = html.index("(auto)", link_end)
    assert marker_pos > anchor_close, "(auto) marker landed inside the anchor"


def test_a_recruiter_role_sub_row_links_the_company_not_the_role(db):
    """
    This sub-row renders the role title with no company in sight -- but the
    `role` dict carries one. Link text stays the role; the href has to target
    the company, which is the one thing nothing else pins down.
    """
    rid = jobs_db.upsert_recruiter(source="linkedin", identity="scout-1",
                                   name="Scout", seen_date="2026-08-19")
    jobs_db.link_recruiter_job(rid, company="RoleCo", date_added="2026-08-19",
                               position_title="Special Role", link="thread-role")
    roles = jobs_db.get_recruiter_jobs()
    assert [r["position_title"] for r in roles] == ["Special Role"], \
        "fixture did not land in get_recruiter_jobs()"

    html = _render(db)

    assert 'href="/?q=RoleCo&amp;include_archived=1"' in html
    assert '>Special Role</a>' in html
    assert 'href="/?q=Special Role' not in html
    assert 'href="/?q=Special%20Role' not in html


def test_a_suspected_uncaptured_company_links(db):
    """
    coverage.rows comes from unlinked_recruiter_rows(): a job whose link
    shape looks like inbound outreach (a conversation, not a posting) with no
    recruiter recorded against it. The recruiters table itself must also be
    non-empty, or the template's outer `{% if recruiters %}` hides the whole
    section including this one.

    date_applied is pinned to today rather than reused from `_job()`'s
    hardcoded 2026-08-19: that date is over 30 days stale against
    date.today(), which crosses NO_RESPONSE_AFTER_DAYS and lands the same row
    in job_silence_stats()['no_response_rows'] too -- letting this test pass
    on the No-response call site alone. A fresh date_applied keeps the row
    "waiting", so only the Suspected-not-captured call site can satisfy the
    assertion below.
    """
    from datetime import date
    today = date.today().isoformat()
    jobs_db.upsert_recruiter(source="linkedin", identity="unrelated-scout",
                             name="Unrelated Scout", seen_date=today)
    jobs_db.upsert_job({"company": "Undercover Co", "position_title": "Engineer",
                        "link": "mailto:someone@undercover.example",
                        "date_added": today, "status": "Applied",
                        "date_applied": today})
    rows = jobs_db.recruiter_coverage()["rows"]
    assert [r["company"] for r in rows] == ["Undercover Co"], \
        "fixture did not land in recruiter_coverage()['rows']"
    assert jobs_db.job_silence_stats()["no_response_rows"] == [], \
        "fixture leaked into no_response_rows -- fixture is not isolated to coverage.rows"

    html = _render(db)

    suspected = _section(html, "Suspected, not captured</h2>", "</table>")
    no_response_table = _section(html, "No response", "</table>")

    assert ('href="/?q=Undercover Co' in suspected
            or 'href="/?q=Undercover%20Co' in suspected)
    assert "Undercover Co" not in no_response_table


def test_a_company_with_an_ampersand_is_encoded(db):
    """
    An unencoded '&' inside a query string starts a second parameter instead
    of naming the company -- this is what would silently break if `urlencode`
    were ever dropped from the macro.
    """
    _job(db, "Barnes & Noble", status="Applied")

    html = _render(db)

    assert 'href="/?q=Barnes%20%26%20Noble&amp;include_archived=1"' in html
