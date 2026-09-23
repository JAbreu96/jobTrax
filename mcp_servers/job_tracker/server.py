import os
import sys
from datetime import date, timedelta

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src import jobs_db  # noqa: E402

mcp = FastMCP("job-tracker")


def _compact(row: dict) -> dict:
    return {
        "company": row["company"],
        "title": row["position_title"],
        "link": row["link"],
        "date_added": row["date_added"],
        "date_applied": row["date_applied"],
        "status": row["status"],
        "outreach_date": row["outreach_date"],
    }


def _match_company(rows: list[dict], company: str) -> list[dict]:
    query = company.lower().strip()
    exact = [r for r in rows if r["company"].lower().strip() == query]
    if exact:
        return exact
    return [r for r in rows if query in r["company"].lower()]


def _narrow(rows: list[dict], position_title: str = "", link: str = "") -> list[dict]:
    """
    Narrows company matches down to a single role.

    A link is an exact identity, so it wins outright. Titles are matched exactly
    first, then by substring in either direction, because ATS rejection emails
    routinely pad the title they quote ("Software Engineer II, Backend - Platform
    Team" vs a tracked "Software Engineer II"). Returns every surviving candidate;
    deciding what to do with 0 or 2+ is the caller's job.
    """
    if link:
        exact_link = [r for r in rows if r["link"].strip() == link.strip()]
        if exact_link:
            return exact_link
    if not position_title:
        return rows
    want = position_title.lower().strip()
    exact = [r for r in rows if r["position_title"].lower().strip() == want]
    if exact:
        return exact
    return [r for r in rows
            if want in r["position_title"].lower() or r["position_title"].lower().strip() in want]


def _find_one_match(company: str) -> dict:
    rows = jobs_db.get_all_jobs()
    matches = _match_company(rows, company)
    if not matches:
        raise ValueError(f"No job found matching company: '{company}'")
    if len(matches) > 1:
        names = ", ".join(r["company"] for r in matches)
        raise ValueError(f"Ambiguous match — {len(matches)} companies found: {names}. Be more specific.")
    return matches[0]


@mcp.tool()
def list_jobs_missing_outreach() -> list[dict]:
    """List all tracked jobs that haven't had outreach yet (Outreach Date column is empty)."""
    rows = jobs_db.get_all_jobs()
    return [_compact(r) for r in rows if not r["outreach_date"]]


@mcp.tool()
def list_all_jobs(include_outreached: bool = True) -> list[dict]:
    """List all tracked jobs in compact format. Set include_outreached=False to hide jobs that already have outreach."""
    rows = jobs_db.get_all_jobs()
    if not include_outreached:
        rows = [r for r in rows if not r["outreach_date"]]
    return [_compact(r) for r in rows]


@mcp.tool()
def filter_jobs(
    company: str | None = None,
    has_outreach: bool | None = None,
    days_since_added: int | None = None,
) -> list[dict]:
    """
    Filter jobs by one or more criteria:
    - company: case-insensitive substring match on company name
    - has_outreach: True = only jobs with outreach sent, False = only jobs without
    - days_since_added: only jobs added within the last N days
    """
    rows = jobs_db.get_all_jobs()

    if company:
        rows = _match_company(rows, company)

    if has_outreach is not None:
        if has_outreach:
            rows = [r for r in rows if r["outreach_date"]]
        else:
            rows = [r for r in rows if not r["outreach_date"]]

    if days_since_added is not None:
        cutoff = date.today() - timedelta(days=days_since_added)
        filtered = []
        for r in rows:
            d = jobs_db._parse_date(r["date_added"])
            if d and d >= cutoff:
                filtered.append(r)
        rows = filtered

    return [_compact(r) for r in rows]


@mcp.tool()
def get_job_by_company(company: str) -> dict:
    """
    Get the full details of a job by company name (case-insensitive, substring match).
    Returns the complete record including summary, contacts, and notes.
    Raises an error if no match or multiple ambiguous matches are found.
    """
    return _find_one_match(company)


@mcp.tool()
def mark_outreached(company: str, outreach_date: str = "") -> dict:
    """
    Mark a job as outreached by writing today's date (or a provided date) to the Outreach Date field.
    - company: case-insensitive match
    - outreach_date: YYYY-MM-DD format; defaults to today if not provided
    """
    row = _find_one_match(company)
    date_str = outreach_date.strip() if outreach_date.strip() else str(date.today())
    jobs_db.mark_outreached(row["company"], row["date_added"], date_str,
                            row["position_title"], row["link"])

    return {
        "success": True,
        "company": row["company"],
        "outreach_date": date_str,
    }


# Derived from the single ordered definition in jobs_db, so the set here can
# never drift from the ranking the importer uses to refuse a downgrade.
VALID_STATUSES = set(jobs_db.STATUS_ORDER) - {""}


@mcp.tool()
def add_job(
    company: str,
    title: str,
    link: str,
    summary: str = "",
    location: str = "",
    contacts: str = "",
    notes: str = "",
    status: str = "Tracking",
    date_added: str = "",
) -> dict:
    """
    Add a new job to the tracker, or update it in place if the link already matches
    an existing (non-archived) entry.
    - company, title, link: required
    - summary, location, contacts, notes: optional free-text fields
    - status: defaults to 'Tracking'; must be one of the valid status values
    - date_added: YYYY-MM-DD; defaults to today (ignored when updating an existing match)
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}")

    existing = jobs_db.find_job_by_link(link)
    date_str = existing["date_added"] if existing else (date_added.strip() or str(date.today()))

    job = {
        "company": company.strip(),
        "position_title": title.strip(),
        "job_summary": summary.strip(),
        "location": location.strip(),
        "link": link.strip(),
        "date_added": date_str,
        "contacts": contacts.strip(),
        "notes": notes.strip(),
        "outreach_date": existing["outreach_date"] if existing else "",
        "date_applied": existing["date_applied"] if existing else "",
        "status": status.strip(),
        "followup_log": existing["followup_log"] if existing else "",
    }
    jobs_db.upsert_job(job)

    return {"success": True, "updated": existing is not None, **_compact(job)}


@mcp.tool()
def update_job_status(company: str, status: str,
                      position_title: str = "", link: str = "") -> dict:
    """
    Update the Status field for a job. Valid values:
    Tracking, Applied, Phone Screen, Technical, System Design, Behavioral, Offer, Accepted, Rejected.
    - company: case-insensitive match
    - status: one of the valid status values above
    - position_title: optional — required when the company has more than one tracked role
    - link: optional — exact posting URL, the most precise way to target a row

    Without position_title/link this updates the company's only row, and raises if
    the company has several. Never guesses: one rejection email must not close out
    every role at that company.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}")

    if position_title or link:
        matches = _narrow(_match_company(jobs_db.get_all_jobs(), company), position_title, link)
        if not matches:
            raise ValueError(
                f"No job found for company '{company}' matching title '{position_title}' / link '{link}'."
            )
        if len(matches) > 1:
            titles = ", ".join(r["position_title"] for r in matches)
            raise ValueError(
                f"Ambiguous — {len(matches)} roles at '{company}' match: {titles}. Pass an exact link."
            )
        row = matches[0]
    else:
        row = _find_one_match(company)
    jobs_db.update_status(row["company"], row["date_added"], status,
                          row["position_title"], row["link"])

    return {"success": True, "company": row["company"],
            "position_title": row["position_title"], "status": status}


@mcp.tool()
def find_job_for_email(company: str, title_hint: str = "", link: str = "") -> dict:
    """
    Resolve an inbound email to exactly one tracked job, without writing anything.

    Returns {"match": "exact"|"ambiguous"|"none", "candidates": [...]}.
    Call this before updating status from an email: on "exact" it is safe to write
    using the returned position_title, and on anything else the caller should ask a
    human rather than guess. Built for inbox-triage, where a wrong silent write is
    far more costly than an extra question.
    """
    rows = _match_company(jobs_db.get_all_jobs(), company)
    if not rows:
        return {"match": "none", "candidates": [], "reason": f"No tracked job for company '{company}'."}

    matches = _narrow(rows, title_hint, link)
    candidates = [_compact(r) for r in (matches or rows)]

    # A single hit is only "exact" if something actually pinned it down. Without a
    # title or link, _narrow is a pass-through, so a lone *substring* company hit
    # would otherwise be reported as certain: "Citi" matches "08763 Citi Canada
    # Technology Services ULC", and a US rejection would close a live Canadian role.
    pinned = bool(link) or bool(title_hint) or \
        any(r["company"].lower().strip() == company.lower().strip() for r in matches)

    if len(matches) == 1 and pinned:
        return {"match": "exact", "candidates": candidates}
    if len(matches) == 1:
        return {"match": "ambiguous", "candidates": candidates,
                "reason": (f"'{company}' only matched '{matches[0]['company']}' as a substring "
                           "and no title was given — too weak to write on.")}
    if not matches:
        return {"match": "none", "candidates": candidates,
                "reason": f"'{company}' has {len(rows)} tracked role(s), none matching '{title_hint}'."}
    return {"match": "ambiguous", "candidates": candidates,
            "reason": f"{len(matches)} roles at '{company}' match '{title_hint}'."}


@mcp.tool()
def update_notes(company: str, notes: str) -> dict:
    """
    Overwrite the Notes field for a job.
    - company: case-insensitive match
    - notes: new notes content (replaces existing value)
    """
    row = _find_one_match(company)
    jobs_db.update_notes(row["company"], row["date_added"], notes,
                         row["position_title"], row["link"])
    return {"success": True, "company": row["company"], "notes": notes}


@mcp.tool()
def update_summary(company: str, job_summary: str) -> dict:
    """
    Overwrite the job_summary (JD) field for a job.
    - company: case-insensitive match
    - job_summary: new summary content (replaces existing value)
    """
    row = _find_one_match(company)
    jobs_db.update_summary(row["company"], row["date_added"], job_summary,
                           row["position_title"], row["link"])
    return {"success": True, "company": row["company"], "job_summary": job_summary}


@mcp.tool()
def update_contacts(company: str, contacts: str) -> dict:
    """
    Overwrite the Contacts field for a job.
    - company: case-insensitive match
    - contacts: new contacts content (replaces existing value)
    """
    row = _find_one_match(company)
    jobs_db.update_contacts(row["company"], row["date_added"], contacts,
                            row["position_title"], row["link"])
    return {"success": True, "company": row["company"], "contacts": contacts}


@mcp.tool()
def get_stats() -> dict:
    """
    Return a summary of the job tracker: total jobs, counts per status, and outreach coverage.
    Useful for digests and dashboards without pulling every row.
    """
    rows = jobs_db.get_all_jobs()
    status_counts: dict[str, int] = {}
    for r in rows:
        s = r["status"] or "Unknown"
        status_counts[s] = status_counts.get(s, 0) + 1

    outreached = sum(1 for r in rows if r["outreach_date"])
    return {
        "total": len(rows),
        "by_status": status_counts,
        "outreached": outreached,
        "not_outreached": len(rows) - outreached,
    }


@mcp.tool()
def list_jobs_needing_followup(days: int = 7) -> list[dict]:
    """
    Return jobs that are stale and may need a follow-up nudge. A job qualifies if status
    is still 'Applied' AND either:
    - date_applied is set and more than `days` days ago, OR
    - outreach_date is set and more than `days` days ago (and no date_applied yet)
    Sorted oldest activity first. Default threshold: 7 days.
    """
    rows = jobs_db.get_all_jobs()
    cutoff = date.today() - timedelta(days=days)
    stale = []
    for r in rows:
        if r["status"] != "Applied":
            continue
        anchor = jobs_db._parse_date(r["date_applied"]) or jobs_db._parse_date(r["outreach_date"])
        if anchor and anchor <= cutoff:
            stale.append((anchor, r))
    stale.sort(key=lambda x: x[0])
    return [_compact(r) for _, r in stale]


@mcp.tool()
def list_jobs_added_recently(days: int = 7) -> list[dict]:
    """List jobs added within the last N days (default: 7), sorted newest first."""
    rows = jobs_db.get_all_jobs()
    cutoff = date.today() - timedelta(days=days)
    recent = []
    for r in rows:
        d = jobs_db._parse_date(r["date_added"])
        if d and d >= cutoff:
            recent.append((d, r))
    recent.sort(key=lambda x: x[0], reverse=True)
    return [_compact(r) for _, r in recent]


@mcp.tool()
def archive_old_jobs(days: int = 60, dry_run: bool = False) -> dict:
    """
    Soft-archive jobs older than `days` days (default: 60) — sets them aside so they
    no longer show up in normal listings, but keeps them in the local DB.
    - dry_run: if True, returns which jobs would be archived without making any changes.
    """
    result = jobs_db.archive_jobs(days=days, dry_run=dry_run)
    return {
        "dry_run": result["dry_run"],
        ("would_archive_count" if dry_run else "archived_count"): result["count"],
        "days_threshold": days,
        "companies": result["companies"],
    }


# --- Interviews (read-only) -------------------------------------------------
# Writes go through the GUI only. Reading needs no single-job resolution, so
# these are immune to the "Ambiguous match" problem that company-keyed writes
# hit on companies with more than one tracked posting.

@mcp.tool()
def interview_rates() -> dict:
    """
    Conversion rate for each interview type: how often a round was followed by
    another round (or an offer) versus followed by a rejection.

    Rate = advanced / (advanced + failed). Rounds whose process is still open are
    reported as awaiting_outcome and left out of the denominator, so a rate is never
    dragged down by interviews you simply have not heard back about yet.
    Each type also splits into `standalone` and `loop`: a failed onsite marks
    every round inside it failed, since the rejection never says which round lost
    it, and the split is what makes that influence visible.
    """
    return jobs_db.interview_stats()


@mcp.tool()
def list_interviews(company: str = "") -> list[dict]:
    """
    Every interview round logged, oldest first, each labelled advanced / failed /
    awaiting_outcome. Pass `company` to narrow to one company (all of its postings).
    """
    rows = jobs_db.classify_interviews()
    if company:
        needle = company.strip().lower()
        rows = [r for r in rows if needle in (r["company"] or "").lower()]
    return [
        {
            "company": r["company"],
            "position_title": r["position_title"],
            "interview_type": r["type_label"] if r["interview_type"] == "other" and r["type_label"]
                              else r["interview_type"],
            "scheduled_date": r["scheduled_date"],
            "loop_id": r["loop_id"],
            "self_rating": r["self_rating"],
            "outcome": r["outcome"],
            "notes": r["notes"],
        }
        for r in rows
    ]


# --- Recruiters -------------------------------------------------------------
# A recruiter pitches N roles. record_recruiter_outreach is the single write
# entry point inbox-triage calls; everything else here reads.

@mcp.tool()
def list_recruiters() -> list[dict]:
    """
    Every recruiter who has sent inbound outreach, most recently heard from first.

    `role_count` is how many roles they have pitched; `reply_count` is how many
    times Joel answered.
    """
    return [
        {
            "name": r["name"],
            "agency": r["agency"],
            "source": r["source"],
            "identity": r["identity"],
            "email": r["email"],
            "roles": r["role_count"],
            "replies": r["reply_count"],
            "first_seen": r["first_seen"],
            "last_seen": r["last_seen"],
        }
        for r in jobs_db.get_recruiters()
    ]


@mcp.tool()
def recruiter_roles(identity: str = "") -> list[dict]:
    """
    Roles sourced by recruiters, newest first.

    Pass `identity` (an email address, or a LinkedIn profile slug) to narrow to
    one recruiter. `job_status` is None when the job row has since been deleted
    or re-keyed — that is real breakage, so it is shown rather than hidden.
    """
    rows = jobs_db.get_recruiter_jobs()
    if identity:
        needle = identity.strip().lower()
        rows = [r for r in rows if needle == (r["recruiter_identity"] or "").lower()]
    return [
        {
            "recruiter": r["recruiter_name"],
            "agency": r["recruiter_agency"],
            "identity": r["recruiter_identity"],
            "company": r["company"],
            "position_title": r["position_title"],
            "sourced_date": r["sourced_date"],
            "job_status": r["job_status"],
        }
        for r in rows
    ]


@mcp.tool()
def record_recruiter_outreach(
    source: str,
    identity: str,
    company: str,
    position_title: str,
    occurred_date: str = "",
    name: str = "",
    agency: str = "",
    email: str = "",
    notes: str = "",
    account: str = "primary",
    message_id: str = "",
    thread_id: str = "",
    subject: str = "",
) -> dict:
    """
    Captures ONE recruiter-sourced role. Call once per role, not once per email.

    A recruiter sending three roles is three calls sharing one message_id — that
    is what keeps them as three independently-trackable rows instead of one row
    with a slash-joined title.

    `source` is 'email' (identity = the sender address) or 'linkedin' (identity =
    the profile slug). LinkedIn InMail arrives from a shared relay address, so
    the address cannot identify the recruiter.

    Creates the job row at status 'Tracking' with a deterministic synthetic link,
    so re-processing the same email updates rather than duplicates. Idempotent.
    """
    if source not in jobs_db.RECRUITER_SOURCES:
        return {"error": f"source must be one of: {', '.join(jobs_db.RECRUITER_SOURCES)}"}
    if not identity.strip():
        return {"error": "identity is required"}
    if not company.strip() or not position_title.strip():
        return {"error": "company and position_title are required"}

    when = occurred_date.strip() or date.today().isoformat()
    title = position_title.strip()
    link = jobs_db.recruiter_link(source, identity.strip(), title)

    recruiter_id = jobs_db.upsert_recruiter(
        source=source, identity=identity.strip(), name=name, agency=agency,
        email=email, seen_date=when,
    )

    # Keyed on the synthetic link, so a re-processed email finds the row it
    # created last time and keeps its original date_added and status.
    existing = jobs_db.find_job_by_link(link)
    jobs_db.upsert_job({
        "company": company.strip(),
        "position_title": title,
        "job_summary": "",
        "location": "",
        "link": link,
        "date_added": (existing or {}).get("date_added") or when,
        "contacts": f"{name} — {email}".strip(" —") if (name or email) else "",
        "notes": notes,
        "outreach_date": "",
        "date_applied": "",
        "status": (existing or {}).get("status") or "Tracking",
        "followup_log": "",
    })
    jobs_db.link_recruiter_job(
        recruiter_id, company=company.strip(),
        date_added=(existing or {}).get("date_added") or when,
        position_title=title, link=link, sourced_date=when,
        account=account, message_id=message_id,
    )
    if message_id:
        jobs_db.record_recruiter_message(
            recruiter_id, "inbound", when, subject=subject,
            account=account, message_id=message_id, thread_id=thread_id,
        )
    return {"recruiter_id": recruiter_id, "company": company.strip(),
            "position_title": title, "link": link}


@mcp.tool()
def record_recruiter_reply(identity: str, source: str = "email",
                           occurred_date: str = "", account: str = "primary",
                           message_id: str = "", thread_id: str = "",
                           subject: str = "") -> dict:
    """
    Records that Joel answered a recruiter. Idempotent on (account, message_id).
    """
    if source not in jobs_db.RECRUITER_SOURCES:
        return {"error": f"source must be one of: {', '.join(jobs_db.RECRUITER_SOURCES)}"}
    recruiter_id = jobs_db.upsert_recruiter(source=source, identity=identity)
    when = occurred_date.strip() or date.today().isoformat()
    jobs_db.record_recruiter_message(
        recruiter_id, "reply", when, subject=subject,
        account=account, message_id=message_id, thread_id=thread_id,
    )
    return {"recruiter_id": recruiter_id, "recorded": when}


if __name__ == "__main__":
    mcp.run()
