"""
The job list's half of the ?q= contract.

Insights links here with ?q=<company>; the box is filled from that param, and
refilled into the URL as it is typed so the address bar is always copyable.

These assert on the template *text*, not on behaviour. jobs.html's script is
inline and nothing in this repo executes it -- which is why the logic itself
lives in job_fields.js, where tests/js/job_fields_checks.js can reach it. What
is guarded here is that the glue exists and is pointed at the right things.
"""

from pathlib import Path

import pytest

JOBS_HTML = Path(__file__).parent.parent / "src" / "templates" / "jobs.html"


@pytest.fixture(scope="module")
def html():
    return JOBS_HTML.read_text()


def test_the_search_box_is_filled_from_the_url(html):
    assert "JobFields.searchFromQuery(window.location.search)" in html


def test_typing_rewrites_the_url(html):
    assert "JobFields.queryWithSearch(" in html
    assert "history.replaceState" in html


def test_the_url_is_replaced_not_pushed(html):
    """A 12-character query would otherwise bury Back under 12 entries."""
    assert "history.pushState" not in html


def test_replacing_the_url_keeps_the_path(html):
    """replaceState with a bare query string would drop /."""
    assert "location.pathname + JobFields.queryWithSearch" in html


def test_archived_inclusion_comes_from_the_shared_helper(html):
    """
    The old inline `.has('stage')` did not know about ?include_archived=1, so a
    deeplink to an archived company answered 'no matches'.
    """
    assert "JobFields.wantsArchived(window.location.search)" in html
    assert "new URLSearchParams(window.location.search).has('stage')" not in html


def test_arriving_with_a_search_says_so(html):
    assert "showSearchBanner" in html
