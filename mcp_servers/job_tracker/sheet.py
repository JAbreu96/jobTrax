import logging
import os
import sys
from datetime import date, datetime, timedelta

import gspread
from google.oauth2 import service_account

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src import config  # noqa: E402

logger = logging.getLogger(__name__)

WORKSHEET = config.SHEET_WORKSHEET
ARCHIVE_WORKSHEET = "Archive"
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COL_COMPANY = 0
COL_TITLE = 1
COL_SUMMARY = 2
COL_LOCATION = 3
COL_LINK = 4
COL_DATE_ADDED = 5
COL_CONTACTS = 6
COL_NOTES = 7
COL_OUTREACH = 8
COL_DATE_APPLIED = 9
COL_STATUS = 10


_client: gspread.Client | None = None


def _get_client() -> gspread.Client:
    global _client
    if _client is None:
        path = SERVICE_ACCOUNT_FILE or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
        creds = service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client


def get_sheet() -> gspread.Worksheet:
    return _get_client().open_by_key(config.require("SPREADSHEET_ID")).worksheet(WORKSHEET)


def get_archive_sheet() -> gspread.Worksheet:
    return (
        _get_client()
        .open_by_key(config.require("SPREADSHEET_ID"))
        .worksheet(ARCHIVE_WORKSHEET)
    )


def _parse_date(value: str) -> date | None:
    if not value or not value.strip():
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    logger.warning("Unrecognized date format %r — row will be excluded from date filters", value.strip())
    return None


def _row_to_dict(row: list, row_index: int) -> dict:
    def cell(i):
        return row[i].strip() if i < len(row) and row[i] else ""

    return {
        "row_index": row_index,
        "company": cell(COL_COMPANY),
        "title": cell(COL_TITLE),
        "summary": cell(COL_SUMMARY),
        "location": cell(COL_LOCATION),
        "link": cell(COL_LINK),
        "date_added": cell(COL_DATE_ADDED),
        "contacts": cell(COL_CONTACTS),
        "notes": cell(COL_NOTES),
        "outreach_date": cell(COL_OUTREACH),
        "date_applied": cell(COL_DATE_APPLIED),
        "status": cell(COL_STATUS),
    }


def read_all_rows() -> list[dict]:
    sheet = get_sheet()
    all_values = sheet.get_all_values()
    rows = []
    for i, row in enumerate(all_values[1:], start=2):  # skip header, 1-based index
        if not row or not row[0].strip():
            continue
        rows.append(_row_to_dict(row, i))
    return rows


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
    """Append a new job row to Sheet1. Returns the inserted row dict."""
    ws = get_sheet()
    date_str = date_added.strip() if date_added.strip() else str(date.today())
    row = [""] * 11
    row[COL_COMPANY] = company.strip()
    row[COL_TITLE] = title.strip()
    row[COL_SUMMARY] = summary.strip()
    row[COL_LOCATION] = location.strip()
    row[COL_LINK] = link.strip()
    row[COL_DATE_ADDED] = date_str
    row[COL_CONTACTS] = contacts.strip()
    row[COL_NOTES] = notes.strip()
    row[COL_OUTREACH] = ""
    row[COL_DATE_APPLIED] = ""
    row[COL_STATUS] = status.strip()

    # Find the last row with data in column A, then write to last_row + 1.
    # This correctly appends at the end of existing data without overshooting
    # the table boundary (as append_row does) or landing in a gap (as
    # first-empty-row scanning does when rows have been deleted).
    all_values = ws.get_all_values()
    last_data_row = 1  # header is row 1
    for i, r in enumerate(all_values[1:], start=2):
        if r and r[0].strip():
            last_data_row = i
    new_row_index = last_data_row + 1
    ws.update(f"A{new_row_index}:K{new_row_index}", [row], value_input_option="USER_ENTERED")

    return _row_to_dict(row, new_row_index)


def _find_live_row_index(ws: gspread.Worksheet, company: str, hint: int) -> int:
    """Return the current row index for a company, re-reading the sheet to avoid stale indices.
    Checks the hinted row first; falls back to a full scan."""
    all_values = ws.get_all_values()
    needle = company.strip().lower()
    # Fast path: hint is still correct
    if 1 <= hint - 1 < len(all_values):
        if all_values[hint - 1] and all_values[hint - 1][COL_COMPANY].strip().lower() == needle:
            return hint
    # Slow path: scan for the company
    for i, row in enumerate(all_values[1:], start=2):
        if row and row[COL_COMPANY].strip().lower() == needle:
            return i
    raise ValueError(f"Company '{company}' no longer found in sheet — it may have been deleted or archived.")


def mark_outreached(company: str, hint_row: int, date_str: str) -> None:
    ws = get_sheet()
    row_index = _find_live_row_index(ws, company, hint_row)
    ws.update_cell(row_index, COL_OUTREACH + 1, date_str)


def update_status(company: str, hint_row: int, status: str) -> None:
    ws = get_sheet()
    row_index = _find_live_row_index(ws, company, hint_row)
    ws.update_cell(row_index, COL_STATUS + 1, status)


def update_notes(company: str, hint_row: int, notes: str) -> None:
    ws = get_sheet()
    row_index = _find_live_row_index(ws, company, hint_row)
    ws.update_cell(row_index, COL_NOTES + 1, notes)


def update_contacts(company: str, hint_row: int, contacts: str) -> None:
    ws = get_sheet()
    row_index = _find_live_row_index(ws, company, hint_row)
    ws.update_cell(row_index, COL_CONTACTS + 1, contacts)


def archive_old_jobs(days: int = 60) -> list[dict]:
    """Move jobs older than `days` days from Sheet1 to Archive. Returns archived rows."""
    ws = get_sheet()
    archive_ws = get_archive_sheet()
    all_values = ws.get_all_values()
    header = all_values[0]
    cutoff = date.today() - timedelta(days=days)

    rows_to_archive = []
    row_indices_to_delete = []

    for i, row in enumerate(all_values[1:], start=2):
        if not row or not row[0].strip():
            continue
        d = _parse_date(row[COL_DATE_ADDED] if COL_DATE_ADDED < len(row) else "")
        if d and d < cutoff:
            rows_to_archive.append(row)
            row_indices_to_delete.append(i)

    if rows_to_archive:
        archive_ws.append_rows(rows_to_archive, value_input_option="USER_ENTERED")
        # Batch delete in reverse order so earlier deletions don't shift later indices
        requests = [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": ws.id,
                        "dimension": "ROWS",
                        "startIndex": row_idx - 1,  # Sheets API is 0-based
                        "endIndex": row_idx,
                    }
                }
            }
            for row_idx in sorted(row_indices_to_delete, reverse=True)
        ]
        ws.spreadsheet.batch_update({"requests": requests})

    return [_row_to_dict(r, 0) for r in rows_to_archive]
