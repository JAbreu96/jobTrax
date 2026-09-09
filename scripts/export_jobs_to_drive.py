"""
Exports the local job tracker DB (data/jobs.db) to a "Daily Export" tab inside
the existing Job Funnel spreadsheet, overwriting its contents each run.

Writes to a tab within an already-shared file rather than creating a new Drive
file — service accounts on a personal (non-Workspace) Google account have zero
storage quota for creating new files, but editing an existing file they already
have edit access to is unaffected by that limit. Sheet1/Archive (the original
tracker data) are left untouched as a frozen rollback backup.

Usage:
    python scripts/export_jobs_to_drive.py

Env:
    GOOGLE_APPLICATION_CREDENTIALS - path to the service account JSON
        (defaults to the same fallback path used by sync_jobs_to_sqlite.py)
"""

import os
import sys

import gspread
from google.oauth2 import service_account

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src import config  # noqa: E402
from src.jobs_db import (  # noqa: E402
    COLUMNS, INTERVIEW_COLUMNS, RECRUITER_COLUMNS, RECRUITER_JOB_COLUMNS,
    get_all_jobs, get_interviews, get_recruiter_jobs, get_recruiters,
)

SERVICE_ACCOUNT_FILE = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.expanduser("~/.config/agents/gcp-service-account.json")
)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

EXPORT_WORKSHEET = "Daily Export"
INTERVIEWS_WORKSHEET = "Interviews"
RECRUITERS_WORKSHEET = "Recruiters"
RECRUITER_ROLES_WORKSHEET = "Recruiter Roles"


def export_and_upload():
    jobs = get_all_jobs()

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.require("SPREADSHEET_ID"))

    try:
        ws = spreadsheet.worksheet(EXPORT_WORKSHEET)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=EXPORT_WORKSHEET, rows=1, cols=len(COLUMNS))
        print(f"Created '{EXPORT_WORKSHEET}' tab")

    rows = [COLUMNS] + [[job.get(c, "") or "" for c in COLUMNS] for job in jobs]
    ws.clear()
    ws.update(range_name="A1", values=rows, value_input_option="RAW")

    print(f"Wrote {len(jobs)} rows to '{EXPORT_WORKSHEET}' tab")

    _export_interviews(spreadsheet)
    _export_recruiters(spreadsheet)


def _export_interviews(spreadsheet) -> None:
    """
    Mirrors the interviews table outward, DB -> Sheet, and never the reverse.

    jobs.db is gitignored and its only backups are ad-hoc local .bak files on the
    same disk; jobs themselves survive that because the Sheet is upstream of them.
    Interview rounds have no such copy and cannot be reconstructed from anywhere,
    so they get one here.

    This must stay one-way. The GUI is the sole writer of interviews, which makes
    the DB authoritative for them — the opposite of jobs, where the Sheet is
    upstream. If sync_jobs_to_sqlite.py ever learned to read this tab, a stale
    export could overwrite rounds that were logged locally.
    """
    interviews = get_interviews()

    try:
        ws = spreadsheet.worksheet(INTERVIEWS_WORKSHEET)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=INTERVIEWS_WORKSHEET, rows=1, cols=len(INTERVIEW_COLUMNS)
        )
        print(f"Created '{INTERVIEWS_WORKSHEET}' tab")

    rows = [INTERVIEW_COLUMNS] + [
        [("" if r.get(c) is None else r.get(c)) for c in INTERVIEW_COLUMNS]
        for r in interviews
    ]
    ws.clear()
    ws.update(range_name="A1", values=rows, value_input_option="RAW")

    print(f"Wrote {len(interviews)} rows to '{INTERVIEWS_WORKSHEET}' tab")


def _write_tab(spreadsheet, title, columns, rows) -> None:
    """Replaces one tab wholesale. One-way, DB -> Sheet."""
    try:
        ws = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=1, cols=len(columns))
        print(f"Created '{title}' tab")

    values = [columns] + [
        [("" if r.get(c) is None else r.get(c)) for c in columns] for r in rows
    ]
    ws.clear()
    ws.update(range_name="A1", values=values, value_input_option="RAW")
    print(f"Wrote {len(rows)} rows to '{title}' tab")


def _export_recruiters(spreadsheet) -> None:
    """
    Mirrors the recruiter tables outward, DB -> Sheet, and never the reverse.

    Same reasoning as _export_interviews: the Sheet is upstream of `jobs`, but it
    knows nothing about recruiters. Who sent what, and which roles came from one
    person, exists only in jobs.db — which is gitignored and backed up only by
    local .bak files on the same disk.

    Two tabs because the shape is one-to-many: flattening a recruiter across
    their roles would repeat their details on every line and lose anyone who has
    pitched nothing yet.
    """
    _write_tab(spreadsheet, RECRUITERS_WORKSHEET, RECRUITER_COLUMNS,
               get_recruiters())
    _write_tab(spreadsheet, RECRUITER_ROLES_WORKSHEET, RECRUITER_JOB_COLUMNS,
               get_recruiter_jobs())


if __name__ == "__main__":
    export_and_upload()
