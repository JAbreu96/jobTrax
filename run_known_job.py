"""
Pre-populated job tracker entry for:
  Software Engineer — Known

Run from the /agents directory:
  python3 run_known_job.py
"""

import os
import sys

# ── Add src/ to path so we can import job_agent ──────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
sys.path.insert(0, os.path.dirname(__file__))
from job_agent import JobTrackerAgent, JobRecord
from src import config

# ── Pre-filled job data ───────────────────────────────────────────────────────

JOB_URL      = "https://job-boards.greenhouse.io/known/jobs/8515531002"
JOB_TITLE    = "Software Engineer"
COMPANY      = "Known"
LOCATION     = "Remote"
SPREADSHEET  = config.SPREADSHEET_ID
WORKSHEET    = config.SHEET_WORKSHEET


RAW_SUMMARY = """**Company Context**
- Modern marketing company (~200+ people), pairs PhD data scientists with award-winning creatives, strategists, engineers, and expert research teams
- Ad Age #3 on The A-List (2025, top agencies worldwide); Data & Insights Agency of Year for 3rd consecutive year
- Proprietary tech platform "Skeptic" uses ML and AI to predict and optimize campaigns
- Revenue $132M in 2023 (6% gain); more than doubled revenue in past 4 years
- Clients span finance, technology, entertainment, media, CPG, and real estate
- Awards: Emmys, Clios, Effies, Cannes Lions, ProMax Agency of the Year, Digiday's Most Innovative Media Agency

**Role & Responsibilities**
- Design and build full-stack web applications in Python
- Create performant Web APIs with FastAPI
- Implement agentic AI systems using latest LLM orchestration frameworks to automate complex workflows and enhance products
- Integrate with industry-standard datastores: PostgreSQL and Snowflake
- Design asynchronous and event-driven services
- Produce robust ETL pipelines with Argo Workflows
- Deploy applications across multiple environments using Docker, Helm, and Kubernetes
- Work closely with data scientists and product managers across marketing and advertising (TV and digital)
- Play an active role in designing and building new, cutting-edge products
- May contribute to open source (e.g., pytest-mock-resources, an in-house custom plugin)
- Will use Terraform for infrastructure management
- Write TypeScript and Vue for frontend UIs

**Required Skills & Experience**
- 1-2+ years of professional experience building and maintaining production applications in Python
- Deep understanding of Python as a language
- Strong communication and teamwork skills

**Bonus**
- Experience with SQL and relational databases; SQLAlchemy is a plus
- Docker and Kubernetes experience is a plus
- ETL or message-oriented architectures experience is a plus
- UI frameworks (Vue or React) experience is a plus

**Compensation**
- Base salary: $100K–$130K
- Unlimited paid time off
- 401k with company matching, no vesting period
- Annual bonuses
- Generous medical plan
- Paid parental leave"""

NOTES = """**Recent News**
- Named #6 on Ad Age 2025 Agency A-List (2nd straight year in top 10); Data & Insights Agency of Year for 3rd consecutive year (Ad Age)
- Revenue $132M in 2023 (6% gain); doubled revenue in past 4 years with consistent new client wins including Shake Shack, AMC Networks, YES Network
- Proprietary AI platform "Skeptic" underpins all media, creative, and strategy work; PhD data science team uncovers hundreds of millions in client savings

**Glassdoor**
- 3/5 stars (114 reviews); 40% would recommend to a friend
- Pros: Unlimited PTO, competitive salary, innovative award-winning work, strong clients
- Cons: Annual layoffs reported, high turnover, junior employees reportedly overworked

**Funding**
- Privately held; no public funding rounds disclosed

**Sources**
- https://adage.com/article/special-report-agency-list-creativity-awards/known-best-agencies-2025/2604001/
- https://adage.com/article/special-report-agency-list-creativity-awards/best-agencies-2024-known/2543431/
- https://www.glassdoor.com/Reviews/Known-Reviews-E458292_P3.htm"""

CONTACTS = """Ross Martin — President — rossm@known.is (98% confidence)
Sara Cahill — General Manager — sarac@known.is (99% confidence)
Jillian Dooley — Senior Director — jilliand@known.is (99% confidence)
Trevor Casey — Director of Paid Search — trevorc@known.is (99% confidence)
Chico Yu — Programmatic Director — chicoy@known.is (99% confidence)"""


def main():
    from dotenv import load_dotenv
    load_dotenv()

    record = JobRecord(
        url=JOB_URL,
        title=JOB_TITLE,
        company=COMPANY,
        location=LOCATION,
        posted_date="2026-05-13",
        summary=RAW_SUMMARY.strip(),
        notes=NOTES.strip(),
        contacts=CONTACTS.strip(),
    )

    print(f"\nJob record ready:")
    print(f"  Title   : {record.title}")
    print(f"  Company : {record.company}")
    print(f"  Location: {record.location}")
    print(f"  URL     : {record.url}")

    sa_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not sa_json:
        print("\n⚠️  GOOGLE_APPLICATION_CREDENTIALS not set.")
        print("    Set it in .env or run: GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json python3 run_known_job.py")
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
