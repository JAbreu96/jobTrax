"""
What opening one job costs.

Against Turso every statement is a network round trip and nothing else is
measurable: SELECT 1 took 151ms, COUNT(*) over all 1,314 rows took 137ms. So
the only lever that moves this page is *how many queries there are*, not how
much work each one does -- which is why the tests below count statements and
read query plans rather than timing anything. A timing test would measure the
network and fail on a train.

Measured before: ~5,240ms across four HTTP calls and ten queries.
Measured after:  ~1,200ms across two HTTP calls and five queries.
"""

import pytest

from src import jobs_db, jobs_gui

KEY = {
    "company": "Physical Intelligence",
    "date_added": "2026-09-20",
    "position_title": "Fullstack SWE",
    "link": "",
}


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    jobs_db._reset_schema_cache()
    jobs_db.upsert_job({**KEY, "status": "Phone Screen",
                        "job_summary": "A description."})
    jobs_db.add_interview(KEY["company"], KEY["date_added"],
                          KEY["position_title"], KEY["link"],
                          "phone_screen", "2026-09-28")
    jobs_db.add_prep_item(KEY["company"], KEY["date_added"],
                          KEY["position_title"], KEY["link"],
                          "task", "Read the whitepaper")
    jobs_db.set_company_profile(KEY["company"], about="An embodied AI lab.")
    return jobs_db


@pytest.fixture
def client(db):
    jobs_gui.app.config["TESTING"] = True
    with jobs_gui.app.test_client() as c:
        yield c


def _detail(client, **flags):
    args = "&".join(f"{k}={v}" for k, v in {**KEY, **flags}.items())
    return client.get(f"/api/jobs/detail?{args}")


# --- the index --------------------------------------------------------------

def test_the_scoped_interviews_read_uses_an_index(db):
    """
    get_interviews matches on LOWER(company), and a plain column index cannot
    serve that -- SQLite reads it as an opaque expression and falls back to a
    full scan. Against the live database that read cost 797ms where the
    identically shaped prep_items read cost 142ms, which is one round trip and
    therefore the floor.

    Asserting the plan rather than the duration: the duration is network.
    """
    conn = db._connect()
    try:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM interviews "
            "WHERE LOWER(company) = LOWER(?) AND date_added = ? "
            "AND position_title = ? AND link = ?",
            ("a", "b", "c", "d"),
        ).fetchall()
    finally:
        conn.close()

    detail = " ".join(str(r[-1]) for r in plan)
    assert "SCAN interviews" not in detail, detail
    assert "USING INDEX" in detail, detail


def test_the_company_only_interviews_read_uses_an_index_too(db):
    """The MCP and digest callers pass a company and nothing else."""
    conn = db._connect()
    try:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM interviews "
            "WHERE LOWER(company) = LOWER(?)", ("a",),
        ).fetchall()
    finally:
        conn.close()

    assert "SCAN interviews" not in " ".join(str(r[-1]) for r in plan)


def test_case_insensitive_matching_still_works(db):
    """
    The index exists so the LOWER() can stay, not so it can go. Callers that
    pass a hand-typed company name depend on this.
    """
    assert len(db.get_interviews("PHYSICAL INTELLIGENCE", KEY["date_added"],
                                 KEY["position_title"], KEY["link"])) == 1


# --- the round trips --------------------------------------------------------

def _count_queries(client, monkeypatch, **flags):
    """
    Statements issued while serving one detail request.

    Through sqlite3's own trace callback rather than by wrapping execute():
    sqlite3.Connection is an immutable C type and cannot be monkeypatched. The
    callback is installed by intercepting _open_connection, which is the single
    place every connection in this codebase comes from.
    """
    seen: list[str] = []
    real_open = jobs_db._open_connection

    def tracing(*a, **k):
        conn = real_open(*a, **k)
        if conn is not None and hasattr(conn, "set_trace_callback"):
            conn.set_trace_callback(seen.append)
        return conn

    monkeypatch.setattr(jobs_db, "_open_connection", tracing)
    _detail(client, **flags)
    monkeypatch.undo()
    # PRAGMAs are connection setup, and the schema DDL runs once per path; the
    # question is how many statements the *request* costs.
    noise = ("PRAGMA", "CREATE ", "ALTER ", "BEGIN", "COMMIT")
    return [q for q in seen if not q.strip().upper().startswith(noise)]


def test_the_row_and_its_summary_come_back_in_one_query(client, monkeypatch):
    """
    They read the same row by the same key. As two statements they cost 334ms
    and 382ms against Turso -- 716ms to fetch one row, where finding it costs
    nothing. This is the single clearest instance of the general rule that the
    query count is the only thing that matters here.
    """
    queries = _count_queries(client, monkeypatch, job=1)

    from_jobs = [q for q in queries if "FROM jobs" in q]
    assert len(from_jobs) == 1, from_jobs


def test_the_whole_job_view_payload_is_five_queries(client, monkeypatch):
    # interviews, the job row, its recruiter link, prep items, the company
    # profile. Five round trips is the floor without a batch API; it was ten
    # across four HTTP calls.
    queries = _count_queries(client, monkeypatch, job=1, prep=1, company_profile=1)

    assert len(queries) == 5, "\n".join(queries)


# --- the payload ------------------------------------------------------------

def test_company_profile_rides_along_when_asked(client):
    res = _detail(client, job=1, company_profile=1)

    assert res.get_json()["company_profile"]["about"] == "An embodied AI lab."


def test_company_profile_is_left_out_unless_asked(client):
    # The table's row expand has no Company tab and should not pay for one.
    assert "company_profile" not in _detail(client, job=1).get_json()


def test_an_unresearched_company_rides_along_as_null(client, db):
    db.upsert_job({"company": "Nowhere", "date_added": "2026-01-01",
                   "position_title": "Engineer", "link": "", "status": "Tracking"})

    res = client.get("/api/jobs/detail?company=Nowhere&date_added=2026-01-01"
                     "&position_title=Engineer&link=&company_profile=1")

    assert res.get_json()["company_profile"] is None


def test_summary_and_job_still_come_back_together(client):
    payload = _detail(client, job=1).get_json()

    assert payload["job_summary"] == "A description."
    assert payload["job"]["company"] == KEY["company"]


def test_summary_can_still_be_skipped_on_its_own(client):
    payload = _detail(client, job=1, summary=0).get_json()

    assert "job_summary" not in payload
    assert payload["job"]["company"] == KEY["company"]


def test_the_job_row_carries_only_the_list_columns(client):
    """
    The merged SELECT asks for job_summary alongside them, so the row it builds
    has to be narrowed back down -- otherwise job_summary appears twice in the
    payload, once where the client does not expect it.
    """
    job = _detail(client, job=1).get_json()["job"]

    assert "job_summary" not in job
    assert set(job) >= set(jobs_db.LIST_COLUMNS)


def test_a_missing_row_answers_null_rather_than_failing(client):
    res = client.get("/api/jobs/detail?company=Ghost&date_added=2026-01-01"
                     "&position_title=&link=&job=1")

    assert res.status_code == 200
    assert res.get_json()["job"] is None
