"""
Local web GUI for browsing and editing the job tracker.

Reads whichever database jobs_db is configured for -- Turso when
TURSO_DATABASE_URL is set, data/jobs.db otherwise.

Run:
    python src/jobs_gui.py

Then open http://127.0.0.1:5151 in your browser.
"""

import base64
import binascii
import gzip
import io
import json
import os
import sys
from datetime import date
from urllib.parse import urlparse

from flask import Flask, Response, g, jsonify, redirect, render_template, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.job_agent import JobTrackerAgent  # noqa: E402
from src.jobs_db import (  # noqa: E402
    INTERVIEW_TYPES,
    LIST_COLUMNS,
    APPLIED_STATUSES,
    STATUS_ORDER,
    UPCOMING_WINDOW_DAYS,
    _connect,
    _WRITE_EXC,
    shared_connection as _shared_connection,
    GHOSTED_AFTER_DAYS,
    RATE_MIN_DENOMINATOR,
    add_interview,
    COMPANY_SECTIONS,
    PREP_KINDS,
    get_prep_items,
    add_prep_item,
    set_prep_item_done,
    update_prep_item,
    delete_prep_item,
    carry_prep_items,
    get_company_profile,
    set_company_profile,
    rename_company_profile,
    delete_interview,
    delete_job_by_key,
    export_csv,
    find_job_by_link,
    funnel_stats,
    get_interviews,
    delete_recruiter,
    get_job_recruiters,
    get_recruiter_jobs,
    get_recruiters,
    job_recruiter_links,
    set_job_recruiter,
    update_recruiter,
    upsert_recruiter,
    job_silence_stats,
    upcoming_interviews,
    jobs_missing_interview_rows,
    duplicate_interview_rounds,
    recruiter_coverage,
    interview_stats,
    upsert_job,
)

EDITABLE_COLUMNS = {
    "company", "status", "notes", "contacts", "job_summary",
    "outreach_date", "date_applied", "followup_log",
}
# The order lives in jobs_db with the rest of the schema vocabulary; the name
# stays bound here because the templates use it.
STATUS_VALUES = STATUS_ORDER

app = Flask(__name__)
# Flask sorts JSON keys by default. On /api/jobs that is 1014 dicts of 11 keys
# reordered for nobody's benefit.
app.json.sort_keys = False


@app.before_request
def _open_scope():
    """
    Every request runs inside one shared_connection().

    It has to be here rather than inside get_db(), because the handlers that
    cost the most never call get_db() at all: insights_view goes straight to the
    jobs_db helpers, and each of those opened its own connection -- seven helpers,
    eleven connections, ~2.1s of the 4.6s that page took.

    Wrapping unconditionally is free because the scope connects lazily, so the
    routes that only render a template still pay nothing.
    """
    g.db_scope = _shared_connection(create=True)
    g.db = g.db_scope.__enter__()


def get_db():
    """
    One connection policy for the whole app: _connect() picks the driver from
    TURSO_DATABASE_URL and builds the schema itself.

    This used to open data/jobs.db directly while every jobs_db helper went to
    Turso, so a single page read two different databases -- the local file was
    153 jobs behind, and the table quietly showed the smaller set.
    """
    if "db" not in g:                      # outside a request (tests, shell)
        g.db_scope = _shared_connection(create=True)
        g.db = g.db_scope.__enter__()
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    scope = g.pop("db_scope", None)
    g.pop("db", None)
    if scope is not None:
        scope.__exit__(None, None, None)   # closes the one real connection


# Level 1, not 9: /api/jobs shrinks 980KB -> 290KB either way, and the cheapest
# setting spends 14ms doing it. The database work behind that response is ~250ms,
# so the response itself was the larger half of the wait.
_GZIP_MIN_BYTES = 8192


@app.after_request
def _compress(response):
    if (response.direct_passthrough
            or response.status_code < 200 or response.status_code >= 300
            or "gzip" not in request.headers.get("Accept-Encoding", "").lower()
            or "Content-Encoding" in response.headers
            or response.content_length is not None
            and response.content_length < _GZIP_MIN_BYTES):
        return response
    data = response.get_data()
    if len(data) < _GZIP_MIN_BYTES:
        return response
    response.set_data(gzip.compress(data, 1))
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = response.content_length
    response.headers.add("Vary", "Accept-Encoding")
    return response


@app.route("/")
def index():
    return render_template("jobs.html", status_values=STATUS_VALUES,
                           interview_types=INTERVIEW_TYPES)


@app.route("/kanban")
def kanban():
    # interview_types is new here: the board's modal can log rounds now, which
    # the table could always do and it could not.
    return render_template("kanban.html", status_values=STATUS_VALUES,
                           interview_types=INTERVIEW_TYPES)


def _bundle_asset_exists(name: str) -> bool:
    """Whether `npm run build` has emitted src/static/dist/assets/<name>.

    src/static/dist/ is gitignored, so on a fresh clone it is simply absent
    and /app would otherwise serve a <script> tag pointing at a 404 -- a blank
    page with the reason only visible in devtools. Checked per request rather
    than cached at import: the dev loop is "edit, rebuild, refresh", and a
    cached miss would survive the rebuild and keep claiming the bundle is
    missing until Flask restarted.
    """
    return os.path.isfile(os.path.join(app.static_folder, "dist", "assets", name))


# Staging mount for the React rewrite (frontend/). Phase 0 only -- it does not
# replace "/", "/kanban" or "/insights" yet, which still serve the Jinja
# templates above. Both routes are needed so a hard refresh on a client-routed
# path under /app (e.g. /app/kanban) doesn't 404 at Flask. This whole mount,
# and the matching `basename="/app"` on the React router, is temporary and is
# expected to be removed route-by-route in Phases 4, 5 and 7 as each view is
# cut over for real; once all three are cut over, basename goes away entirely.
@app.route("/app")
@app.route("/app/<path:_rest>")
def app_shell(_rest=None):
    return render_template(
        "app_shell.html",
        bundle_built=_bundle_asset_exists("main.js"),
        # Vite emits a stylesheet only once something in the entry graph
        # imports CSS. Phase 0's App.tsx imported none, and the field
        # components landed on this rung are not mounted yet, so main.css
        # genuinely does not exist here -- linking it unconditionally would
        # serve a 404 on every load. Asking the filesystem rather than
        # hard-coding either answer means the link appears on its own the
        # moment a later phase renders a component that imports a module, so
        # nobody has to remember to come back and add it.
        bundle_css=_bundle_asset_exists("main.css"),
    )


# The list is ordered by date_added DESC, and date_added is not unique, so a
# cursor carrying only the date cannot say where inside a tied run a page
# stopped. It carries the whole primary key -- the tie-break the index
# (idx_jobs_list) is built on -- and the comparison below walks it in the same
# order. Opaque on the wire so the client never builds one by hand.
_CURSOR_FIELDS = ("d", "c", "p", "l")   # date_added, company, position_title, link

# Above the client's PREFETCH_PAGE (2000) so its post-first-page request isn't
# silently truncated back down to multiple round trips -- see jobs.html for the
# Turso measurements that picked 2000. Still a real ceiling, not removed: a
# client cannot ask for an unbounded page.
_MAX_PAGE = 2000


def _encode_cursor(row) -> str:
    payload = {"d": row["date_added"], "c": row["company"],
               "p": row["position_title"], "l": row["link"]}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> list[str]:
    """Values in comparison order. Raises ValueError on anything malformed."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("undecodable cursor") from exc
    if not isinstance(payload, dict) or any(f not in payload for f in _CURSOR_FIELDS):
        raise ValueError("cursor is missing key fields")
    values = [payload[f] for f in _CURSOR_FIELDS]
    if any(not isinstance(v, str) for v in values):
        raise ValueError("cursor fields must be strings")
    return values


def _with_recruiter(row: dict, linked=None) -> dict:
    """Attach the four recruiter_* fields a job row carries on the wire.

    None of them is a column on `jobs` -- the link lives in recruiter_jobs --
    so every endpoint handing out a job row has to add them, and a caller that
    forgets returns something that matches the declared shape everywhere except
    the recruiter picker, which then quietly renders as unlinked.

    `linked` is supplied by the list route, which scans recruiter_jobs once for
    the whole page instead of once per row: that runs for every job rendered,
    against a thousand jobs. A single-row caller omits it and pays for one scan.
    """
    if linked is None:
        linked = get_job_recruiters()
    hit = linked.get((row["company"], row["date_added"],
                      row.get("position_title") or "", row.get("link") or ""))
    row["recruiter_id"] = hit["recruiter_id"] if hit else None
    row["recruiter_name"] = hit["recruiter_name"] if hit else None
    row["recruiter_agency"] = hit["recruiter_agency"] if hit else None
    # Tells the row whether the link came from a mail, which is what makes it
    # read-only until the user overrides it.
    row["recruiter_from_triage"] = bool(hit and (hit.get("message_id") or "").strip())
    return row


@app.route("/api/jobs")
def api_jobs():
    """
    Archived rows are hidden by default — this is the working table.

    ?include_archived=1 is what the Insights drill-through uses: the funnel counts
    archived rows on purpose (a finished outcome is its most useful input), so a
    click from a funnel stage has to land on the same population it just counted,
    or the number changes when you follow it.

    ?limit (with ?cursor) pages the list, and is opt-in for exactly one reason:
    kanban.html and the Insights drill-through also read this route and both need
    the whole table in one answer. Without a limit the response stays the bare
    array it has always been; with one it becomes {jobs, next_cursor}. Nothing
    that does not ask for paging can be broken by it.
    """
    include_archived = request.args.get("include_archived") in ("1", "true", "yes")
    limit, cursor = request.args.get("limit"), request.args.get("cursor")

    if limit is not None:
        try:
            limit = int(limit)
        except ValueError:
            return jsonify({"error": "limit must be an integer"}), 400
        if limit < 1:
            return jsonify({"error": "limit must be at least 1"}), 400
        limit = min(limit, _MAX_PAGE)
    if cursor is not None:
        try:
            cursor_values = _decode_cursor(cursor)
        except ValueError as exc:
            # A 400 rather than a silent restart from row one: the client pages in
            # a loop, and a cursor that quietly resets makes it re-read the top of
            # the list forever instead of failing where it broke.
            return jsonify({"error": str(exc)}), 400

    db = get_db()
    # Named columns, not SELECT *: dropping job_summary here takes the payload
    # from 2.1MB to 0.68MB and the query from 230ms to 152ms. Trimming in Python
    # instead would still drag the column across the wire from Turso.
    query = f"SELECT {', '.join(LIST_COLUMNS)} FROM jobs"
    where, params = [], []
    if not include_archived:
        where.append("archived = 0")
    if cursor is not None:
        # Written out rather than as a row-value comparison: date_added runs DESC
        # and the tie-break columns ASC, and SQLite's (a, b) < (c, d) cannot mix
        # directions. Every column here is NOT NULL DEFAULT '', so there is no
        # NULL case to fall through.
        where.append(
            "(date_added < ?"
            " OR (date_added = ? AND company > ?)"
            " OR (date_added = ? AND company = ? AND position_title > ?)"
            " OR (date_added = ? AND company = ? AND position_title = ?"
            "     AND link > ?))"
        )
        d, c, p, l = cursor_values
        params += [d, d, c, d, c, p, d, c, p, l]
    if where:
        query += " WHERE " + " AND ".join(where)
    # The tie-break is what makes paging total, and it matches idx_jobs_list, so
    # the extra columns cost nothing -- the index is already in this order.
    query += " ORDER BY date_added DESC, company, position_title, link"
    if limit is not None:
        # One extra row, never returned: it is how the last page is recognised
        # without a second COUNT query.
        query += " LIMIT ?"
        params.append(limit + 1)
    rows = db.execute(query, params).fetchall()

    has_more = limit is not None and len(rows) > limit
    if has_more:
        rows = rows[:limit]

    # One scan of recruiter_jobs for the whole list, not a lookup per row: this
    # runs for every job rendered, and the table is tens of rows against a
    # thousand jobs.
    linked = get_job_recruiters()
    out = [_with_recruiter(dict(r), linked) for r in rows]

    if limit is None:
        return jsonify(out)
    return jsonify({"jobs": out,
                    "next_cursor": _encode_cursor(rows[-1]) if has_more else None})


@app.route("/api/jobs/detail")
def api_job_detail():
    """
    Everything the list deliberately left out, for one row, on expand.

    job_summary and interview rounds are cached differently by the client and
    that is the point: job_summary has exactly one writer -- the edit box in the
    panel -- so once fetched it can be held for the life of the page, and
    ?summary=0 says the client already has it. Rounds have a second writer,
    inbox-triage on a daily cron, so they are re-read on every expand and never
    cached.
    """
    key = {
        "company": (request.args.get("company") or "").strip(),
        "date_added": (request.args.get("date_added") or "").strip(),
        "position_title": (request.args.get("position_title") or "").strip(),
        "link": (request.args.get("link") or "").strip(),
    }
    if not key["company"]:
        return jsonify({"error": "company is required"}), 400

    want_summary = request.args.get("summary") not in ("0", "false", "no")
    # ?job=1 adds the row itself. The table never needs it -- it is expanding a
    # row it already holds -- but the job view at /app is reached by a full page
    # load out of that table, so it starts with an empty cache and no way to ask
    # for one row. Opt-in rather than always-on, so the table's expand does not
    # start carrying a payload it would throw away.
    want_job = request.args.get("job") in ("1", "true", "yes")
    want_prep = request.args.get("prep") in ("1", "true", "yes")
    want_company = request.args.get("company_profile") in ("1", "true", "yes")

    payload = {"interviews": get_interviews(**key)}

    # One SELECT for both, where there used to be two. They read the same row by
    # the same key, and against Turso each statement is a network round trip --
    # measured at 334ms and 382ms for the two halves of one row, where the row
    # itself costs nothing to find. Every query on this endpoint is latency, so
    # the only lever that moves is how many there are.
    columns = []
    if want_summary:
        columns.append("job_summary")
    if want_job:
        columns.extend(LIST_COLUMNS)
    if columns:
        row = get_db().execute(
            f"SELECT {', '.join(columns)} FROM jobs WHERE company = ? "
            "AND date_added = ? AND position_title = ? AND link = ?",
            (key["company"], key["date_added"], key["position_title"], key["link"]),
        ).fetchone()
        if want_summary:
            payload["job_summary"] = ((row["job_summary"] if row else "") or "")
        if want_job:
            payload["job"] = _with_recruiter(
                {c: row[c] for c in LIST_COLUMNS}) if row else None

    # Same opt-in shape, and for the same reason: the table's expand has no
    # prep checklist to show and should not pay for one.
    if want_prep:
        payload["prep_items"] = get_prep_items(**key)

    # The company profile rides along rather than costing its own request. It is
    # keyed on the employer, which this endpoint already has, and the job view
    # needs both on every open -- a second HTTP round trip to fetch one row by a
    # key we are holding was 471ms of the ~5.2s that open cost.
    if want_company:
        payload["company_profile"] = get_company_profile(key["company"])

    return jsonify(payload)


@app.route("/api/jobs/export.csv")
def api_export_csv():
    db = get_db()
    rows = db.execute("SELECT * FROM jobs WHERE archived = 0 ORDER BY date_added DESC").fetchall()
    buf = io.StringIO()
    export_csv([dict(r) for r in rows], buf)
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=jobs_export.csv"},
    )


@app.route("/api/jobs/fetch_url", methods=["POST"])
def api_fetch_url():
    payload = request.get_json(force=True)
    url = (payload.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400

    host = urlparse(url).netloc.lower()
    if any(d in host for d in ("linkedin.com", "indeed.com", "glassdoor.com")):
        return jsonify({
            "error": "LinkedIn/Indeed/Glassdoor block automated fetching — paste the details manually."
        }), 400

    try:
        board_info = JobTrackerAgent.detect_job_board(url)
        if board_info:
            board_type, api_url = board_info
            if board_type == "greenhouse":
                record = JobTrackerAgent.fetch_greenhouse_job(api_url, url)
            else:
                record = JobTrackerAgent.fetch_lever_job(api_url, url)
            if record.summary:
                record.summary = JobTrackerAgent.refine_summary(record.summary)
        else:
            html = JobTrackerAgent.fetch_page(url)
            record = JobTrackerAgent.parse_job_page(html, url)

        if record.company and record.company != "(unknown company)":
            record.notes = JobTrackerAgent.research_company(record.company)
    except Exception as exc:
        return jsonify({"error": f"Failed to fetch job posting: {exc}"}), 502

    return jsonify({
        "company": record.company if record.company != "(unknown company)" else "",
        "position_title": record.title if record.title != "(unknown title)" else "",
        "location": record.location if record.location != "(unknown location)" else "",
        "link": url,
        "job_summary": record.summary,
        "notes": record.notes,
    })


@app.route("/api/jobs/add", methods=["POST"])
def api_add_job():
    payload = request.get_json(force=True)
    company = (payload.get("company") or "").strip()
    title = (payload.get("position_title") or "").strip()
    link = (payload.get("link") or "").strip()
    location = (payload.get("location") or "").strip()
    summary = (payload.get("job_summary") or "").strip()
    contacts = (payload.get("contacts") or "").strip()
    notes = (payload.get("notes") or "").strip()
    status = (payload.get("status") or "Tracking").strip()
    date_added = (payload.get("date_added") or "").strip()

    if not company or not title:
        return jsonify({"error": "company and position_title are required"}), 400
    if status and status not in STATUS_VALUES:
        return jsonify({"error": f"status '{status}' is not a recognized value"}), 400
    if link:
        existing = find_job_by_link(link)
        if existing:
            return jsonify({
                "error": f"This URL is already tracked ({existing['company']}, added {existing['date_added']})."
            }), 409

    job = {
        "company": company,
        "position_title": title,
        "job_summary": summary,
        "location": location,
        "link": link,
        "date_added": date_added or date.today().isoformat(),
        "contacts": contacts,
        "notes": notes,
        "outreach_date": "",
        "date_applied": date.today().isoformat() if (status or "Tracking") == "Applied" else "",
        "status": status or "Tracking",
        "followup_log": "",
    }
    upsert_job(job)
    return jsonify(job)


# Tables that carry a copy of the jobs primary key instead of a foreign key to
# it -- see _ensure_interviews_schema's docstring in jobs_db for why the key is
# copied rather than referenced. The tradeoff is that nothing at the database
# level keeps them in step, so renaming a company silently strands every child
# row: the parent moves to a new key and the children keep pointing at the old
# one. That is not hypothetical. A census on 2026-09-24 found 5 orphaned
# `interviews` rows and 3 orphaned `recruiter_jobs` rows already in the live
# database, invisible in every view because every read joins on the key.
#
# `company` is the only one of the four key columns in EDITABLE_COLUMNS, so a
# rename is the only way to reach this through the API -- which is what makes a
# fix this small sufficient. Any future table keyed the same way belongs here.
_CHILD_TABLES = ("interviews", "recruiter_jobs")


def _carry_children(db, old_company, new_company, date_added, position_title, link):
    """Move a renamed job's child rows to its new key, in the caller's transaction.

    Deliberately not committed here: it runs inside api_update_job's try block
    so that a collision raised by the parent UPDATE rolls the children back
    with it, rather than leaving them pointing at a company the job no longer
    has.
    """
    for table in _CHILD_TABLES:
        db.execute(
            f"UPDATE {table} SET company = ? WHERE company = ? AND date_added = ? "
            f"AND position_title = ? AND link = ?",
            (new_company, old_company, date_added, position_title, link),
        )


@app.route("/api/jobs/update", methods=["POST"])
def api_update_job():
    payload = request.get_json(force=True)
    company = payload.get("company")
    date_added = payload.get("date_added")
    position_title = payload.get("position_title")
    row_link = payload.get("link")
    field = payload.get("field")
    value = payload.get("value", "")

    if not company or date_added is None:
        return jsonify({"error": "company and date_added are required"}), 400
    if field not in EDITABLE_COLUMNS:
        return jsonify({"error": f"field '{field}' is not editable"}), 400
    if field == "company" and not value.strip():
        return jsonify({"error": "company cannot be blank"}), 400

    db = get_db()

    # Renaming a company moves the row to a new primary key, which can collide.
    # Checked with a SELECT rather than left to the UPDATE, because the driver
    # decides which exception a collision raises -- IntegrityError on SQLite, a
    # bare ValueError over Hrana -- and tests/conftest.py strips TURSO_* for the
    # whole session, so no test can ever exercise the remote path. A SELECT
    # behaves identically on both, so the local suite covers the real behaviour.
    if field == "company" and value != company:
        taken = db.execute(
            "SELECT 1 FROM jobs WHERE company = ? AND date_added = ? "
            "AND position_title = ? AND link = ?",
            (value, date_added, position_title or "", row_link or ""),
        ).fetchone()
        if taken:
            return jsonify({
                "error": f"A job for '{value}' on {date_added} already exists."
            }), 409

    date_applied_value = None
    if field == "status" and value in APPLIED_STATUSES:
        row = db.execute(
            "SELECT date_applied FROM jobs WHERE company = ? AND date_added = ? "
            "AND position_title = ? AND link = ?",
            (company, date_added, position_title or "", row_link or ""),
        ).fetchone()
        if row and not (row["date_applied"] or "").strip():
            date_applied_value = date.today().isoformat()

    try:
        if date_applied_value is not None:
            db.execute(
                "UPDATE jobs SET status = ?, date_applied = ? WHERE company = ? "
                "AND date_added = ? AND position_title = ? AND link = ?",
                (value, date_applied_value, company, date_added,
                 position_title or "", row_link or ""),
            )
        else:
            db.execute(
                f"UPDATE jobs SET {field} = ? WHERE company = ? AND date_added = ? "
                f"AND position_title = ? AND link = ?",
                (value, company, date_added, position_title or "", row_link or ""),
            )
        if field == "company" and value != company:
            _carry_children(db, company, value, date_added,
                            position_title or "", row_link or "")
        db.commit()
    except _WRITE_EXC:
        # Backstop for a collision the SELECT above raced past.
        return jsonify({
            "error": f"A job for '{value}' on {date_added} already exists."
        }), 409

    result = {"ok": True}
    if date_applied_value is not None:
        result["date_applied"] = date_applied_value
    if field == "company" and value != company:
        result["company_profile_moved"] = _carry_company_profile(company, value, db)
        # Unconditional, unlike the profile: prep rows belong to this posting
        # alone, so there is no sibling role they could be stranded from.
        result["prep_items_moved"] = carry_prep_items(
            company, value, date_added, position_title or "", row_link or "")
    return jsonify(result)


def _carry_company_profile(old_company: str, new_company: str, db) -> bool:
    """
    Follows a renamed company to its new key, if it was the last job under the old one.

    The profile is keyed on the employer, not on a job, so two roles at one
    company share one row. Renaming one of them is not a rename of the company
    -- it is usually a correction to that posting -- and moving the research out
    from under the sibling would be wrong. Only when nothing is left behind does
    the profile follow.

    Best-effort: the rename itself has already committed, and a profile that
    stays on the old key is recoverable by hand. Failing the request after a
    successful write would be a worse lie than returning False.
    """
    if not get_company_profile(old_company):
        return False
    remaining = db.execute(
        "SELECT 1 FROM jobs WHERE company = ? LIMIT 1", (old_company,)
    ).fetchone()
    if remaining:
        return False
    try:
        return rename_company_profile(old_company, new_company)
    except Exception:
        return False


# --- Interview prep ----------------------------------------------------------
# Tasks and questions for one job. Reads ride along on /api/jobs/detail?prep=1;
# these three are the writes.

@app.route("/api/prep/add", methods=["POST"])
def api_add_prep_item():
    payload = request.get_json(force=True)
    key = {
        "company": (payload.get("company") or "").strip(),
        "date_added": (payload.get("date_added") or "").strip(),
        "position_title": (payload.get("position_title") or "").strip(),
        "link": (payload.get("link") or "").strip(),
    }
    kind = payload.get("kind")
    body = (payload.get("body") or "").strip()

    if not key["company"]:
        return jsonify({"error": "company is required"}), 400
    if kind not in PREP_KINDS:
        return jsonify({"error": f"kind must be one of {', '.join(PREP_KINDS)}"}), 400
    if not body:
        return jsonify({"error": "body cannot be blank"}), 400

    item_id = add_prep_item(**key, kind=kind, body=body)
    if item_id is None:
        return jsonify({"error": "could not add the item"}), 500
    return jsonify({"ok": True, "id": item_id})


@app.route("/api/prep/update", methods=["POST"])
def api_update_prep_item():
    payload = request.get_json(force=True)
    item_id = payload.get("id")
    if not isinstance(item_id, int):
        return jsonify({"error": "id is required"}), 400

    # Exactly one of the two, so a caller cannot half-tick and half-rewrite an
    # item in a single request and then have to guess which half applied.
    if "done" in payload:
        ok = set_prep_item_done(item_id, bool(payload["done"]))
    elif "body" in payload:
        ok = update_prep_item(item_id, payload.get("body") or "")
        if not ok:
            return jsonify({"error": "body cannot be blank"}), 400
    else:
        return jsonify({"error": "pass either done or body"}), 400

    if not ok:
        return jsonify({"error": "Item not found."}), 404
    return jsonify({"ok": True})


@app.route("/api/prep/delete", methods=["POST"])
def api_delete_prep_item():
    payload = request.get_json(force=True)
    item_id = payload.get("id")
    if not isinstance(item_id, int):
        return jsonify({"error": "id is required"}), 400
    if not delete_prep_item(item_id):
        return jsonify({"error": "Item not found."}), 404
    return jsonify({"ok": True})


# --- Company research --------------------------------------------------------
# The GUI reads and edits; it never researches. Flask cannot invoke a Claude
# skill, and pretending otherwise would put a "Research this company" button
# here that could only ever spin. Claude writes through the MCP tool
# set_company_profile; these two routes are the viewer and the correcting pen.

@app.route("/api/companies/profile")
def api_company_profile():
    company = (request.args.get("company") or "").strip()
    if not company:
        return jsonify({"error": "company is required"}), 400
    profile = get_company_profile(company)
    # A company with nothing written yet is the normal case, not an error: the
    # tab has to render an empty notebook you can start typing into.
    return jsonify({"company": company, "profile": profile})


@app.route("/api/companies/profile/update", methods=["POST"])
def api_update_company_profile():
    payload = request.get_json(force=True)
    company = (payload.get("company") or "").strip()
    field = payload.get("field")
    value = payload.get("value", "")

    if not company:
        return jsonify({"error": "company is required"}), 400
    if field not in set(COMPANY_SECTIONS) | {"website"}:
        return jsonify({"error": f"field '{field}' is not a company profile field"}), 400

    profile = set_company_profile(company, **{field: value})
    if profile is None:
        return jsonify({"error": "could not write the company profile"}), 500
    return jsonify({"ok": True, "profile": profile})


# --- Interviews -------------------------------------------------------------
# The GUI is the only write path for interviews. Every other surface reads.
# A job is identified here by its full composite key, taken straight from the
# row the user clicked, so the "Ambiguous match" problem that company-keyed
# lookups hit on the 67 companies with multiple postings never arises.

@app.route("/insights")
def insights_view():
    # Only what is ahead. This used to ask for include_past=True and split the
    # result on `overdue`, because a booking whose date went by with no outcome
    # recorded had to be counted somewhere. That state no longer exists: a past
    # round simply happened, and belongs to the outcome table further down.
    booked = upcoming_interviews()
    return render_template(
        "insights.html",
        stats=interview_stats(),
        funnel=funnel_stats(),
        rate_min=RATE_MIN_DENOMINATOR,
        ghost_days=GHOSTED_AFTER_DAYS,
        interview_types=INTERVIEW_TYPES,
        recruiters=get_recruiters(),
        recruiter_roles=get_recruiter_jobs(),
        coverage=recruiter_coverage(),
        silence=job_silence_stats(),
        upcoming=booked,
        upcoming_window=UPCOMING_WINDOW_DAYS,
        missing_rounds=jobs_missing_interview_rows(),
        duplicate_rounds=duplicate_interview_rounds(),
    )


@app.route("/interviews")
def interviews_view():
    """Kept so older bookmarks still land somewhere useful."""
    return redirect("/insights", code=302)


@app.route("/api/config")
def api_config():
    # Replaces the Jinja tojson injection jobs.html/kanban.html use today --
    # the React frontend fetches this once instead of getting it baked into
    # server-rendered HTML.
    return jsonify({"status_values": STATUS_VALUES, "interview_types": INTERVIEW_TYPES})


@app.route("/api/funnel")
def api_funnel():
    return jsonify(funnel_stats())


@app.route("/api/interviews/upcoming")
def api_upcoming_interviews():
    """Booked but not yet held. Never counted toward any rate."""
    return jsonify(upcoming_interviews(
        include_past=request.args.get("include_past") in ("1", "true", "yes")))


@app.route("/api/silence")
def api_silence():
    """Derived on read — no silence verdict is ever stored."""
    return jsonify(job_silence_stats())


@app.route("/api/recruiters")
def api_recruiters():
    """
    The GUI may write recruiters. It could not until this endpoint grew the
    routes below, because an agency that reaches you by phone or referral never
    appears in a mailbox and so had nowhere to live.

    What replaced the old rule, rather than simply dropping it: a row the user
    typed is flagged manual_entry, and upsert_recruiter will not let a later
    parse overwrite its name or agency; and a job link carrying a message_id
    belongs to inbox-triage, so the GUI refuses to replace it without an
    explicit override. Both are enforced in jobs_db, not here, so the MCP server
    and the cron scripts get them too.
    """
    return jsonify({
        "recruiters": get_recruiters(),
        "roles": get_recruiter_jobs(),
        "coverage": recruiter_coverage(),
    })


def _recruiter_payload():
    p = request.get_json(force=True) or {}
    return (
        (p.get("name") or "").strip(),
        (p.get("agency") or "").strip(),
        (p.get("email") or "").strip(),
        (p.get("notes") or "").strip(),
        p,
    )


def _recruiter_id(payload):
    """
    The recruiter id as an int, or None when it is absent or not a number.

    Same shape as api_delete_interview's inline check, factored out because
    three routes need it. Without it a body like {"recruiter_id": "abc"} reaches
    int() unguarded and answers 500, where every other id-taking route here
    answers 400.
    """
    try:
        return int(payload.get("recruiter_id"))
    except (TypeError, ValueError):
        return None


@app.route("/api/recruiters/add", methods=["POST"])
def api_add_recruiter():
    """
    Creates a recruiter by hand, keyed on their email address.

    Email is required because it is the identity, not merely a nice-to-have:
    without it there is nothing to dedupe a later inbound message against, and
    the same person would arrive again as a second row.
    """
    name, agency, email, notes, _ = _recruiter_payload()
    if not email:
        return jsonify({"error": "An email address is required — it identifies "
                                 "the recruiter."}), 400
    if not name:
        return jsonify({"error": "A name is required."}), 400

    try:
        recruiter_id = upsert_recruiter(
            source="email", identity=email, name=name, agency=agency,
            email=email, notes=notes, manual_entry=True,
        )
    except _WRITE_EXC as exc:
        return jsonify({"error": str(exc)}), 400

    row = next((r for r in get_recruiters() if r["id"] == recruiter_id), None)
    return jsonify({"ok": True, "recruiter": row})


@app.route("/api/recruiters/update", methods=["POST"])
def api_update_recruiter():
    payload = request.get_json(force=True) or {}
    recruiter_id = _recruiter_id(payload)
    if recruiter_id is None:
        return jsonify({"error": "recruiter_id is required"}), 400

    # None means "not sent, leave alone"; "" means "the user cleared it".
    fields = {k: v for k, v in (("name", payload.get("name")),
                                ("agency", payload.get("agency")),
                                ("email", payload.get("email")),
                                ("notes", payload.get("notes")))
              if v is not None}
    if not fields:
        return jsonify({"error": "nothing to update"}), 400
    if "name" in fields and not fields["name"].strip():
        return jsonify({"error": "A name is required."}), 400

    if not update_recruiter(recruiter_id, **fields):
        return jsonify({"error": "No such recruiter."}), 404
    row = next((r for r in get_recruiters() if r["id"] == recruiter_id), None)
    return jsonify({"ok": True, "recruiter": row})


@app.route("/api/recruiters/delete", methods=["POST"])
def api_delete_recruiter():
    """
    Deletes a recruiter with its links and its messages.

    The messages go too on purpose — see delete_recruiter.

    dry_run: true counts without deleting, which is how the confirm dialog names
    both numbers before the user commits to an delete that cannot be undone.
    """
    payload = request.get_json(force=True) or {}
    recruiter_id = _recruiter_id(payload)
    if recruiter_id is None:
        return jsonify({"error": "recruiter_id is required"}), 400

    res = delete_recruiter(recruiter_id, dry_run=bool(payload.get("dry_run")))
    if not res.get("ok"):
        return jsonify({"error": res.get("error", "Delete failed.")}), 404
    return jsonify(res)


@app.route("/api/jobs/recruiter", methods=["POST"])
def api_set_job_recruiter():
    """
    Points one job at one recruiter, or clears it with recruiter_id: null.

    Deliberately not a field on /api/jobs/update: that route interpolates the
    column name into its UPDATE and is safe only because EDITABLE_COLUMNS gates
    it. The recruiter link is not a jobs column at all — it lives in
    recruiter_jobs — so folding it in would mean weakening the check that makes
    the f-string defensible.

    409 when the existing link came from inbox-triage: the response carries the
    message it came from so the client can say what it is about to override.
    """
    payload = request.get_json(force=True) or {}
    company = (payload.get("company") or "").strip()
    date_added = payload.get("date_added")
    if not company or date_added is None:
        return jsonify({"error": "company and date_added are required"}), 400

    # null or absent clears the link, which is a legitimate request; a value
    # that is present but not a number is not.
    raw_recruiter = payload.get("recruiter_id")
    recruiter_id = None
    if raw_recruiter not in (None, ""):
        recruiter_id = _recruiter_id(payload)
        if recruiter_id is None:
            return jsonify({"error": "recruiter_id must be a number, or null "
                                     "to clear the link."}), 400

    key = dict(
        company=company,
        date_added=date_added,
        position_title=payload.get("position_title") or "",
        link=payload.get("link") or "",
    )

    res = set_job_recruiter(
        **key,
        recruiter_id=recruiter_id,
        override=bool(payload.get("override")),
    )
    if not res["ok"]:
        # An unknown recruiter is the caller's mistake; a triage link is not.
        if res.get("error"):
            return jsonify({"error": res["error"]}), 404
        return jsonify({
            "error": "This job was linked by inbox-triage from a message. "
                     "Overriding it means the next run will not restore it.",
            "blocked": res["blocked"],
        }), 409

    return jsonify({
        "ok": True,
        "removed": res["removed"],
        "recruiter": res["current"],
    })


@app.route("/api/interviews")
def api_interviews():
    return jsonify(get_interviews(
        company=(request.args.get("company") or "").strip(),
        date_added=(request.args.get("date_added") or "").strip(),
        position_title=(request.args.get("position_title") or "").strip(),
        link=(request.args.get("link") or "").strip(),
    ))


@app.route("/api/interviews/stats")
def api_interview_stats():
    return jsonify(interview_stats())


@app.route("/api/interviews/add", methods=["POST"])
def api_add_interview():
    payload = request.get_json(force=True)
    company = (payload.get("company") or "").strip()
    date_added = (payload.get("date_added") or "").strip()
    position_title = (payload.get("position_title") or "").strip()
    link = (payload.get("link") or "").strip()
    interview_type = (payload.get("interview_type") or "").strip()
    scheduled_date = (payload.get("scheduled_date") or "").strip()
    type_label = (payload.get("type_label") or "").strip()
    loop_id = (payload.get("loop_id") or "").strip()
    notes = (payload.get("notes") or "").strip()

    rating = payload.get("self_rating")
    if rating in ("", None):
        rating = None
    else:
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            return jsonify({"error": "self_rating must be a whole number 1-5"}), 400

    if not company:
        return jsonify({"error": "company is required"}), 400
    if interview_type not in INTERVIEW_TYPES:
        return jsonify({"error": f"interview_type must be one of: {', '.join(INTERVIEW_TYPES)}"}), 400
    if interview_type == "other" and not type_label:
        return jsonify({"error": "type_label is required when interview_type is 'other'"}), 400
    # One date, so there is no longer a pair to disagree with each other. The
    # rejection of "both dates at once" went with them.
    if not scheduled_date:
        return jsonify({"error": "scheduled_date (the day the round is on) "
                                 "is required"}), 400

    try:
        new_id = add_interview(
            company=company, date_added=date_added, position_title=position_title,
            link=link, interview_type=interview_type, scheduled_date=scheduled_date,
            type_label=type_label, loop_id=loop_id, self_rating=rating, notes=notes,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"id": new_id})


@app.route("/api/interviews/duplicates")
def api_interview_duplicates():
    return jsonify(duplicate_interview_rounds())


@app.route("/api/interviews/delete", methods=["POST"])
def api_delete_interview():
    payload = request.get_json(force=True)
    try:
        interview_id = int(payload.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id is required"}), 400
    removed = delete_interview(interview_id)
    if not removed:
        return jsonify({"error": "no interview with that id"}), 404
    return jsonify({"deleted": removed})


@app.route("/api/jobs/delete", methods=["POST"])
def api_delete_job():
    payload = request.get_json(force=True)
    company = payload.get("company")
    date_added = payload.get("date_added")
    position_title = payload.get("position_title")
    row_link = payload.get("link")

    if not company or date_added is None:
        return jsonify({"error": "company and date_added are required"}), 400

    deleted = delete_job_by_key(company, date_added, position_title or "", row_link or "")
    if not deleted:
        return jsonify({"error": "Job not found."}), 404
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(port=5151, debug=True)
