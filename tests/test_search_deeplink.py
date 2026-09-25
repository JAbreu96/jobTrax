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
    """
    "showSearchBanner" alone is satisfied by the function's own declaration
    ("function showSearchBanner() {") with nobody ever calling it. The call
    site ends "();" immediately, which the declaration does not -- pinning
    that a call exists, not just that the name is spelled somewhere.
    """
    assert "showSearchBanner();" in html


def _listener_body(html):
    """The body of the #search input listener, isolated from the rest of the
    inline script -- a page-wide substring check for one of its statements
    would also be satisfied by that same text sitting somewhere else on the
    page entirely."""
    start = html.index("getElementById('search').addEventListener('input'")
    return html[start:html.index("});", start)]


def test_typing_also_re_renders_the_table(html):
    """
    The listener is three statements now, not the original one-liner that
    only updated the URL. Drop the trailing renderFromTop() and the address
    bar keeps changing while the table quietly stops filtering -- and every
    other assertion in this file would keep passing.
    """
    assert "renderFromTop();" in _listener_body(html)


def test_typing_keeps_the_banner_honest(html):
    """
    showSearchBanner() computed once at load and never again would keep
    naming the query the page arrived with after the box was retyped,
    contradicting the table directly beneath it. The listener has to call it
    again on every keystroke, not just re-render the rows.
    """
    assert "showSearchBanner();" in _listener_body(html)
