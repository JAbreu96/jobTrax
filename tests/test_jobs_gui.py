"""
The GUI's read path.

Two things here are shaped by constraints rather than taste:

`/api/jobs` deliberately omits job_summary -- it was two thirds of the payload
and appears nowhere in the table -- while keeping `notes`, which the search box
matches against. A test asserts both halves, because dropping the wrong column
breaks search silently: the filter just stops matching.

The duplicate-company 409 is detected with a SELECT rather than by catching the
UPDATE's exception, because conftest strips TURSO_* for the whole session and so
no test can ever observe what libSQL raises. A SELECT behaves the same on both
drivers, which is what makes the case testable here at all.
"""

import sqlite3

import pytest

from src import jobs_db, jobs_gui


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    jobs_db._reset_schema_cache()
    jobs_db.upsert_job({
        "company": "Acme", "position_title": "Engineer", "link": "",
        "date_added": "2026-01-01", "job_summary": "A long job description.",
        "notes": "applypass auto-applied", "status": "Tracking",
    })
    jobs_db.upsert_job({
        "company": "Globex", "position_title": "Engineer", "link": "",
        "date_added": "2026-01-01", "job_summary": "Another description.",
        "notes": "", "status": "Tracking",
    })
    jobs_gui.app.config["TESTING"] = True
    with jobs_gui.app.test_client() as c:
        yield c


def test_list_columns_drops_job_summary():
    assert "job_summary" not in jobs_db.LIST_COLUMNS


def test_list_columns_keeps_notes_for_the_search_box():
    assert "notes" in jobs_db.LIST_COLUMNS


def test_list_columns_tracks_columns():
    """Derived, not hand-written: a new column must reach the GUI on its own."""
    assert set(jobs_db.LIST_COLUMNS) == set(jobs_db.COLUMNS) - {"job_summary"}


def test_write_exc_covers_both_drivers():
    assert sqlite3.IntegrityError in jobs_db._WRITE_EXC
    assert ValueError in jobs_db._WRITE_EXC


def test_jobs_list_omits_job_summary(client):
    rows = client.get("/api/jobs").get_json()
    assert rows
    assert all("job_summary" not in r for r in rows)


def test_jobs_list_still_carries_notes(client):
    rows = client.get("/api/jobs").get_json()
    assert any(r["notes"] == "applypass auto-applied" for r in rows)


def test_detail_returns_the_summary_the_list_withheld(client):
    data = client.get("/api/jobs/detail", query_string={
        "company": "Acme", "date_added": "2026-01-01",
        "position_title": "Engineer", "link": "",
    }).get_json()
    assert data["job_summary"] == "A long job description."
    assert data["interviews"] == []


def test_detail_skips_the_summary_when_the_client_has_it(client):
    data = client.get("/api/jobs/detail", query_string={
        "company": "Acme", "date_added": "2026-01-01",
        "position_title": "Engineer", "link": "", "summary": "0",
    }).get_json()
    assert "job_summary" not in data
    assert "interviews" in data


def test_detail_returns_rounds_for_the_job(client):
    jobs_db.add_interview(company="Acme", date_added="2026-01-01",
                          position_title="Engineer", link="",
                          interview_type="technical", occurred_date="2026-02-01")
    data = client.get("/api/jobs/detail", query_string={
        "company": "Acme", "date_added": "2026-01-01",
        "position_title": "Engineer", "link": "", "summary": "0",
    }).get_json()
    assert [r["interview_type"] for r in data["interviews"]] == ["technical"]


def test_detail_does_not_leak_another_jobs_rounds(client):
    jobs_db.add_interview(company="Acme", date_added="2026-01-01",
                          position_title="Engineer", link="",
                          interview_type="technical", occurred_date="2026-02-01")
    data = client.get("/api/jobs/detail", query_string={
        "company": "Globex", "date_added": "2026-01-01",
        "position_title": "Engineer", "link": "", "summary": "0",
    }).get_json()
    assert data["interviews"] == []


def test_renaming_onto_an_existing_key_is_rejected(client):
    res = client.post("/api/jobs/update", json={
        "company": "Acme", "date_added": "2026-01-01",
        "position_title": "Engineer", "link": "",
        "field": "company", "value": "Globex",
    })
    assert res.status_code == 409
    assert "already exists" in res.get_json()["error"]


def test_the_rejected_rename_left_the_row_alone(client):
    client.post("/api/jobs/update", json={
        "company": "Acme", "date_added": "2026-01-01",
        "position_title": "Engineer", "link": "",
        "field": "company", "value": "Globex",
    })
    companies = [r["company"] for r in client.get("/api/jobs").get_json()]
    assert sorted(companies) == ["Acme", "Globex"]


def test_a_rename_to_a_free_key_still_works(client):
    res = client.post("/api/jobs/update", json={
        "company": "Acme", "date_added": "2026-01-01",
        "position_title": "Engineer", "link": "",
        "field": "company", "value": "Initech",
    })
    assert res.status_code == 200
    companies = [r["company"] for r in client.get("/api/jobs").get_json()]
    assert sorted(companies) == ["Globex", "Initech"]


# --- the recruiter write path -----------------------------------------------
# api_recruiters used to state that the GUI never writes recruiter rows. It does
# now; what replaced the rule is the two protections exercised below.

def _keys(client):
    job = client.get("/api/jobs").get_json()[0]
    return {k: job[k] for k in ("company", "date_added", "position_title", "link")}


def test_add_recruiter_requires_an_email_as_its_identity(client):
    res = client.post("/api/recruiters/add", json={"name": "Jo"})
    assert res.status_code == 400
    assert "email" in res.get_json()["error"].lower()


def test_add_recruiter_creates_a_manual_row(client):
    res = client.post("/api/recruiters/add", json={
        "name": "Joanna Reyes", "agency": "Reyes Talent", "email": "jo@agency.com",
    })
    assert res.status_code == 200
    row = res.get_json()["recruiter"]
    assert (row["name"], row["agency"], row["manual_entry"]) == (
        "Joanna Reyes", "Reyes Talent", 1)
    # Keyed as email, not a separate 'manual' source, so a later inbound message
    # from the same address lands on this row instead of making a second one.
    assert (row["source"], row["identity"]) == ("email", "jo@agency.com")


def test_assigning_a_recruiter_shows_up_on_the_job_row(client):
    rid = client.post("/api/recruiters/add", json={
        "name": "Joanna Reyes", "agency": "Reyes Talent", "email": "jo@agency.com",
    }).get_json()["recruiter"]["id"]
    key = _keys(client)

    res = client.post("/api/jobs/recruiter", json={**key, "recruiter_id": rid})
    assert res.status_code == 200

    job = next(j for j in client.get("/api/jobs").get_json()
               if j["company"] == key["company"])
    assert job["recruiter_agency"] == "Reyes Talent"
    assert job["recruiter_id"] == rid
    assert job["recruiter_from_triage"] is False


def test_assigning_a_recruiter_leaves_contacts_alone(client):
    """
    record_recruiter_outreach denormalises the recruiter into jobs.contacts; the
    GUI deliberately does not. The badge reads through recruiter_jobs, so the
    copy is legacy, and writing it would silently overwrite a hand-edited field.
    """
    client.post("/api/jobs/update", json={**_keys(client),
                                          "field": "contacts",
                                          "value": "someone I typed"})
    rid = client.post("/api/recruiters/add", json={
        "name": "Jo", "email": "jo@agency.com"}).get_json()["recruiter"]["id"]
    client.post("/api/jobs/recruiter", json={**_keys(client), "recruiter_id": rid})

    job = next(j for j in client.get("/api/jobs").get_json()
               if j["company"] == _keys(client)["company"])
    assert job["contacts"] == "someone I typed"


def test_clearing_a_recruiter(client):
    rid = client.post("/api/recruiters/add", json={
        "name": "Jo", "email": "jo@agency.com"}).get_json()["recruiter"]["id"]
    key = _keys(client)
    client.post("/api/jobs/recruiter", json={**key, "recruiter_id": rid})

    res = client.post("/api/jobs/recruiter", json={**key, "recruiter_id": None})
    assert res.status_code == 200
    assert res.get_json()["recruiter"] is None


def test_a_triage_link_returns_409_with_the_message_it_came_from(client):
    key = _keys(client)
    triage = jobs_db.upsert_recruiter("linkedin", "triage-person",
                                      name="Triage Person")
    jobs_db.link_recruiter_job(triage, sourced_date="2026-08-20", account="alt",
                               message_id="MSG-ABC-123", **key)
    rid = client.post("/api/recruiters/add", json={
        "name": "Jo", "email": "jo@agency.com"}).get_json()["recruiter"]["id"]

    res = client.post("/api/jobs/recruiter", json={**key, "recruiter_id": rid})
    assert res.status_code == 409
    assert res.get_json()["blocked"][0]["message_id"] == "MSG-ABC-123"

    # And the override goes through.
    ok = client.post("/api/jobs/recruiter",
                     json={**key, "recruiter_id": rid, "override": True})
    assert ok.status_code == 200
    assert ok.get_json()["recruiter"]["recruiter_name"] == "Jo"


def test_job_row_flags_a_triage_sourced_link_as_read_only(client):
    key = _keys(client)
    triage = jobs_db.upsert_recruiter("linkedin", "triage-person", name="T")
    jobs_db.link_recruiter_job(triage, sourced_date="2026-08-20", account="alt",
                               message_id="MSG-1", **key)
    job = next(j for j in client.get("/api/jobs").get_json()
               if j["company"] == key["company"])
    assert job["recruiter_from_triage"] is True


def test_delete_recruiter_names_what_it_destroyed(client):
    key = _keys(client)
    rid = client.post("/api/recruiters/add", json={
        "name": "Jo", "email": "jo@agency.com"}).get_json()["recruiter"]["id"]
    client.post("/api/jobs/recruiter", json={**key, "recruiter_id": rid})
    jobs_db.record_recruiter_message(rid, "inbound", "2026-08-20", message_id="M1")

    res = client.post("/api/recruiters/delete", json={"recruiter_id": rid})
    assert res.status_code == 200
    assert (res.get_json()["jobs"], res.get_json()["messages"]) == (1, 1)

    job = next(j for j in client.get("/api/jobs").get_json()
               if j["company"] == key["company"])
    assert job["recruiter_id"] is None


def test_updating_a_recruiter_protects_it_from_the_next_parse(client):
    rid = jobs_db.upsert_recruiter("email", "jo@agency.com", name="Parsed")
    client.post("/api/recruiters/update",
                json={"recruiter_id": rid, "name": "Corrected By Hand"})
    jobs_db.upsert_recruiter("email", "jo@agency.com", name="Parsed Again")

    row = next(r for r in jobs_db.get_recruiters() if r["id"] == rid)
    assert row["name"] == "Corrected By Hand"


def test_recruiter_link_is_not_an_editable_job_column(client):
    """
    /api/jobs/update interpolates the column name into its SQL and is safe only
    because EDITABLE_COLUMNS gates it. The recruiter link must stay out.
    """
    assert "recruiter" not in jobs_gui.EDITABLE_COLUMNS
    assert "recruiter_id" not in jobs_gui.EDITABLE_COLUMNS
    res = client.post("/api/jobs/update", json={**_keys(client),
                                                "field": "recruiter_id",
                                                "value": "1"})
    assert res.status_code == 400


def test_non_numeric_recruiter_id_is_a_400_not_a_500(client):
    """
    A body like {"recruiter_id": "abc"} reached int() unguarded and raised,
    so these two routes answered 500 where api_delete_interview -- a few lines
    above them in the same file -- answers 400 for the same mistake.
    """
    for route in ("/api/recruiters/delete", "/api/recruiters/update"):
        res = client.post(route, json={"recruiter_id": "abc", "name": "x"})
        assert res.status_code == 400, route


def test_setting_a_job_recruiter_rejects_a_non_numeric_id(client):
    res = client.post("/api/jobs/recruiter",
                      json={**_keys(client), "recruiter_id": "abc"})
    assert res.status_code == 400


def test_clearing_a_job_recruiter_is_still_allowed(client):
    """
    The guard above must not catch null: clearing the link is a legitimate
    request, and only a present-but-unparseable value is an error.
    """
    res = client.post("/api/jobs/recruiter",
                      json={**_keys(client), "recruiter_id": None})
    assert res.status_code == 200
    assert res.get_json()["recruiter"] is None


def test_assigning_an_unknown_recruiter_is_404_not_a_silent_success(client):
    res = client.post("/api/jobs/recruiter",
                      json={**_keys(client), "recruiter_id": 9999})
    assert res.status_code == 404
    job = next(j for j in client.get("/api/jobs").get_json()
               if j["company"] == _keys(client)["company"])
    assert job["recruiter_id"] is None


def test_delete_dry_run_previews_without_destroying(client):
    rid = client.post("/api/recruiters/add", json={
        "name": "Jo", "email": "jo@agency.com"}).get_json()["recruiter"]["id"]
    client.post("/api/jobs/recruiter", json={**_keys(client), "recruiter_id": rid})
    jobs_db.record_recruiter_message(rid, "inbound", "2026-08-20", message_id="M1")

    preview = client.post("/api/recruiters/delete",
                          json={"recruiter_id": rid, "dry_run": True}).get_json()
    assert (preview["jobs"], preview["messages"]) == (1, 1)
    assert any(r["id"] == rid for r in jobs_db.get_recruiters())   # still there

    real = client.post("/api/recruiters/delete",
                       json={"recruiter_id": rid}).get_json()
    assert (real["jobs"], real["messages"]) == (preview["jobs"], preview["messages"])
    assert not any(r["id"] == rid for r in jobs_db.get_recruiters())


# --- paging the list --------------------------------------------------------
#
# The list page paints the first rows and then prefetches the rest, so the whole
# table still ends up in the browser -- the paging exists to get something on
# screen sooner, not to send less. That makes "every row exactly once" the
# property worth testing: a cursor that skips or repeats a row silently corrupts
# the array that search, sort and the counters all run against.


@pytest.fixture
def paged(tmp_path, monkeypatch):
    """
    Nine jobs, six of them sharing one date_added.

    The ties are the point. date_added is not unique, so a cursor that carries
    only the date cannot say where inside a tied run it stopped, and pages
    either lose rows or repeat them. Three dates keeps a boundary landing
    mid-run.
    """
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    jobs_db._reset_schema_cache()
    rows = [
        ("Alpha",   "2026-03-01"), ("Bravo",   "2026-02-01"),
        ("Charlie", "2026-02-01"), ("Delta",   "2026-02-01"),
        ("Echo",    "2026-02-01"), ("Foxtrot", "2026-02-01"),
        ("Golf",    "2026-02-01"), ("Hotel",   "2026-01-01"),
    ]
    for company, date_added in rows:
        jobs_db.upsert_job({
            "company": company, "position_title": "Engineer", "link": "",
            "date_added": date_added, "status": "Tracking",
        })
    jobs_db.upsert_job({
        "company": "Zulu", "position_title": "Engineer", "link": "",
        "date_added": "2026-02-01", "status": "Tracking",
    })
    # upsert_job has no archived field -- it is set by archive_jobs, on age.
    with jobs_db.shared_connection() as conn:
        conn.execute("UPDATE jobs SET archived = 1 WHERE company = 'Zulu'")
        conn.commit()
    jobs_gui.app.config["TESTING"] = True
    with jobs_gui.app.test_client() as c:
        yield c


def _walk(client, limit, **params):
    """Pages to exhaustion, returning the row keys in the order they arrived."""
    keys, cursor, requests = [], None, 0
    while True:
        query = {"limit": limit, **params}
        if cursor:
            query["cursor"] = cursor
        body = client.get("/api/jobs", query_string=query).get_json()
        keys += [(j["company"], j["date_added"], j["position_title"], j["link"])
                 for j in body["jobs"]]
        cursor = body["next_cursor"]
        requests += 1
        assert requests < 50, "paging did not terminate"
        if cursor is None:
            return keys


def test_no_limit_still_returns_the_whole_list_as_a_bare_array(paged):
    """
    The unpaginated shape is load-bearing: kanban.html and the insights
    drill-through both read /api/jobs and neither passes a limit.
    """
    body = paged.get("/api/jobs").get_json()
    assert isinstance(body, list)
    assert len(body) == 8


def test_a_limit_switches_the_response_to_a_paged_envelope(paged):
    body = paged.get("/api/jobs", query_string={"limit": 3}).get_json()
    assert [*body] == ["jobs", "next_cursor"]
    assert len(body["jobs"]) == 3
    assert body["next_cursor"]


def test_paging_yields_every_row_exactly_once(paged):
    walked = _walk(paged, limit=3)
    whole = [(j["company"], j["date_added"], j["position_title"], j["link"])
             for j in paged.get("/api/jobs").get_json()]
    assert walked == whole
    assert len(set(walked)) == len(walked)


def test_one_row_at_a_time_survives_the_tied_dates(paged):
    """
    limit=1 puts a page boundary between every pair of tied rows -- the case a
    date-only cursor gets wrong, and it gets it wrong by looping forever or by
    dropping the whole tied run.
    """
    walked = _walk(paged, limit=1)
    assert len(walked) == 8
    assert len(set(walked)) == 8


def test_the_last_page_closes_the_cursor(paged):
    body = paged.get("/api/jobs", query_string={"limit": 100}).get_json()
    assert len(body["jobs"]) == 8
    assert body["next_cursor"] is None


def test_archived_rows_page_the_same_way_they_list(paged):
    walked = _walk(paged, limit=2, include_archived=1)
    whole = [(j["company"], j["date_added"], j["position_title"], j["link"])
             for j in paged.get("/api/jobs",
                                query_string={"include_archived": 1}).get_json()]
    assert walked == whole
    assert len(walked) == 9          # the archived row is in, and only once


def test_a_junk_cursor_is_rejected_rather_than_restarting_the_list(paged):
    """
    Silently falling back to page one would make the prefetch loop repeat the
    top of the list forever instead of failing.
    """
    for junk in ("not-base64", "", "!!!!"):
        assert paged.get("/api/jobs",
                         query_string={"limit": 2, "cursor": junk}).status_code == 400


def test_a_non_integer_limit_is_rejected(paged):
    assert paged.get("/api/jobs", query_string={"limit": "all"}).status_code == 400


def test_limit_is_clamped_rather_than_trusted(paged):
    body = paged.get("/api/jobs", query_string={"limit": 100000}).get_json()
    assert len(body["jobs"]) == 8
    assert paged.get("/api/jobs", query_string={"limit": 0}).status_code == 400
