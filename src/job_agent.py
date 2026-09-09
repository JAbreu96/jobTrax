"""Job-search agent that scrapes a job page and logs into Google Sheets."""

import os
import re
import sys
import argparse
from datetime import date, datetime, timezone
from dataclasses import dataclass
from typing import Dict, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Also loads .env, by absolute path -- the bare load_dotenv() that used to sit
# here searched from the cwd, so under cron (which runs from /) it found nothing
# and reported no error.
from src import config  # noqa: E402

import anthropic
import requests
from bs4 import BeautifulSoup
import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials


@dataclass
class JobRecord:
    url: str
    title: str
    company: str
    location: str
    posted_date: str
    summary: str
    notes: str = ""
    contacts: str = ""


class JobTrackerAgent:
    USER_AGENT = "JobTrackerAgent/1.0 (+https://github.com)"

    @staticmethod
    def fetch_page(url: str, timeout: int = 12) -> str:
        headers = {"User-Agent": JobTrackerAgent.USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text

    @staticmethod
    def parse_job_page(html: str, url: str, refine: bool = True) -> JobRecord:
        """
        `refine=False` returns the scraped text as-is, skipping the two claude
        CLI subprocesses below (summary polish and company research). Callers
        adding one job interactively want them; a bulk backfill does not -- 118
        rows would be 236 CLI invocations, and the summaries would not match the
        raw HTML-stripped text every imported row already carries.
        """
        soup = BeautifulSoup(html, "html.parser")

        title = (soup.find("h1") or soup.find("title") or soup.find("h2") or soup.find("div", class_="job-title"))
        title_text = title.get_text(strip=True) if title else "(unknown title)"

        company = (soup.find("meta", property="og:site_name") or soup.find("div", class_="company") or soup.find("span", class_="company"))
        company_text = company["content"].strip() if company and company.has_attr("content") else (company.get_text(strip=True) if company else "(unknown company)")

        location = (soup.find("div", class_="location") or soup.find("span", class_="location") or soup.select_one("[itemprop=jobLocation]"))
        location_text = location.get_text(strip=True) if location else "(unknown location)"

        posted = (soup.find(string=lambda text: text and "Posted" in text) or soup.find("time") or soup.find("span", class_="date"))
        posted_text = posted.strip() if posted else "(unknown date)"

        # Improved summary extraction: target actual job posting content
        summary = ""

        def _extract_text_from_html(html_str: str) -> str:
            return BeautifulSoup(html_str, "html.parser").get_text(" ", strip=True)

        # Try JSON-LD structured data first (most reliable for job postings)
        json_ld = soup.find("script", type="application/ld+json")
        if json_ld:
            try:
                import json
                data = json.loads(json_ld.string)
                # Normalize: handle @graph array or direct object
                job_posting = None
                if isinstance(data, dict) and data.get("@graph"):
                    for item in data["@graph"]:
                        if item.get("@type") == "JobPosting":
                            job_posting = item
                            break
                elif isinstance(data, list):
                    for item in data:
                        if item.get("@type") == "JobPosting":
                            job_posting = item
                            break
                elif data.get("@type") == "JobPosting":
                    job_posting = data

                if job_posting:
                    desc = job_posting.get("description", "")
                    if desc:
                        summary = _extract_text_from_html(desc)

                    hiring_org = job_posting.get("hiringOrganization", {})
                    if isinstance(hiring_org, dict) and hiring_org.get("name"):
                        company_text = hiring_org["name"].strip()

                    job_loc = job_posting.get("jobLocation", {})
                    if isinstance(job_loc, dict):
                        addr = job_loc.get("address", {})
                        if isinstance(addr, dict):
                            city = addr.get("addressLocality", "")
                            region = addr.get("addressRegion", "")
                            country = addr.get("addressCountry", "")
                            parts = [p for p in [city, region, country] if p]
                            if parts:
                                location_text = ", ".join(parts)

                    date_posted = job_posting.get("datePosted", "")
                    if date_posted:
                        posted_text = date_posted
            except Exception:
                pass
        
        # Fallback: extract from main content areas
        if not summary or len(summary) < 300:
            key_parts = []
            
            # Find main job content container (often has job-specific classes)
            main_content = None
            for container_class in ["job-description", "job-details", "job-content", "main-content", "article-body", "description"]:
                main_content = soup.find(class_=container_class)
                if main_content:
                    break
            
            if not main_content:
                main_content = soup.find("main") or soup.find("article") or soup.find("div", class_="content")
            
            # Extract from main content
            if main_content:
                # Get all direct text content excluding nested lists/sidebars
                for elem in main_content.find_all(["p", "h2", "h3", "h4", "li"], recursive=False):
                    if elem.name in ["h2", "h3", "h4"]:
                        text = elem.get_text(" ", strip=True)
                        if text and any(kw in text.lower() for kw in ["role", "about", "need", "require", "skill", "benefit", "compens", "location"]):
                            key_parts.append("\n" + text)
                    elif elem.name == "li":
                        text = elem.get_text(" ", strip=True)
                        if text:
                            key_parts.append("• " + text)
                    elif elem.name == "p":
                        text = elem.get_text(" ", strip=True)
                        # Filter out generic page content
                        if text and len(text) > 30 and not any(skip in text.lower() for skip in ["tech scene", "venture capital", "forbes", "company page", "navigate to"]):
                            key_parts.append(text)
                
                # A container holding plain text (no <p>/<li> children) yielded
                # nothing at all before this — its own text is better than "".
                summary = " ".join(key_parts) if key_parts else main_content.get_text(" ", strip=True)
        
        # Clean up: remove excessive whitespace and HTML entities
        summary = " ".join(summary.split())
        summary = summary.replace("&nbsp;", " ").replace("&amp;", "&")

        # Limit raw summary before sending to LLM
        if summary and len(summary) > 20000:
            summary = summary[:20000] + "..."

        # Refine summary with Claude
        if summary and refine:
            summary = JobTrackerAgent.refine_summary(summary)

        # Research company for notes
        notes = ""
        if refine and company_text and company_text != "(unknown company)":
            print(f"Researching company: {company_text}...")
            notes = JobTrackerAgent.research_company(company_text)

        # Contacts are entered by hand (GUI / MCP), not looked up automatically.
        contacts = ""

        return JobRecord(
            url=url,
            title=title_text,
            company=company_text,
            location=location_text,
            posted_date=posted_text,
            summary=summary,
            notes=notes,
            contacts=contacts,
        )

    @staticmethod
    def refine_summary(raw: str) -> str:
        """Use the claude CLI to distill the raw job description into structured, fluff-free sections."""
        import subprocess
        prompt = (
            "You are a job description editor. Given the raw text of a job posting, "
            "extract and return only the following sections (skip any section with no relevant content):\n\n"
            "- **Company Context**: What the company does and its mission/stage\n"
            "- **Role & Responsibilities**: What the person will do day-to-day\n"
            "- **Required Skills & Experience**: Must-have qualifications and tech stack\n"
            "- **Compensation**: Salary range, equity, and any notable benefits\n\n"
            "Rules:\n"
            "- Remove all legal disclaimers, DEI boilerplate, E-Verify notices, and recruitment fraud warnings\n"
            "- Remove interview process descriptions\n"
            "- Be concise — use bullet points within each section\n"
            "- Do not add commentary or introductions\n\n"
            f"Raw job description:\n{raw}"
        )
        import shutil
        claude_bin = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
        # Build env without ANTHROPIC_API_KEY so claude CLI uses its own keychain auth
        cli_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        cli_env["PATH"] = f"{os.path.expanduser('~/.local/bin')}:{cli_env.get('PATH', '')}"
        result = subprocess.run(
            [claude_bin, "-p"],
            input=prompt,
            capture_output=True,
            text=True,
            env=cli_env,
        )
        if result.returncode != 0 or not result.stdout.strip():
            print(f"Warning: claude CLI failed (rc={result.returncode}, bin={claude_bin}): {result.stderr.strip()!r}")
            return raw
        return result.stdout.strip()

    @staticmethod
    def research_company(company: str) -> str:
        """Use the claude CLI with web search to gather company news, Glassdoor reviews, and funding."""
        import subprocess, shutil
        claude_bin = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
        prompt = (
            f"Research the company '{company}' and return a concise notes block with exactly these sections "
            f"(skip any section if no reliable info is found):\n\n"
            f"**Recent News** (last 12 months): 2–3 bullet points on notable events, launches, or controversies\n"
            f"**Glassdoor**: Overall rating (X/5), and 2–3 bullet points on top pros and cons from reviews\n"
            f"**Funding**: Latest round — stage, amount, date, and lead investors\n\n"
            f"Rules:\n"
            f"- Use web search to find current information\n"
            f"- Be factual and concise — no filler or commentary\n"
            f"- If a section has no reliable data, omit it entirely"
        )
        cli_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        cli_env["PATH"] = f"{os.path.expanduser('~/.local/bin')}:{cli_env.get('PATH', '')}"
        result = subprocess.run(
            [claude_bin, "-p", "--allowedTools", "WebSearch"],
            input=prompt,
            capture_output=True,
            text=True,
            env=cli_env,
        )
        if result.returncode != 0 or not result.stdout.strip():
            print(f"Warning: company research failed (rc={result.returncode}): {result.stderr.strip()!r}")
            return ""
        return result.stdout.strip()

    @staticmethod
    def detect_job_board(url: str) -> Optional[tuple]:
        """Return (board_type, api_url) if URL is a known job board API, else None."""
        # Greenhouse: job-boards.greenhouse.io/{company}/jobs/{id}
        #          or boards.greenhouse.io/{company}/jobs/{id}
        m = re.search(r'greenhouse\.io/([^/?#]+)/jobs/(\d+)', url)
        if m:
            company, job_id = m.group(1), m.group(2)
            return ('greenhouse', f'https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}')

        # Lever: jobs.lever.co/{company}/{uuid}
        m = re.search(r'jobs\.lever\.co/([^/?#]+)/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', url)
        if m:
            company, job_id = m.group(1), m.group(2)
            return ('lever', f'https://api.lever.co/v0/postings/{company}/{job_id}')

        return None

    @staticmethod
    def fetch_greenhouse_job(api_url: str, original_url: str) -> 'JobRecord':
        """Fetch job details from the Greenhouse boards API."""
        resp = requests.get(api_url, timeout=12)
        resp.raise_for_status()
        data = resp.json()

        title = data.get('title', '(unknown title)')
        location = (data.get('location') or {}).get('name', '(unknown location)')
        posted_date = data.get('updated_at', str(date.today()))[:10]

        # Strip HTML tags from content field
        content_html = data.get('content', '')
        summary = BeautifulSoup(content_html, 'html.parser').get_text(' ', strip=True) if content_html else ''

        # Derive company from URL slug (e.g. "justworks" → "Justworks")
        m = re.search(r'greenhouse\.io/([^/?#]+)/jobs/', original_url)
        company = m.group(1).replace('-', ' ').title() if m else '(unknown company)'

        return JobRecord(
            url=original_url,
            title=title,
            company=company,
            location=location,
            posted_date=posted_date,
            summary=summary,
        )

    @staticmethod
    def fetch_lever_job(api_url: str, original_url: str) -> 'JobRecord':
        """Fetch job details from the Lever postings API."""
        resp = requests.get(api_url, timeout=12)
        resp.raise_for_status()
        data = resp.json()

        title = data.get('text', '(unknown title)')
        categories = data.get('categories', {})
        location = categories.get('location', '(unknown location)') or '(unknown location)'

        created_at_ms = data.get('createdAt')
        if created_at_ms:
            posted_date = datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
        else:
            posted_date = str(date.today())

        summary = data.get('descriptionPlain', '')
        if not summary:
            summary = BeautifulSoup(data.get('description', ''), 'html.parser').get_text(' ', strip=True)

        m = re.search(r'jobs\.lever\.co/([^/?#]+)/', original_url)
        company = m.group(1).replace('-', ' ').title() if m else '(unknown company)'

        return JobRecord(
            url=original_url,
            title=title,
            company=company,
            location=location,
            posted_date=posted_date,
            summary=summary,
        )

    # Known job board domains — use company name lookup instead of domain lookup

    @staticmethod
    def sheet_client_from_service_account(json_keyfile: str, scopes: Optional[list] = None) -> gspread.Client:
        if scopes is None:
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
        creds = Credentials.from_service_account_file(json_keyfile, scopes=scopes)
        return gspread.authorize(creds)

    @classmethod
    def find_job_tracker_worksheet(
        cls,
        spread,
        table_name: Optional[str] = None,
        worksheet_name: str = "Sheet1",
    ):
        # try explicit table name first
        if table_name:
            try:
                return spread.worksheet(table_name)
            except WorksheetNotFound:
                pass

        # try direct worksheet names
        for candidate in [worksheet_name, "Sheet1", "job tracker", "Job Tracker"]:
            try:
                return spread.worksheet(candidate)
            except WorksheetNotFound:
                continue

        # try header-based detection
        for ws in spread.worksheets():
            headers = ws.row_values(1)
            if headers and "Job Title" in headers and ("Link" in headers or "Company" in headers):
                return ws

        # fallback: create a target sheet
        target = table_name or worksheet_name or "job tracker"
        sh = spread.add_worksheet(title=target, rows=200, cols=25)
        header = ["Company", "Job Title", "Job Summary", "Link", "Date Added", "Contacts", "Notes", "Outreach Date", "Date Applied"]
        sh.append_row(header, value_input_option="USER_ENTERED")
        return sh

    @classmethod
    def find_existing_row(cls, sh, url: str) -> Optional[int]:
        """Return 1-based row index of the existing URL, or None if not found.
        URL is in column D (index 3): A=Company, B=Job Title, C=Job Summary, D=Link.
        """
        try:
            all_values = sh.get_all_values()
            for i, row in enumerate(all_values[1:], start=2):  # i is 1-based row index
                if len(row) > 3 and row[3].strip() == url:
                    return i
        except Exception as e:
            print(f"Warning: could not check for duplicates: {e}")
        return None

    @classmethod
    def get_table_bounds(cls, spread, sh):
        """Get the bounds of the formatted table on the sheet, if any."""
        try:
            metadata = spread.fetch_sheet_metadata({
                'fields': 'sheets(data(rowData(values(userEnteredFormat))))',
                'includeGridData': True
            })
            # Tables in Google Sheets are indicated by formatted cells
            # For now, return None to use simple row-counting approach
        except:
            pass
        return None

    @classmethod
    def extend_table_range(cls, spread, sh, new_row_count):
        """Extend table range if needed when approaching capacity."""
        try:
            sheet_id = sh.properties['sheetId']
            current_grid = sh.properties.get('gridProperties', {})
            current_rows = current_grid.get('rowCount', 1000)
            
            # If we're using more than 80% of available rows, extend by 100 rows
            if new_row_count > (current_rows * 0.8):
                new_row_count = current_rows + 100
                spread.batch_update({
                    'requests': [
                        {
                            'updateSheetProperties': {
                                'fields': 'gridProperties.rowCount',
                                'properties': {
                                    'sheetId': sheet_id,
                                    'gridProperties': {
                                        'rowCount': new_row_count
                                    }
                                }
                            }
                        }
                    ]
                })
                print(f"Extended sheet to {new_row_count} rows")
        except Exception as e:
            print(f"Warning: could not extend table range: {e}")

    @classmethod
    def append_record_to_sheet(
        cls,
        record: JobRecord,
        spreadsheet: str,
        worksheet_name: str = "Sheet1",
        table_name: Optional[str] = None,
        service_account_json: Optional[str] = None,
    ) -> Dict:
        if service_account_json is None:
            service_account_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

        if not service_account_json:
            raise ValueError("Google service account JSON path is required via service_account_json or GOOGLE_APPLICATION_CREDENTIALS")

        client = cls.sheet_client_from_service_account(service_account_json)

        spreadsheet = spreadsheet.strip()
        if spreadsheet.startswith("http://") or spreadsheet.startswith("https://"):
            spread = client.open_by_url(spreadsheet)
        elif re.match(r"^[A-Za-z0-9-_]+$", spreadsheet):
            spread = client.open_by_key(spreadsheet)
        else:
            spread = client.open(spreadsheet)

        sh = cls.find_job_tracker_worksheet(spread, table_name=table_name, worksheet_name=worksheet_name)

        # Check for duplicate URL
        # Clean up posted_date: extract just the date if it's JSON or complex format
        posted_date = record.posted_date
        if posted_date.startswith("{"):
            try:
                import json
                data = json.loads(posted_date)
                if isinstance(data, dict) and "datePosted" in data:
                    posted_date = data["datePosted"]
                elif isinstance(data, dict) and "@graph" in data:
                    for item in data.get("@graph", []):
                        if "datePosted" in item:
                            posted_date = item["datePosted"]
                            break
                else:
                    posted_date = str(date.today())
            except Exception:
                posted_date = str(date.today())
        elif not posted_date or posted_date == "(unknown date)":
            posted_date = str(date.today())

        # Columns: Company, Job Title, Job Summary, Link, Date Added, Contacts, Notes, Outreach Date, Date Applied
        # A          B          C             D      E             F         G         H               I
        new_row = [
            record.company,
            record.title,
            record.summary,
            record.url,
            str(date.today()),  # Date Added — only written for new jobs
            record.contacts,
            record.notes,
            "",  # Outreach Date — always left blank
            "",  # Date Applied — always left blank
        ]

        existing_row = cls.find_existing_row(sh, record.url)
        if existing_row is not None:
            # Update A:C (company, title, summary) and F:G (contacts, notes)
            # Never touch D (Link), E (Date Added), H (Outreach Date), or I (Date Applied)
            sh.update(
                range_name=f"A{existing_row}:C{existing_row}",
                values=[[new_row[0], new_row[1], new_row[2]]],
                value_input_option="USER_ENTERED",
            )
            sh.update(
                range_name=f"F{existing_row}:G{existing_row}",
                values=[[new_row[5], new_row[6]]],
                value_input_option="USER_ENTERED",
            )
            print(f"Overwrote existing job at row {existing_row} (preserved Date Added & Date Applied).")
            return {"range": f"Sheet1!A{existing_row}", "status": "updated"}

        # Get all values to find table bounds
        all_values = sh.get_all_values()

        # Find next empty row after header row 1
        next_row_idx = 2
        for i in range(1, len(all_values)):
            if any(cell.strip() for cell in all_values[i][:3]):
                next_row_idx = i + 2
            else:
                break

        # Check if we need to extend the sheet
        cls.extend_table_range(spread, sh, next_row_idx + 1)

        # Insert at the next empty row within table bounds
        sh.insert_row(new_row, index=next_row_idx, value_input_option="USER_ENTERED")
        return {"range": f"Sheet1!A{next_row_idx}"}

    @classmethod
    def get_sheet_headers(cls, spreadsheet: str, worksheet_name: str = "Sheet1", service_account_json: Optional[str] = None) -> list:
        if service_account_json is None:
            service_account_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

        if not service_account_json:
            raise ValueError("Google service account JSON path is required via service_account_json or GOOGLE_APPLICATION_CREDENTIALS")

        client = cls.sheet_client_from_service_account(service_account_json)

        spreadsheet = spreadsheet.strip()
        if spreadsheet.startswith("http://") or spreadsheet.startswith("https://"):
            spread = client.open_by_url(spreadsheet)
        elif re.match(r"^[A-Za-z0-9-_]+$", spreadsheet):
            spread = client.open_by_key(spreadsheet)
        else:
            spread = client.open(spreadsheet)

        sh = spread.worksheet(worksheet_name)
        return sh.row_values(1)


# Defaults for quick testing. The spreadsheet resolves through config rather
# than a literal, so a fork cannot write into someone else's sheet; it is empty
# when none is configured, and --spreadsheet overrides it either way.
DEFAULT_JOB_URL = "https://example.com/job"
DEFAULT_SPREADSHEET = config.SPREADSHEET_URL
DEFAULT_WORKSHEET = config.SHEET_WORKSHEET


def run_agent(arguments: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="Job tracker agent: fetch job page and log it to Google Sheets")
    parser.add_argument("--url", default=os.getenv("JOB_TRACKER_URL", DEFAULT_JOB_URL), help="Job posting URL")
    parser.add_argument("--spreadsheet", default=os.getenv("JOB_TRACKER_SPREADSHEET", DEFAULT_SPREADSHEET), help="Google spreadsheet name, spreadsheet URL, or spreadsheet ID")
    parser.add_argument("--worksheet", default=os.getenv("JOB_TRACKER_WORKSHEET", DEFAULT_WORKSHEET), help="Worksheet tab name")
    parser.add_argument("--table-name", default=os.getenv("JOB_TRACKER_TABLE", "Sheet1"), help="Worksheet table name (e.g., 'job tracker')")
    parser.add_argument("--service-account-json", default=None, help="Path to Google service account JSON credentials")
    parser.add_argument("--text", default=None, help="Raw job description text (skips fetching the URL)")
    parser.add_argument("--title", default=None, help="Job title override")
    parser.add_argument("--company", default=None, help="Company name override")
    parser.add_argument("--location", default=None, help="Location override")

    args = parser.parse_args(arguments)

    if args.text:
        # Build record directly from provided text + overrides
        summary = JobTrackerAgent.refine_summary(args.text)
        company = args.company or "(unknown company)"
        notes = ""
        if company != "(unknown company)":
            print(f"Researching company: {company}...")
            notes = JobTrackerAgent.research_company(company)
        contacts = ""
        record = JobRecord(
            url=args.url,
            title=args.title or "(unknown title)",
            company=company,
            location=args.location or "(unknown location)",
            posted_date=str(date.today()),
            summary=summary,
            notes=notes,
            contacts=contacts,
        )
    else:
        board_info = JobTrackerAgent.detect_job_board(args.url)
        if board_info:
            board_type, api_url = board_info
            if board_type == 'greenhouse':
                record = JobTrackerAgent.fetch_greenhouse_job(api_url, args.url)
            elif board_type == 'lever':
                record = JobTrackerAgent.fetch_lever_job(api_url, args.url)
            else:
                html = JobTrackerAgent.fetch_page(args.url)
                record = JobTrackerAgent.parse_job_page(html, args.url)

            # For API-fetched records, run the same post-processing as parse_job_page
            if board_info:
                if record.summary:
                    record.summary = JobTrackerAgent.refine_summary(record.summary)
                if record.company and record.company != '(unknown company)':
                    print(f"Researching company: {record.company}...")
                    record.notes = JobTrackerAgent.research_company(record.company)
        else:
            html = JobTrackerAgent.fetch_page(args.url)
            record = JobTrackerAgent.parse_job_page(html, args.url)

        if args.title:
            record.title = args.title
        if args.company:
            record.company = args.company
        if args.location:
            record.location = args.location

    print("Parsed job record:")
    print(record)

    try:
        headers = JobTrackerAgent.get_sheet_headers(
            spreadsheet=args.spreadsheet,
            worksheet_name=args.worksheet,
            service_account_json=args.service_account_json,
        )
        print("Google Sheets headers:", headers)
    except Exception as exc:
        print("Warning: could not read sheet headers:", exc)

    result = JobTrackerAgent.append_record_to_sheet(
        record,
        spreadsheet=args.spreadsheet,
        worksheet_name=args.worksheet,
        table_name=args.table_name,
        service_account_json=args.service_account_json,
    )

    if result.get("status") == "duplicate":
        print("Job already exists in tracker. Skipping.")
    else:
        print(f"Appended to Google Sheets successfully at {result.get('range')}.")


if __name__ == "__main__":
    run_agent()
