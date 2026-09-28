"""
upsert_jobs is upsert_job batched, and nothing else.

The importer switched to it purely for speed, so every test here pins it to
upsert_job's behaviour: a regression that changes what lands in the table is a
data bug wearing a performance fix. The chunk boundary gets its own test because
it is the one place the batched path can differ from the loop -- a row dropped
or doubled at row 50 would pass every small fixture.
"""

import pytest

from src import jobs_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "jobs.db"))
    return jobs_db


def _item(n, **overrides):
    return {
        "company": f"Co {n}", "date_added": "2026-09-01", "position_title": "Engineer",
        "link": f"https://example.invalid/jobs/{n}", "status": "Applied",
        "location": "Texas", "notes": f"row {n}", **overrides,
    }


def _rows(db):
    return sorted(db.get_all_jobs(include_archived=True), key=lambda r: r["link"])


def test_writes_the_same_rows_as_a_loop_over_upsert_job(db, tmp_path, monkeypatch):
    items = [_item(n) for n in range(7)]
    assert db.upsert_jobs(items) == 7
    batched = _rows(db)

    monkeypatch.setattr(jobs_db, "DB_PATH", str(tmp_path / "loop.db"))
    for item in items:
        db.upsert_job(item)
    assert batched == _rows(db)


def test_spans_chunk_boundaries_without_dropping_or_doubling(db):
    n = jobs_db._UPSERT_CHUNK * 2 + 3
    assert db.upsert_jobs([_item(i) for i in range(n)]) == n
    rows = db.get_all_jobs(include_archived=True)
    assert len(rows) == n
    assert {r["company"] for r in rows} == {f"Co {i}" for i in range(n)}


def test_skips_rows_without_a_company(db):
    assert db.upsert_jobs([_item(1), _item(2, company=""), _item(3, company=None)]) == 1
    assert [r["company"] for r in db.get_all_jobs()] == ["Co 1"]


def test_empty_input_writes_nothing(db):
    assert db.upsert_jobs([]) == 0
    assert db.upsert_jobs([_item(1, company="")]) == 0


def test_replacing_a_row_keeps_it_archived(db):
    # upsert_job's COALESCE exists so re-importing an archived job does not
    # quietly resurrect it. The batched statement carries the same subquery.
    db.upsert_job(_item(1))
    conn = db._connect()
    try:
        conn.execute("UPDATE jobs SET archived = 1")
        conn.commit()
    finally:
        conn.close()

    db.upsert_jobs([_item(1, notes="changed")])
    rows = db.get_all_jobs(include_archived=True)
    assert len(rows) == 1
    assert rows[0]["notes"] == "changed"
    assert rows[0]["archived"] == 1


def test_a_repeated_key_resolves_to_the_later_item(db):
    db.upsert_jobs([_item(1, notes="first"), _item(1, notes="second")])
    rows = db.get_all_jobs()
    assert [r["notes"] for r in rows] == ["second"]
