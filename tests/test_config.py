"""Precedence, tolerance of a missing profile, and a useful failure message.

The point of `src/config.py` is that a fork hits one clear error naming the file
to edit, instead of a 404 from gspread three calls later. That property is worth
a test.
"""

import os

import pytest

from src import config

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "profile.test.md")


@pytest.fixture
def reloaded(monkeypatch):
    """Reload config under whatever env the test has set, then restore."""

    def _reload():
        config.refresh()
        return config

    yield _reload
    monkeypatch.undo()
    config.refresh()


def test_reads_the_profile_front_matter(reloaded):
    cfg = reloaded()
    assert cfg.OWNER_NAME == "Test Owner"
    assert cfg.NOTIFY_EMAIL == "owner@example.test"
    assert cfg.LINKEDIN_URL == "linkedin.com/in/test-owner"


def test_owner_first_and_last_split_from_the_full_name(reloaded):
    cfg = reloaded()
    assert cfg.OWNER_FIRST_NAME == "Test"
    assert cfg.OWNER_LAST_NAME == "Owner"


def test_owner_emails_are_a_casefolded_list(reloaded):
    cfg = reloaded()
    assert cfg.OWNER_EMAILS == ("owner@example.test", "outreach@example.test")


def test_env_beats_the_profile(monkeypatch, reloaded):
    monkeypatch.setenv("AGENTS_NOTIFY_EMAIL", "override@example.test")
    assert reloaded().NOTIFY_EMAIL == "override@example.test"


def test_legacy_spreadsheet_env_name_still_works(monkeypatch, reloaded):
    monkeypatch.setenv("JOB_TRACKER_SPREADSHEET", "LEGACYID")
    assert reloaded().SPREADSHEET_ID == "LEGACYID"


def test_a_full_edit_url_is_reduced_to_the_id(monkeypatch, reloaded):
    """Pasting the browser URL is the obvious mistake; it must not be one."""
    monkeypatch.setenv(
        "AGENTS_SPREADSHEET_ID",
        "https://docs.google.com/spreadsheets/d/ABC123_x-y/edit#gid=0",
    )
    assert reloaded().SPREADSHEET_ID == "ABC123_x-y"


def test_a_missing_profile_yields_defaults_and_does_not_raise(monkeypatch, reloaded):
    """A fresh clone has no profile. Import must still succeed.

    `tests/test_sync_archived.py` and `tests/test_job_agent.py` import modules
    that import config at module scope, so an import-time raise would turn
    "not configured yet" into "the suite does not collect".
    """
    monkeypatch.setenv("AGENTS_PROFILE", "/nonexistent/profile.md")
    cfg = reloaded()
    assert cfg.OWNER_NAME == ""
    assert cfg.SPREADSHEET_ID == ""
    assert cfg.SHEET_WORKSHEET == "Sheet1"


def test_a_malformed_profile_is_skipped_rather_than_raised(monkeypatch, tmp_path, reloaded):
    bad = tmp_path / "profile.md"
    bad.write_text("---\nthis line has no colon\nowner_name: Still Read\n---\n")
    monkeypatch.setenv("AGENTS_PROFILE", str(bad))
    assert reloaded().OWNER_NAME == "Still Read"


def test_require_names_the_file_to_edit(monkeypatch, reloaded):
    monkeypatch.setenv("AGENTS_PROFILE", "/nonexistent/profile.md")
    cfg = reloaded()
    with pytest.raises(config.ConfigError) as excinfo:
        cfg.require("SPREADSHEET_ID")
    message = str(excinfo.value)
    assert "SPREADSHEET_ID" in message
    assert "profile.example.md" in message


def test_require_returns_a_configured_value(reloaded):
    assert reloaded().require("NOTIFY_EMAIL") == "owner@example.test"
