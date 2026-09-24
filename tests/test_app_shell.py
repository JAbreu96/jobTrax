"""The /app shell's two build-dependent links.

src/static/dist/ is gitignored, so whether the bundle exists is a property of
the machine, not of the checkout. Both link decisions in app_shell.html are
therefore filesystem checks, and both have a failure mode that is invisible in
a browser:

  - a <script> tag pointing at a missing main.js renders a blank page whose
    only symptom is a 404 in devtools;
  - a <link> pointing at a main.css that Vite never emitted does the same, and
    Vite emits no stylesheet at all until something in the entry graph imports
    CSS -- which is not true yet at this rung.

These tests pin the four combinations against a fake dist/ so they hold
whether or not the machine running them has ever built the frontend.
"""

import pytest

from src import jobs_gui


@pytest.fixture
def client():
    jobs_gui.app.config["TESTING"] = True
    with jobs_gui.app.test_client() as c:
        yield c


@pytest.fixture
def fake_dist(tmp_path, monkeypatch):
    """Point the app's static folder at an empty tree we control.

    Rewriting app.static_folder rather than writing into the real
    src/static/dist/ keeps the suite from depending on -- or clobbering -- a
    build the developer may have sitting there.
    """
    static = tmp_path / "static"
    (static / "dist" / "assets").mkdir(parents=True)
    monkeypatch.setattr(jobs_gui.app, "static_folder", str(static))
    return static / "dist" / "assets"


def test_unbuilt_bundle_explains_itself_instead_of_serving_a_blank_page(client, fake_dist):
    html = client.get("/app").get_data(as_text=True)

    assert "dist/assets/main.js" not in html
    assert 'id="root"' not in html
    # The point of the branch: the page has to name the fix, since a bare
    # blank page sends you looking at Flask routing instead of the build.
    assert "build-frontend.sh" in html


def test_built_bundle_is_mounted(client, fake_dist):
    (fake_dist / "main.js").write_text("// built")

    html = client.get("/app").get_data(as_text=True)

    assert "dist/assets/main.js" in html
    assert 'id="root"' in html
    assert "build-frontend.sh" not in html


def test_stylesheet_is_not_linked_when_vite_emitted_none(client, fake_dist):
    (fake_dist / "main.js").write_text("// built")

    html = client.get("/app").get_data(as_text=True)

    # No component in the entry graph imports CSS yet, so main.css does not
    # exist. Linking it anyway would 404 on every page load.
    assert "dist/assets/main.css" not in html
    # The hand-maintained stylesheet is unconditional and shared with the
    # Jinja views -- it must survive the branch above either way.
    assert "job_views.css" in html


def test_stylesheet_is_linked_once_the_build_emits_one(client, fake_dist):
    (fake_dist / "main.js").write_text("// built")
    (fake_dist / "main.css").write_text("/* built */")

    html = client.get("/app").get_data(as_text=True)

    assert "dist/assets/main.css" in html


def test_bundle_presence_is_rechecked_per_request(client, fake_dist):
    """The dev loop is edit, rebuild, refresh -- with no Flask restart.

    A value cached at import would keep reporting the bundle missing after the
    very build the page just told the developer to run.
    """
    assert "build-frontend.sh" in client.get("/app").get_data(as_text=True)

    (fake_dist / "main.js").write_text("// built")

    assert 'id="root"' in client.get("/app").get_data(as_text=True)


def test_client_routed_paths_serve_the_same_shell(client, fake_dist):
    """A hard refresh on /app/<anything> must not 404 at Flask."""
    (fake_dist / "main.js").write_text("// built")

    assert client.get("/app/job/acme").status_code == 200
    assert 'id="root"' in client.get("/app/job/acme").get_data(as_text=True)
