"""
The prep checklist: one table for tasks and questions.

The thing worth stating up front is why there is one table and not two. A task
and a question have the same shape, the same lifecycle and the same two states,
and `done` on a question means "asked" -- which is the state you need mid-loop
and cannot get anywhere else. Two tables would duplicate every read, write and
rename path to distinguish rows that differ by one word.

Unlike `companies`, these are keyed on the job: preparing for a screen at one
company is not preparing for the other role there. That also means a company
rename orphans them exactly the way it orphans `interviews`, so they join the
carry list.
"""

import pytest

from src import jobs_db, jobs_gui

KEY = ("Physical Intelligence", "2026-09-20", "Fullstack SWE", "")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    jobs_db._reset_schema_cache()
    jobs_db.upsert_job({
        "company": KEY[0], "date_added": KEY[1], "position_title": KEY[2],
        "link": KEY[3], "status": "Phone Screen",
    })
    return jobs_db


@pytest.fixture
def client(db):
    jobs_gui.app.config["TESTING"] = True
    with jobs_gui.app.test_client() as c:
        yield c


# --- storage ----------------------------------------------------------------

def test_job_with_no_prep_reads_as_an_empty_list(db):
    assert db.get_prep_items(*KEY) == []


def test_add_then_read_round_trips(db):
    db.add_prep_item(*KEY, "task", "Re-read the whitepaper")

    items = db.get_prep_items(*KEY)
    assert [i["body"] for i in items] == ["Re-read the whitepaper"]
    assert items[0]["done"] == 0


def test_tasks_sort_before_questions(db):
    db.add_prep_item(*KEY, "question", "What does success look like?")
    db.add_prep_item(*KEY, "task", "Re-read the whitepaper")

    assert [i["kind"] for i in db.get_prep_items(*KEY)] == ["task", "question"]


def test_items_keep_insertion_order_within_a_kind(db):
    for body in ("first", "second", "third"):
        db.add_prep_item(*KEY, "task", body)

    assert [i["body"] for i in db.get_prep_items(*KEY)] == [
        "first", "second", "third"]


def test_ticking_an_item_does_not_move_it(db):
    """
    A list that reshuffles as you tick loses your place five minutes before a
    screen, which is the one moment that costs something.
    """
    for body in ("first", "second", "third"):
        db.add_prep_item(*KEY, "task", body)
    second = db.get_prep_items(*KEY)[1]

    db.set_prep_item_done(second["id"], True)

    items = db.get_prep_items(*KEY)
    assert [i["body"] for i in items] == ["first", "second", "third"]
    assert items[1]["done"] == 1


def test_each_kind_numbers_its_own_positions(db):
    """
    sort_order is per (job, kind). Sharing one counter would leave the questions
    starting at 3 and sorting correctly only by accident.
    """
    db.add_prep_item(*KEY, "task", "a task")
    db.add_prep_item(*KEY, "question", "a question")

    by_kind = {i["kind"]: i["sort_order"] for i in db.get_prep_items(*KEY)}
    assert by_kind == {"task": 0, "question": 0}


def test_a_blank_body_is_refused(db):
    assert db.add_prep_item(*KEY, "task", "   ") is None
    assert db.get_prep_items(*KEY) == []


def test_an_unknown_kind_is_refused(db):
    """
    A third kind would be stored and then never rendered -- the tab draws
    exactly two sections -- so it has to fail at the boundary.
    """
    assert db.add_prep_item(*KEY, "reminder", "something") is None


def test_prep_is_scoped_to_one_role_not_the_company(db):
    db.upsert_job({
        "company": KEY[0], "date_added": "2026-09-21",
        "position_title": "Robotics Engineer", "link": "", "status": "Tracking",
    })
    db.add_prep_item(*KEY, "task", "Fullstack prep")

    assert db.get_prep_items(KEY[0], "2026-09-21", "Robotics Engineer", "") == []


def test_editing_rewrites_the_body(db):
    db.add_prep_item(*KEY, "task", "Old text")
    item = db.get_prep_items(*KEY)[0]

    assert db.update_prep_item(item["id"], "New text")
    assert db.get_prep_items(*KEY)[0]["body"] == "New text"


def test_editing_to_blank_is_refused(db):
    db.add_prep_item(*KEY, "task", "Old text")
    item = db.get_prep_items(*KEY)[0]

    assert db.update_prep_item(item["id"], "   ") is False
    assert db.get_prep_items(*KEY)[0]["body"] == "Old text"


def test_deleting_removes_only_that_item(db):
    db.add_prep_item(*KEY, "task", "keep me")
    db.add_prep_item(*KEY, "task", "delete me")
    doomed = db.get_prep_items(*KEY)[1]

    assert db.delete_prep_item(doomed["id"])
    assert [i["body"] for i in db.get_prep_items(*KEY)] == ["keep me"]


# --- the GUI ----------------------------------------------------------------

def test_detail_omits_prep_unless_asked(client, db):
    db.add_prep_item(*KEY, "task", "Re-read the whitepaper")

    res = client.get("/api/jobs/detail?company=Physical Intelligence"
                     "&date_added=2026-09-20&position_title=Fullstack SWE&link=")

    assert "prep_items" not in res.get_json()


def test_detail_carries_prep_when_asked(client, db):
    db.add_prep_item(*KEY, "task", "Re-read the whitepaper")

    res = client.get("/api/jobs/detail?company=Physical Intelligence"
                     "&date_added=2026-09-20&position_title=Fullstack SWE"
                     "&link=&prep=1")

    assert len(res.get_json()["prep_items"]) == 1


def test_add_endpoint_rejects_an_unknown_kind(client):
    res = client.post("/api/prep/add", json={
        "company": KEY[0], "date_added": KEY[1], "position_title": KEY[2],
        "link": KEY[3], "kind": "reminder", "body": "x",
    })

    assert res.status_code == 400


def test_add_endpoint_rejects_a_blank_body(client):
    res = client.post("/api/prep/add", json={
        "company": KEY[0], "date_added": KEY[1], "position_title": KEY[2],
        "link": KEY[3], "kind": "task", "body": "   ",
    })

    assert res.status_code == 400


def test_update_endpoint_needs_either_done_or_body(client, db):
    db.add_prep_item(*KEY, "task", "x")
    item = db.get_prep_items(*KEY)[0]

    res = client.post("/api/prep/update", json={"id": item["id"]})

    assert res.status_code == 400


def test_update_endpoint_404s_on_a_missing_item(client):
    res = client.post("/api/prep/update", json={"id": 9999, "done": True})

    assert res.status_code == 404


def test_renaming_the_company_carries_the_prep_rows(client, db):
    """
    The composite key enforces nothing, so without this the checklist is still
    in the table and belongs to a job that no longer exists.
    """
    db.add_prep_item(*KEY, "task", "Re-read the whitepaper")

    res = client.post("/api/jobs/update", json={
        "company": KEY[0], "date_added": KEY[1], "position_title": KEY[2],
        "link": KEY[3], "field": "company", "value": "Physical Intelligence Inc",
    })

    assert res.get_json()["prep_items_moved"] == 1
    assert len(db.get_prep_items(
        "Physical Intelligence Inc", KEY[1], KEY[2], KEY[3])) == 1
    assert db.get_prep_items(*KEY) == []


def test_prep_carry_is_unconditional_unlike_the_company_profile(client, db):
    """
    A second role at the company does NOT hold these rows back. The profile is
    shared and must not be moved out from under a sibling; prep belongs to this
    posting and to nothing else.
    """
    db.upsert_job({
        "company": KEY[0], "date_added": "2026-09-21",
        "position_title": "Robotics Engineer", "link": "", "status": "Tracking",
    })
    db.add_prep_item(*KEY, "task", "Fullstack prep")

    res = client.post("/api/jobs/update", json={
        "company": KEY[0], "date_added": KEY[1], "position_title": KEY[2],
        "link": KEY[3], "field": "company", "value": "Physical Intelligence Inc",
    })

    assert res.get_json()["prep_items_moved"] == 1
    assert res.get_json()["company_profile_moved"] is False


# --- the MCP tools ----------------------------------------------------------

def test_mcp_appends_rather_than_replacing(db):
    """
    The candidate ticks items off and writes their own between research passes.
    A replacing write would throw that away.
    """
    from mcp_servers.job_tracker import server

    server.add_prep_plan(KEY[0], tasks=["First task"])
    server.add_prep_plan(KEY[0], tasks=["Second task"])

    assert [i["body"] for i in db.get_prep_items(*KEY)] == [
        "First task", "Second task"]


def test_mcp_marks_what_it_wrote_as_its_own(db):
    from mcp_servers.job_tracker import server

    server.add_prep_plan(KEY[0], tasks=["A task"])

    assert db.get_prep_items(*KEY)[0]["source"] == "claude"


def test_mcp_reports_blank_entries_instead_of_dropping_them(db):
    from mcp_servers.job_tracker import server

    result = server.add_prep_plan(KEY[0], tasks=["Real task", "   "])

    assert result["added"]["tasks"] == 1
    assert result["refused_as_blank"] == ["   "]


def test_mcp_write_with_nothing_to_write_is_refused(db):
    from mcp_servers.job_tracker import server

    assert server.add_prep_plan(KEY[0])["success"] is False


def test_mcp_read_splits_tasks_from_questions(db):
    from mcp_servers.job_tracker import server

    server.add_prep_plan(KEY[0], tasks=["A task"], questions=["A question?"])
    plan = server.get_prep_plan(KEY[0])

    assert [t["body"] for t in plan["tasks"]] == ["A task"]
    assert [q["body"] for q in plan["questions"]] == ["A question?"]


def test_mcp_refuses_an_ambiguous_company(db):
    """
    Job-keyed, so unlike the company tools these must disambiguate: a prep plan
    for a robotics screen is not a prep plan for the fullstack one.
    """
    from mcp_servers.job_tracker import server

    db.upsert_job({
        "company": KEY[0], "date_added": "2026-09-21",
        "position_title": "Robotics Engineer", "link": "", "status": "Tracking",
    })

    with pytest.raises(ValueError, match="[Aa]mbiguous"):
        server.add_prep_plan(KEY[0], tasks=["A task"])
