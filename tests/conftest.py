"""
Test-suite guardrails.

`src/job_agent.py` calls `load_dotenv()` at import time, so importing it — which
`test_job_agent.py` does — pushes every key in `.env` into `os.environ` for the
rest of the session. Once `TURSO_DATABASE_URL` lived there, `_use_libsql()`
returned True and every test's `_connect()` ignored its monkeypatched `DB_PATH`
and went to the production cloud database instead.

That is not hypothetical: it wrote 138 job rows, 78 interviews and 4 recruiters
into the live Turso database before the run was killed.

Tests must never touch a remote database. This fixture is autouse and
session-scoped so it applies before any test module is imported.
"""

import os

import pytest

_REMOTE_KEYS = ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN")


@pytest.fixture(autouse=True, scope="session")
def _never_touch_the_cloud_database():
    """Strips remote-database config for the whole session, and puts it back after."""
    saved = {k: os.environ.pop(k, None) for k in _REMOTE_KEYS}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


@pytest.fixture(autouse=True, scope="session")
def _pin_test_profile(_never_touch_the_cloud_database):
    """Point `src.config` at a fixture profile for the whole session.

    Otherwise the suite asserts against whatever `config/profile.md` happens to
    hold on the machine running it: green on the author's laptop, red on a fresh
    fork that has no profile at all. Same class of bug the config extraction
    exists to remove, so it does not get to live in the tests either.

    Ordered after the cloud-database fixture so `config.refresh()` cannot be the
    thing that puts TURSO_* back.
    """
    from src import config

    saved = os.environ.get("AGENTS_PROFILE")
    os.environ["AGENTS_PROFILE"] = os.path.join(
        os.path.dirname(__file__), "fixtures", "profile.test.md"
    )
    config.refresh()
    yield
    if saved is None:
        os.environ.pop("AGENTS_PROFILE", None)
    else:
        os.environ["AGENTS_PROFILE"] = saved
    config.refresh()


@pytest.fixture(autouse=True)
def _assert_still_local():
    """
    Belt and braces: something importing dotenv mid-run could re-introduce the
    variable, so re-check before every single test rather than once per session.
    """
    for k in _REMOTE_KEYS:
        os.environ.pop(k, None)
    yield
