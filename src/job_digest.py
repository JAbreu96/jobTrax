"""Job search pipeline digest — reads Google Sheets tracker and outputs JSON summary."""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Also loads .env, by absolute path. The bare load_dotenv() that used to sit here
# searched from the cwd, so the scheduled run -- which starts from / -- found
# nothing and said so nowhere.
from src import config  # noqa: E402

import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials


DEFAULT_SPREADSHEET = config.SPREADSHEET_URL
DEFAULT_WORKSHEET = config.SHEET_WORKSHEET

# Column indices (0-based) matching current sheet layout
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


def _sheet_client(service_account_json: str) -> gspread.Client:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(service_account_json, scopes=scopes)
    return gspread.authorize(creds)


def _open_worksheet(client: gspread.Client, spreadsheet: str, worksheet_name: str):
    spreadsheet = spreadsheet.strip()
    if spreadsheet.startswith("http://") or spreadsheet.startswith("https://"):
        spread = client.open_by_url(spreadsheet)
    elif re.match(r"^[A-Za-z0-9-_]+$", spreadsheet):
        spread = client.open_by_key(spreadsheet)
    else:
        spread = client.open(spreadsheet)

    for candidate in [worksheet_name, "Sheet1", "job tracker", "Job Tracker"]:
        try:
            return spread.worksheet(candidate)
        except WorksheetNotFound:
            continue

    # header-based fallback
    for ws in spread.worksheets():
        headers = ws.row_values(1)
        if headers and "Job Title" in headers and "Link" in headers:
            return ws

    raise RuntimeError(f"Could not find a job tracker worksheet in '{spreadsheet}'")


def get_all_rows(
    spreadsheet: str = DEFAULT_SPREADSHEET,
    worksheet_name: str = DEFAULT_WORKSHEET,
    service_account_json: Optional[str] = None,
) -> list[dict]:
    """Read all data rows from the job tracker sheet, skipping header and empty rows."""
    if service_account_json is None:
        service_account_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not service_account_json:
        raise ValueError(
            "Google service account JSON path required via --service-account-json "
            "or GOOGLE_APPLICATION_CREDENTIALS env var"
        )

    client = _sheet_client(service_account_json)
    ws = _open_worksheet(client, spreadsheet, worksheet_name)
    all_values = ws.get_all_values()

    rows = []
    for raw in all_values[1:]:  # skip header
        # pad short rows
        while len(raw) <= COL_STATUS:
            raw.append("")
        if not any(raw):
            continue
        rows.append({
            "company": raw[COL_COMPANY].strip(),
            "title": raw[COL_TITLE].strip(),
            "summary": raw[COL_SUMMARY].strip(),
            "link": raw[COL_LINK].strip(),
            "date_added": raw[COL_DATE_ADDED].strip(),
            "contacts": raw[COL_CONTACTS].strip(),
            "notes": raw[COL_NOTES].strip(),
            "outreach_date": raw[COL_OUTREACH].strip(),
            "date_applied": raw[COL_DATE_APPLIED].strip(),
            "status": raw[COL_STATUS].strip(),
        })
    return rows


def _parse_date(value: str) -> Optional[date]:
    """Try common date formats, return None on failure."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def classify_status(row: dict) -> str:
    """Return 'applied', 'stale', or 'not_applied'."""
    if row.get("date_applied"):
        return "applied"
    added = _parse_date(row.get("date_added", ""))
    if added and (date.today() - added) > timedelta(days=14):
        return "stale"
    return "not_applied"


def compute_stats(rows: list[dict]) -> dict:
    today = date.today()
    cutoff_7 = today - timedelta(days=7)

    applied = stale = not_applied = 0
    added_last_7 = applied_last_7 = 0

    for row in rows:
        status = row.get("status", classify_status(row))
        if status == "applied":
            applied += 1
        elif status == "stale":
            stale += 1
        else:
            not_applied += 1

        added = _parse_date(row.get("date_added", ""))
        if added and added >= cutoff_7:
            added_last_7 += 1

        app_date = _parse_date(row.get("date_applied", ""))
        if app_date and app_date >= cutoff_7:
            applied_last_7 += 1

    return {
        "total": len(rows),
        "applied": applied,
        "not_applied": not_applied,
        "stale": stale,
        "added_last_7_days": added_last_7,
        "applied_last_7_days": applied_last_7,
    }


def build_digest(
    spreadsheet: str = DEFAULT_SPREADSHEET,
    worksheet_name: str = DEFAULT_WORKSHEET,
    service_account_json: Optional[str] = None,
) -> dict:
    """Read the sheet, classify rows, compute stats, return digest dict."""
    rows = get_all_rows(spreadsheet, worksheet_name, service_account_json)
    for row in rows:
        row["status"] = classify_status(row)
    stats = compute_stats(rows)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_jobs": len(rows),
        "rows": rows,
        "stats": stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Output job tracker pipeline as JSON")
    parser.add_argument(
        "--spreadsheet",
        default=os.getenv("JOB_TRACKER_SPREADSHEET", DEFAULT_SPREADSHEET),
        help="Spreadsheet URL, ID, or name",
    )
    parser.add_argument(
        "--worksheet",
        default=os.getenv("JOB_TRACKER_WORKSHEET", DEFAULT_WORKSHEET),
        help="Worksheet tab name",
    )
    parser.add_argument(
        "--service-account-json",
        default=None,
        help="Path to Google service account JSON credentials",
    )
    args = parser.parse_args()

    try:
        digest = build_digest(
            spreadsheet=args.spreadsheet,
            worksheet_name=args.worksheet,
            service_account_json=args.service_account_json,
        )
        print(json.dumps(digest, indent=2))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
