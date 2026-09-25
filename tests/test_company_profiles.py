"""
The company research notebook: storage, partial writes, and renames.

Two behaviours here are load-bearing and neither is obvious from the schema.

**Writes are partial.** The research skill fills `about` and `product` in one
pass and `recent_news` in another, with hand corrections to `why_me` in
between. Every other update_* helper in jobs_db overwrites its whole column
(update_notes, update_summary, update_contacts), which is survivable when a
human is the only writer and is not survivable here.

**The profile is keyed on the employer, not the job.** That is the whole reason
it exists as a table: 174 companies in this tracker hold more than one role and
the research is true of all of them. It also means a company rename has to be
handled explicitly, since the composite job key enforces nothing.
"""

import pytest

from src import jobs_db, jobs_gui


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    jobs_db._reset_schema_cache()
    return jobs_db


@pytest.fixture
def client(db):
    db.upsert_job({
        "company": "Physical Intelligence", "position_title": "Fullstack SWE",
        "link": "", "date_added": "2026-09-20", "status": "Phone Screen",
    })
    jobs_gui.app.config["TESTING"] = True
    with jobs_gui.app.test_client() as c:
        yield c


# --- the key ----------------------------------------------------------------

def test_key_ignores_case_and_surrounding_space(db):
    assert db.company_key("  Physical Intelligence ") == db.company_key(
        "physical intelligence")


def test_key_collapses_internal_whitespace(db):
    assert db.company_key("Physical  Intelligence") == "physical intelligence"


def test_key_keeps_non_ascii_names_distinct(db):
    """
    Not _slugify(). That maps non-alphanumerics to hyphens and drops anything
    outside ASCII, which would file two different employers under one key --
    and merged research notes cannot be unpicked afterwards.
    """
    assert db.company_key("Adé") != db.company_key("Ad")


def test_blank_company_has_no_profile(db):
    assert db.get_company_profile("   ") is None


# --- writing ----------------------------------------------------------------

def test_unresearched_company_reads_as_none(db):
    assert db.get_company_profile("Physical Intelligence") is None


def test_write_then_read_round_trips(db):
    db.set_company_profile("Physical Intelligence", about="An embodied AI lab.")

    assert db.get_company_profile("Physical Intelligence")["about"] == (
        "An embodied AI lab.")


def test_second_write_leaves_the_first_section_alone(db):
    """The case the whole partial-write design exists for."""
    db.set_company_profile("Physical Intelligence", about="An embodied AI lab.")
    db.set_company_profile("Physical Intelligence", funding="Series B, $400M.")

    profile = db.get_company_profile("Physical Intelligence")
    assert profile["about"] == "An embodied AI lab."
    assert profile["funding"] == "Series B, $400M."


def test_rewriting_one_section_replaces_only_that_section(db):
    db.set_company_profile("Physical Intelligence", about="Old.", team="Jenny Morin.")
    db.set_company_profile("Physical Intelligence", about="New.")

    profile = db.get_company_profile("Physical Intelligence")
    assert profile["about"] == "New."
    assert profile["team"] == "Jenny Morin."


def test_a_differently_cased_name_writes_the_same_profile(db):
    db.set_company_profile("Physical Intelligence", about="First.")
    db.set_company_profile("PHYSICAL INTELLIGENCE", product="pi0.7.")

    profile = db.get_company_profile("physical intelligence")
    assert profile["about"] == "First."
    assert profile["product"] == "pi0.7."


def test_display_name_keeps_the_first_real_spelling(db):
    db.set_company_profile("Physical Intelligence", about="x")
    db.set_company_profile("PHYSICAL INTELLIGENCE", product="y")

    assert db.get_company_profile("physical intelligence")["display_name"] == (
        "Physical Intelligence")


def test_unknown_section_is_rejected_not_ignored(db):
    """A typo in a tool call must fail loudly rather than write nothing."""
    with pytest.raises(ValueError, match="headcount"):
        db.set_company_profile("Physical Intelligence", headcount="40")


def test_research_write_stamps_researched_at(db):
    db.set_company_profile("Physical Intelligence", about="x")

    assert db.get_company_profile("Physical Intelligence")["researched_at"]


def test_website_correction_does_not_refresh_researched_at(db):
    """
    Otherwise fixing a URL makes month-old notes look current, and the research
    skill uses this date to decide what is stale.
    """
    db.set_company_profile("Physical Intelligence", about="x")
    conn = db._connect()
    conn.execute("UPDATE companies SET researched_at = '2026-01-01'")
    conn.commit()
    conn.close()

    db.set_company_profile("Physical Intelligence",
                           website="https://physicalintelligence.company")

    assert db.get_company_profile("Physical Intelligence")["researched_at"] == (
        "2026-01-01")


# --- renaming ---------------------------------------------------------------

def test_rename_moves_the_profile(db):
    db.set_company_profile("Physical Intelligence", about="An embodied AI lab.")

    assert db.rename_company_profile("Physical Intelligence", "Physical Intelligence Inc")
    assert db.get_company_profile("Physical Intelligence Inc")["about"] == (
        "An embodied AI lab.")
    assert db.get_company_profile("Physical Intelligence") is None


def test_rename_refuses_to_merge_onto_an_existing_profile(db):
    """
    Two employers' research merged into one row cannot be separated again.
    Leaving the old row where it is loses nothing and stays fixable by hand.
    """
    db.set_company_profile("Fin", about="Fin's research.")
    db.set_company_profile("Fin Inc", about="A different company entirely.")

    assert db.rename_company_profile("Fin", "Fin Inc") is False
    assert db.get_company_profile("Fin")["about"] == "Fin's research."
    assert db.get_company_profile("Fin Inc")["about"] == "A different company entirely."


def test_rename_to_the_same_key_is_a_no_op(db):
    db.set_company_profile("Fin", about="x")

    assert db.rename_company_profile("Fin", "  fin  ") is False
    assert db.get_company_profile("Fin")["about"] == "x"


# --- the GUI ----------------------------------------------------------------

def test_get_profile_answers_null_for_an_unresearched_company(client):
    res = client.get("/api/companies/profile?company=Physical Intelligence")

    assert res.status_code == 200
    assert res.get_json()["profile"] is None


def test_get_profile_requires_a_company(client):
    assert client.get("/api/companies/profile").status_code == 400


def test_update_writes_one_section(client, db):
    res = client.post("/api/companies/profile/update", json={
        "company": "Physical Intelligence", "field": "about", "value": "An AI lab.",
    })

    assert res.status_code == 200
    assert res.get_json()["profile"]["about"] == "An AI lab."


def test_update_rejects_a_field_that_is_not_a_section(client):
    """
    Mirrors the EDITABLE_COLUMNS gate on /api/jobs/update: the column name
    reaches an f-string in the UPDATE, so the allowlist is the thing stopping
    an arbitrary column -- or worse -- being written.
    """
    res = client.post("/api/companies/profile/update", json={
        "company": "Physical Intelligence", "field": "company_key", "value": "x",
    })

    assert res.status_code == 400


def test_update_rejects_a_blank_company(client):
    res = client.post("/api/companies/profile/update", json={
        "company": "", "field": "about", "value": "x",
    })

    assert res.status_code == 400


def test_renaming_the_last_job_carries_the_profile(client, db):
    db.set_company_profile("Physical Intelligence", about="An embodied AI lab.")

    res = client.post("/api/jobs/update", json={
        "company": "Physical Intelligence", "date_added": "2026-09-20",
        "position_title": "Fullstack SWE", "link": "",
        "field": "company", "value": "Physical Intelligence Inc",
    })

    assert res.get_json()["company_profile_moved"] is True
    assert db.get_company_profile("Physical Intelligence Inc")["about"] == (
        "An embodied AI lab.")


def test_renaming_one_of_two_roles_leaves_the_profile_put(client, db):
    """
    Renaming a job is usually a correction to that posting, not a rename of the
    employer. Moving the research out from under the sibling role would be
    wrong, so the profile only follows when nothing is left behind.
    """
    db.upsert_job({
        "company": "Physical Intelligence", "position_title": "Robotics Engineer",
        "link": "", "date_added": "2026-09-21", "status": "Tracking",
    })
    db.set_company_profile("Physical Intelligence", about="An embodied AI lab.")

    res = client.post("/api/jobs/update", json={
        "company": "Physical Intelligence", "date_added": "2026-09-20",
        "position_title": "Fullstack SWE", "link": "",
        "field": "company", "value": "Physical Intelligence Inc",
    })

    assert res.get_json()["company_profile_moved"] is False
    assert db.get_company_profile("Physical Intelligence")["about"] == (
        "An embodied AI lab.")
    assert db.get_company_profile("Physical Intelligence Inc") is None


def test_rename_still_succeeds_when_there_is_no_profile_to_carry(client, db):
    res = client.post("/api/jobs/update", json={
        "company": "Physical Intelligence", "date_added": "2026-09-20",
        "position_title": "Fullstack SWE", "link": "",
        "field": "company", "value": "Physical Intelligence Inc",
    })

    assert res.status_code == 200
    assert res.get_json()["company_profile_moved"] is False


# --- the MCP tools ----------------------------------------------------------
# Thin wrappers, but two of their contracts are theirs alone and are the kind a
# model calling them will lean on.

def test_mcp_write_reports_only_the_sections_it_wrote(db):
    from mcp_servers.job_tracker import server

    result = server.set_company_profile("Physical Intelligence",
                                        about="An embodied AI lab.")

    assert result["success"] is True
    assert result["written"] == ["about"]


def test_mcp_omitted_section_is_left_alone_not_cleared(db):
    """
    Every parameter defaults to "" because MCP tools take flat arguments, so
    "not researched" and "researched as empty" arrive identically. Treating the
    blank as a clear would let a model that filled one section wipe the other
    five it never mentioned.
    """
    from mcp_servers.job_tracker import server

    server.set_company_profile("Physical Intelligence", about="An embodied AI lab.")
    server.set_company_profile("Physical Intelligence", funding="Series B.")

    assert db.get_company_profile("Physical Intelligence")["about"] == (
        "An embodied AI lab.")


def test_mcp_write_with_nothing_to_write_is_refused(db):
    from mcp_servers.job_tracker import server

    assert server.set_company_profile("Physical Intelligence")["success"] is False


def test_mcp_read_of_an_unresearched_company_says_so(db):
    from mcp_servers.job_tracker import server

    result = server.get_company_profile("Nowhere Inc")

    assert result["profile"] is None
    assert "No research stored" in result["note"]
