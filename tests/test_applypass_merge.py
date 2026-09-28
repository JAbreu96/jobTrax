"""
Merging an ApplyPass export into rows that already exist.

Every test here locks down a way the old --include-dupes path lost data. It
routed matched rows through upsert_job, which is INSERT OR REPLACE on
(company, date_added, position_title, link): it keyed off the incoming record's
date_added -- ApplyPass's datetime_matched, which drifts when a job is
re-matched -- so it usually missed the row and inserted a duplicate beside it,
and when it did hit, it overwrote contacts, outreach dates and followup logs
with the empty strings the export builder hardcodes.
"""

import importlib.util
import os

import pytest

from src import jobs_db

_SPEC = importlib.util.spec_from_file_location(
    "paj", os.path.join(os.path.dirname(__file__), "..", "scripts", "parse_applied_jobs.py"))


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    return jobs_db


@pytest.fixture
def paj():
    module = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(module)
    return module


def _job(db, company="Acme", *, title="Engineer", link="https://x/1", date_added="2026-01-01",
         status="Applied", contacts="", notes="", outreach="", followup="",
         summary="", location="", applied="", archived=False):
    db.upsert_job({
        "company": company, "date_added": date_added, "position_title": title, "link": link,
        "job_summary": summary, "location": location, "contacts": contacts, "notes": notes,
        "outreach_date": outreach, "date_applied": applied, "status": status,
        "followup_log": followup,
    })
    if archived:
        conn = db._connect()
        try:
            conn.execute(
                "UPDATE jobs SET archived = 1 WHERE company = ? AND date_added = ? "
                "AND position_title = ? AND link = ?",
                (company, date_added, title, link))
            conn.commit()
        finally:
            conn.close()


def _rec(company="Acme", *, title="Engineer", link="https://x/1",
         matched="2026-06-15T10:00:00Z", location="Texas", description="A job."):
    """One export record, in the `_api_c2_` shape the source actually sends."""
    return {
        "_api_c2_match_id": f"{company}-{title}-{link}",
        "_api_c2_company_name": company,
        "_api_c2_job_title": title,
        "_api_c2_job_url": link,
        "_api_c2_job_description": description,
        "_api_c2_location_name": [location] if location else [],
        "_api_c2_datetime_matched": matched,
        "_api_c2_application_submitted_bool": True,
        "_api_c2_application_submitted_date": matched,
    }


def _classify(paj, records):
    return paj.classify_rows(paj.parse_export(records)["rows"])


def _row(db, **where):
    return [j for j in db.get_all_jobs(include_archived=True)
            if all(j.get(k) == v for k, v in where.items())]


def test_a_rematched_export_updates_the_row_instead_of_duplicating_it(db, paj):
    """
    The bug this whole change exists for. ApplyPass re-matches a job months
    later with a fresh datetime_matched; keying the write off that date made
    INSERT OR REPLACE miss the stored row and add a second one with the same
    link, so the tracker counted one job twice.
    """
    _job(db, date_added="2026-01-01", link="https://x/1", location="")
    groups = _classify(paj, [_rec(matched="2026-06-15T10:00:00Z", link="https://x/1")])

    assert len(groups["updates"]) == 1
    row, match, updates = groups["updates"][0]
    assert match["date_added"] == "2026-01-01"

    assert jobs_db.update_job_fields(
        match["company"], match["date_added"], updates,
        position_title=match["position_title"], link=match["link"])

    assert len(db.get_all_jobs(include_archived=True)) == 1


def test_curated_columns_survive_a_merge(db, paj):
    """
    contacts, outreach_date and followup_log are hand-entered or written by
    inbox-triage, and the export builder hardcodes all three to "". A merge that
    passes them through erases outreach history that exists nowhere else.
    """
    _job(db, contacts="rec@acme.com", outreach="2026-02-02",
         followup="2026-03-03 nudged", notes="spoke to hiring manager")
    groups = _classify(paj, [_rec()])

    _, _, updates = groups["updates"][0]
    for column in ("contacts", "outreach_date", "followup_log", "notes"):
        assert column not in updates


def test_an_advanced_status_is_not_knocked_back_to_applied(db, paj):
    """
    'Never downgrade a status' has been written policy in inbox-triage since it
    was created, enforced only by Claude reading the skill. The export always
    says Applied, so an unguarded merge would walk every interviewing row back.
    """
    _job(db, status="Phone Screen")
    _, match, updates = _classify(paj, [_rec()])["updates"][0]

    assert "status" not in updates
    assert match["status"] == "Phone Screen"


def test_a_rejected_row_is_left_alone(db, paj):
    """Rejected outranks Applied, so a re-match must not reopen a closed job."""
    _job(db, status="Rejected", location="")
    _, _, updates = _classify(paj, [_rec()])["updates"][0]

    assert "status" not in updates


def test_a_record_matching_an_archived_row_is_neither_inserted_nor_updated(db, paj):
    """
    find_job_by_link filtered archived rows while the company+title path did
    not, so a record matching an archived row looked new and was inserted next
    to the job that had deliberately been archived.
    """
    _job(db, archived=True)
    groups = _classify(paj, [_rec()])

    assert len(groups["archived"]) == 1
    assert groups["new"] == []
    assert groups["updates"] == []


def test_a_blank_link_row_is_matched_by_company_and_title_and_gets_its_link(db, paj):
    """
    Every export record carries a URL, so the linkless branch never fires for
    ApplyPass and a blank-link row is unreachable by link forever -- each import
    would insert a duplicate beside it. Filling the link makes it matchable.
    """
    _job(db, link="")
    groups = _classify(paj, [_rec(link="https://x/real")])

    assert len(groups["updates"]) == 1
    _, _, updates = groups["updates"][0]
    assert updates["link"] == "https://x/real"


def test_a_row_holding_a_different_link_is_not_treated_as_a_match(db, paj):
    """
    A company posting several requisitions under one title yields distinct URLs.
    Falling back to company+title for rows that already have a link would
    collapse those into one and silently drop the others.
    """
    _job(db, link="https://x/requisition-a")
    groups = _classify(paj, [_rec(link="https://x/requisition-b")])

    assert len(groups["new"]) == 1
    assert groups["updates"] == []


def test_two_blank_link_rows_sharing_a_title_are_refused_not_guessed(db, paj):
    """
    Same discipline find_job_for_email uses: a wrong silent write is worse than
    an unanswered question, so an ambiguous match is reported and skipped.
    """
    _job(db, link="", date_added="2026-01-01")
    _job(db, link="", date_added="2026-02-01")
    groups = _classify(paj, [_rec(link="https://x/real")])

    assert len(groups["ambiguous"]) == 1
    assert groups["new"] == []
    assert groups["updates"] == []


def test_a_refined_summary_is_kept_but_a_blank_one_is_filled(db, paj):
    """
    The GUI runs refine_summary over job_summary and the column is user
    editable, so raw export HTML must not overwrite it -- but an empty summary
    is worth filling.
    """
    _job(db, summary="Hand-refined: senior backend, Go, remote.", link="https://x/1")
    _, _, updates = _classify(paj, [_rec(link="https://x/1")])["updates"][0]
    assert "job_summary" not in updates

    _job(db, company="Globex", summary="", link="https://x/2")
    groups = _classify(paj, [_rec(company="Globex", link="https://x/2")])
    _, _, updates = next((u for u in groups["updates"] if u[1]["company"] == "Globex"), None)
    assert updates["job_summary"]


# --- incremental cutoff ------------------------------------------------------

AUTO_NOTE = "Imported from auto-apply export (auto-submitted application)."


def test_cutoff_is_the_newest_auto_applied_date_less_the_buffer(paj):
    jobs = [
        {"notes": AUTO_NOTE, "date_applied": "2026-09-20"},
        {"notes": AUTO_NOTE, "date_applied": "2026-09-28"},
        {"notes": AUTO_NOTE, "date_applied": "2026-09-01"},
    ]
    assert paj.incremental_cutoff(jobs) == "2026-09-26"
    assert paj.incremental_cutoff(jobs, buffer_days=0) == "2026-09-28"


def test_cutoff_ignores_jobs_applied_to_by_hand(paj):
    # A manual application yesterday says nothing about how far the export has
    # been imported; letting it set the cutoff would skip older export records.
    jobs = [
        {"notes": AUTO_NOTE, "date_applied": "2026-09-10"},
        {"notes": "Referred by a friend", "date_applied": "2026-09-27"},
    ]
    assert paj.incremental_cutoff(jobs) == "2026-09-08"


def test_cutoff_is_empty_before_the_first_import(paj):
    assert paj.incremental_cutoff([]) == ""
    assert paj.incremental_cutoff([{"notes": "manual", "date_applied": "2026-09-27"}]) == ""


def test_cutoff_skips_unparseable_dates(paj):
    jobs = [
        {"notes": AUTO_NOTE, "date_applied": ""},
        {"notes": AUTO_NOTE, "date_applied": "sometime"},
        {"notes": AUTO_NOTE, "date_applied": "2026-09-15T10:00:00"},
    ]
    assert paj.incremental_cutoff(jobs) == "2026-09-13"


def test_cutoff_flag_reads_the_tracker(db, paj, capsys, monkeypatch):
    _job(db, "Acme", notes=AUTO_NOTE, applied="2026-09-20")
    monkeypatch.setattr("sys.argv", ["parse_applied_jobs.py", "--cutoff"])
    assert paj.main() == 0
    assert capsys.readouterr().out.strip() == "2026-09-18"
