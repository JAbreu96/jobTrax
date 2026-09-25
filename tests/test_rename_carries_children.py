"""Renaming a company must take its interviews and recruiter links with it.

`jobs` has a four-column composite primary key and the child tables copy that
key in rather than referencing it, so nothing at the database level keeps them
in step. `company` is the only key column in EDITABLE_COLUMNS, which makes a
rename the one way to reach this through the API -- and until the fix these
tests cover, it silently stranded every child row.

The live database already contained 8 such orphans when this was written, so
these are regression tests for something that has happened, not a precaution.
"""

import pytest

from src import jobs_db, jobs_gui

KEY = dict(date_added="2026-01-01", position_title="Engineer", link="")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    jobs_db._reset_schema_cache()
    jobs_db.upsert_job({"company": "Acme", "status": "Tracking", **KEY})
    jobs_gui.app.config["TESTING"] = True
    with jobs_gui.app.test_client() as c:
        yield c


def _rename(client, old, new):
    return client.post("/api/jobs/update", json={
        "company": old, "field": "company", "value": new, **KEY,
    })


def _rows(table, company):
    conn = jobs_db._connect()
    try:
        return conn.execute(
            f"SELECT COUNT(*) n FROM {table} WHERE company = ?", [company]
        ).fetchone()["n"]
    finally:
        conn.close()


def test_interviews_follow_the_rename(client):
    jobs_db.add_interview(company="Acme", interview_type="phone_screen",
                          scheduled_date="2026-02-01", **KEY)

    assert _rename(client, "Acme", "Acme Corp").status_code == 200

    assert _rows("interviews", "Acme Corp") == 1
    assert _rows("interviews", "Acme") == 0


def test_recruiter_links_follow_the_rename(client):
    rid = jobs_db.upsert_recruiter(source="email", identity="r@acme.com", name="R")
    jobs_db.link_recruiter_job(rid, company="Acme", sourced_date="2026-01-05", **KEY)

    assert _rename(client, "Acme", "Acme Corp").status_code == 200

    assert _rows("recruiter_jobs", "Acme Corp") == 1
    assert _rows("recruiter_jobs", "Acme") == 0


def test_the_detail_endpoint_still_finds_the_rounds_after_a_rename(client):
    """The orphaning was invisible because every read joins on the key -- the
    rounds did not error, they just stopped appearing."""
    jobs_db.add_interview(company="Acme", interview_type="technical",
                          scheduled_date="2026-02-01", **KEY)
    _rename(client, "Acme", "Acme Corp")

    detail = client.get("/api/jobs/detail", query_string={
        "company": "Acme Corp", **KEY,
    }).get_json()

    assert len(detail["interviews"]) == 1


def test_another_companys_children_are_untouched(client):
    jobs_db.upsert_job({"company": "Globex", "status": "Tracking", **KEY})
    jobs_db.add_interview(company="Globex", interview_type="phone_screen",
                          scheduled_date="2026-02-01", **KEY)
    jobs_db.add_interview(company="Acme", interview_type="phone_screen",
                          scheduled_date="2026-02-01", **KEY)

    _rename(client, "Acme", "Acme Corp")

    assert _rows("interviews", "Globex") == 1


def test_a_rename_that_collides_leaves_children_where_they_were(client):
    """A refused rename must not move the children either.

    Today this holds because the collision SELECT returns 409 before any UPDATE
    runs, so the carry never starts -- not because anything rolls back. Pinned
    anyway: if that guard is ever moved below the writes, or the carry is
    hoisted above the parent update, this is the assertion that catches it.
    """
    jobs_db.upsert_job({"company": "Globex", "status": "Tracking", **KEY})
    jobs_db.add_interview(company="Acme", interview_type="phone_screen",
                          scheduled_date="2026-02-01", **KEY)

    assert _rename(client, "Acme", "Globex").status_code == 409

    assert _rows("interviews", "Acme") == 1
    assert _rows("interviews", "Globex") == 0


def test_editing_a_non_key_field_touches_no_children(client):
    jobs_db.add_interview(company="Acme", interview_type="phone_screen",
                          scheduled_date="2026-02-01", **KEY)

    client.post("/api/jobs/update", json={
        "company": "Acme", "field": "notes", "value": "hi", **KEY,
    })

    assert _rows("interviews", "Acme") == 1
