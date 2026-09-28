"""Keeps the board from growing a second copy of a shared rule.

jobs.html and kanban.html rendered the same job through the same field
builders, so for a long time they carried two copies of every rule those
builders need. The copies drifted -- `.company-editable` and
`.recruiter-select` had already diverged by the time they were pulled into
src/static/job_views.css.

jobs.html is gone: the table is React now, and its rules live in CSS modules
beside the components that use them. That leaves one Jinja view, so the test
comparing the two views against each other went with it -- there is nothing
left to compare. The other direction still bites, and is kept: a view
restating word for word a rule the shared sheet already has.
"""

import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).parent.parent / "src" / "templates"
SHARED = Path(__file__).parent.parent / "src" / "static" / "job_views.css"
VIEWS = ("kanban",)


def _close(text, start):
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise AssertionError("unbalanced braces")


def _rules(css, prefix=()):
    """{(at-rule chain, selector): sorted declarations} -- comments stripped."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = {}
    i = 0
    while True:
        brace = css.find("{", i)
        if brace < 0:
            return out
        selector = " ".join(css[i:brace].split())
        end = _close(css, brace)
        body = css[brace + 1:end]
        if selector.startswith("@media") or selector.startswith("@supports"):
            out.update(_rules(body, prefix + (selector,)))
        elif not selector.startswith("@"):
            decls = sorted(" ".join(d.split()) for d in body.split(";") if d.strip())
            out[prefix + (selector,)] = " ; ".join(decls)
        i = end + 1


def _style_block(name):
    html = (TEMPLATES / f"{name}.html").read_text()
    return html[html.index("<style>") + len("<style>"):html.index("</style>")]


@pytest.mark.parametrize("name", VIEWS)
def test_view_links_the_shared_stylesheet(name):
    assert "job_views.css" in (TEMPLATES / f"{name}.html").read_text()


def test_shared_rules_are_not_restated_by_a_view():
    """A view may override a shared rule, but not repeat it word for word."""
    shared = _rules(SHARED.read_text())
    for name in VIEWS:
        own = _rules(_style_block(name))
        repeated = sorted(k[-1] for k in own if k in shared and own[k] == shared[k])
        assert not repeated, f"{name}.html repeats shared rules verbatim: {repeated}"
