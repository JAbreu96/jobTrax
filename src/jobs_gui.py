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
    STATUS_ORDER,
    UPCOMING_WINDOW_DAYS,
    _connect,
    _WRITE_EXC,
    shared_connection as _shared_connection,
    GHOSTED_AFTER_DAYS,
    RATE_MIN_DENOMINATOR,
    add_interview,
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


# The list is ordered by date_added DESC, and date_added is not unique, so a
# cursor carrying only the date cannot say where inside a tied run a page
# stopped. It carries the whole primary key -- the tie-break the index
# (idx_jobs_list) is built on -- and the comparison below walks it in the same
# order. Opaque on the wire so the client never builds one by hand.
_CURSOR_FIELDS = ("d", "c", "p", "l")   # date_added, company, position_title, link
_MAX_PAGE = 500


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
    out = []
    for r in rows:
        d = dict(r)
        hit = linked.get((d["company"], d["date_added"],
                          d.get("position_title") or "", d.get("link") or ""))
        d["recruiter_id"] = hit["recruiter_id"] if hit else None
        d["recruiter_name"] = hit["recruiter_name"] if hit else None
        d["recruiter_agency"] = hit["recruiter_agency"] if hit else None
        # Tells the row whether the link came from a mail, which is what makes
        # it read-only until the user overrides it.
        d["recruiter_from_triage"] = bool(hit and (hit.get("message_id") or "").strip())
        out.append(d)

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

    payload = {"interviews": get_interviews(**key)}
    if request.args.get("summary") not in ("0", "false", "no"):
        row = get_db().execute(
            "SELECT job_summary FROM jobs WHERE company = ? AND date_added = ? "
            "AND position_title = ? AND link = ?",
            (key["company"], key["date_added"], key["position_title"], key["link"]),
        ).fetchone()
        payload["job_summary"] = (row["job_summary"] if row else "") or ""
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
    if field == "status" and value == "Applied":
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
        db.commit()
    except _WRITE_EXC:
        # Backstop for a collision the SELECT above raced past.
        return jsonify({
            "error": f"A job for '{value}' on {date_added} already exists."
        }), 409

    result = {"ok": True}
    if date_applied_value is not None:
        result["date_applied"] = date_applied_value
    return jsonify(result)


# --- Interviews -------------------------------------------------------------
# The GUI is the only write path for interviews. Every other surface reads.
# A job is identified here by its full composite key, taken straight from the
# row the user clicked, so the "Ambiguous match" problem that company-keyed
# lookups hit on the 67 companies with multiple postings never arises.

@app.route("/insights")
def insights_view():
    # One query, split two ways. The card shows only what is ahead, but a booking
    # whose date went by with no outcome recorded has to be counted somewhere --
    # it is invisible to missing_rounds, which only sees jobs with no round at all.
    booked = upcoming_interviews(include_past=True)
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
        upcoming=[r for r in booked if not r["overdue"]],
        past_bookings=[r for r in booked if r["overdue"]],
        upcoming_window=UPCOMING_WINDOW_DAYS,
        missing_rounds=jobs_missing_interview_rows(),
    )


@app.route("/interviews")
def interviews_view():
    """Kept so older bookmarks still land somewhere useful."""
    return redirect("/insights", code=302)


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
    occurred_date = (payload.get("occurred_date") or "").strip()
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
    # The two dates are the two states a round can be in, and it is exactly one
    # of them. jobs_db.add_interview already rejects neither; both is rejected
    # here because it is the more confusing error -- upcoming_interviews() reads
    # a round with an occurred_date as done, so a row carrying both claims to be
    # simultaneously booked and held, and silently vanishes from "Coming up".
    if not occurred_date and not scheduled_date:
        return jsonify({"error": "one of occurred_date (it happened) or "
                                 "scheduled_date (it is booked) is required"}), 400
    if occurred_date and scheduled_date:
        return jsonify({"error": "give occurred_date or scheduled_date, not both — "
                                 "mark a booked round as held instead"}), 400

    try:
        new_id = add_interview(
            company=company, date_added=date_added, position_title=position_title,
            link=link, interview_type=interview_type, occurred_date=occurred_date,
            scheduled_date=scheduled_date,
            type_label=type_label, loop_id=loop_id, self_rating=rating, notes=notes,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"id": new_id})


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
