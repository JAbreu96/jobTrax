"""
Pre-populated job tracker entry for:
  Founding Engineer — Healthcare AI Startup (via Reval Recruiting)

Run from the /agents directory:
  GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json python3 run_job_entry.py

Requirements: pip install gspread google-auth requests beautifulsoup4 python-dotenv
"""

import os
import sys

# ── Add src/ to path so we can import job_agent ──────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
sys.path.insert(0, os.path.dirname(__file__))
from job_agent import JobTrackerAgent, JobRecord
from src import config

# ── Pre-filled job data ───────────────────────────────────────────────────────

JOB_URL      = "https://www.reval.site/jobs/030a4814-c4de-41ee-a7b1-4cc6aad41fbd"
JOB_TITLE    = "Founding Engineer"
COMPANY      = "Healthcare AI Startup (via Reval Recruiting)"
LOCATION     = "New York, NY (Hybrid)"
SPREADSHEET  = config.SPREADSHEET_ID
WORKSHEET    = config.SHEET_WORKSHEET


RAW_SUMMARY = """
**Company Context**
- Early-stage healthcare AI startup (undisclosed name), posted via Reval Recruiting
- Building an agentic operating system for skilled nursing facilities (SNFs)
- ~$7M seed funding raised; pre-launch with ~$2M ARR in signed Letters of Intent (LOIs)
- Founding team: repeat operators with a prior successful exit
- Mission: reduce missed conditions, prevent re-hospitalizations, and surface care issues proactively for nurses in highly regulated SNF environments

**Role & Responsibilities**
- Build core backend systems powering an ambient AI scribe (audio capture → structured clinical notes)
- Develop automated workflows that surface issues, reduce missed conditions, and prevent re-hospitalizations
- Integrate transcription APIs, LLMs, and vocal biomarker capabilities for real-time clinical insight
- Design solutions tailored to nurses' day-to-day workflows within a highly regulated environment
- Set engineering standards and define foundational architecture as an early/first engineer

**Required Skills & Experience**
- Backend or full-stack engineer with end-to-end ownership, concept to production
- Highly autonomous with strong ownership mentality and bias toward shipping
- Deep technical fundamentals combined with modern AI tooling (LLMs, transcription APIs, applied ML)
- Motivated by real-world impact for seniors and caregivers

**Compensation**
- Salary: $165,000 – $210,000
- Equity: typical founding engineer equity expected at this stage (not specified)
- Hybrid work in New York, NY
"""

NOTES = """**Recent News**
- No public news available; company is pre-launch and has not disclosed its name
- Operating in the SNF ambient AI space alongside players like Abridge (250+ health systems), DeepScribe, and Andy AI (YC-backed, similar ambient documentation for home-visit nurses)
- ExaCare AI recently announced a 160-facility SNF partnership (Apr 2026) — adjacent validation of SNF AI demand

**Glassdoor**
- No Glassdoor listing found (pre-launch / undisclosed company)

**Funding**
- ~$7M seed round (per job posting); pre-launch stage
- Lead investor(s): not disclosed
- $2M ARR in signed LOIs indicates strong early commercial traction before product launch

**Sources**
- https://www.reval.site/jobs/030a4814-c4de-41ee-a7b1-4cc6aad41fbd
- https://www.businesswire.com/news/home/20260408179582/en/Creative-Solutions-in-Healthcare-Implements-AI-Across-160-Skilled-Nursing-Facilities-Transforming-Preadmission-Through-Partnership-with-ExaCare-AI
- https://www.ycombinator.com/companies/andy-ai/jobs/lrsiSTP-founding-engineer-healthcare-ai"""


def main():
    # Contacts are entered by hand, not looked up automatically.
    contacts = ""

    # ── Build the record ──────────────────────────────────────────────────────
    record = JobRecord(
        url=JOB_URL,
        title=JOB_TITLE,
        company=COMPANY,
        location=LOCATION,
        posted_date="2026-05-12",
        summary=RAW_SUMMARY.strip(),
        notes=NOTES.strip(),
        contacts=contacts,
    )

    print(f"\nJob record ready:")
    print(f"  Title   : {record.title}")
    print(f"  Company : {record.company}")
    print(f"  Location: {record.location}")
    print(f"  URL     : {record.url}")

    # ── Write to Google Sheets ────────────────────────────────────────────────
    sa_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not sa_json:
        print("\n⚠️  GOOGLE_APPLICATION_CREDENTIALS not set.")
        print("    Run: GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json python3 run_job_entry.py")
        sys.exit(1)

    print(f"\nWriting to spreadsheet {SPREADSHEET} → {WORKSHEET}...")
    result = JobTrackerAgent.append_record_to_sheet(
        record,
        spreadsheet=SPREADSHEET,
        worksheet_name=WORKSHEET,
        service_account_json=sa_json,
    )

    status = result.get("status", "added")
    row_ref = result.get("range", "unknown row")
    if status == "updated":
        print(f"✅ Duplicate found — updated existing entry at {row_ref} (Date Added preserved).")
    else:
        print(f"✅ Newly added to Google Sheet at {row_ref}.")


if __name__ == "__main__":
    main()
