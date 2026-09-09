---
name: job-tracker
description: Track a job posting — fetch a job URL, extract job details (title, company, location, summary), and log it to the local job tracker DB. Use when the user provides a job posting URL and wants to save it to their tracker.
argument-hint: [job-posting-url]
---

Track the job posting at `$ARGUMENTS` by following these steps:

---

## Step 0 — Load the profile

Read `config/profile.md`. Every `{placeholder}` below is a key in its front
matter.

If that file does not exist, stop and tell the user to run
`cp config/profile.example.md config/profile.md` and fill it in. Do not guess a
name, address or document ID — a wrong address here sends real mail to a
stranger.

## Step 1 — Fetch the job posting

If no URL was given, ask for one before continuing.

**If the URL contains `linkedin.com`, `indeed.com`, or `glassdoor.com`:** STOP — do not attempt to fetch, scrape, or use Playwright on these URLs under any circumstances. Their ToS explicitly prohibit automated access. Ask the user to provide manually:
- Job title
- Company name
- Location
- Job description (full text)

Wait for their response, then skip to Step 2 with that data. The Playwright fallback below does NOT apply to these domains.

**If the URL matches Greenhouse** (`greenhouse.io/{company}/jobs/{id}`):
Fetch from the Greenhouse API instead of the page:
```
https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{id}
```
Extract `title`, `location.name`, `updated_at` (date), and `content` (HTML — strip tags for summary). Derive the company name from the URL slug (e.g. `justworks` → `Justworks`).

**If the URL matches Lever** (`jobs.lever.co/{company}/{uuid}`):
Fetch from the Lever API:
```
https://api.lever.co/v0/postings/{company}/{uuid}
```
Extract `text` (title), `categories.location`, `createdAt` (ms timestamp → YYYY-MM-DD), and `descriptionPlain` (or `description` stripped of HTML).

**Otherwise:** Fetch the page using WebFetch. Extract the job description from JSON-LD `application/ld+json` structured data if present (`description`, `hiringOrganization.name`, `jobLocation.address`, `datePosted`). Fall back to `<h1>` for title and main content areas for description.

**If WebFetch returns fewer than 200 characters of meaningful content** (e.g. Ashby, Rippling, Workday, or any JS-rendered page), fall back to Playwright via Bash. **Never use this for `linkedin.com`, `indeed.com`, or `glassdoor.com` — always ask the user instead.**

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("{URL}", wait_until="networkidle", timeout=15000)
    try:
        page.wait_for_selector("h1", timeout=8000)
    except:
        pass
    text = page.inner_text("body")
    browser.close()

print(text)
```

Use the full `text` output as the raw content for Step 2 extraction. Save the complete, unedited raw content (whatever was fetched — API response text, WebFetch output, or Playwright `text`) as `RAW_JOB_DESCRIPTION` — it gets appended in full to the tracker notes in Step 5, so nothing gets lost to summarization.

---

## Step 2 — Extract and refine job details

From the fetched content, extract:
- **Job title** — main heading or page title
- **Company** — from structured data, headings, or URL slug
- **Location** — city/state/remote, or "(unknown location)"
- **Summary** — preserve as much meaningful content as possible from the raw description, organized into these sections (skip any with no content):
  - **Company Context**: what the company does, mission, scale, stage, culture — include specific metrics, customer counts, growth stats, or notable customers if mentioned
  - **Role & Responsibilities**: full list of day-to-day responsibilities — do not condense or merge bullets, keep all specifics
  - **Required Skills & Experience**: all must-have qualifications, full tech stack with versions/frameworks, years of experience, degree requirements
  - **Bonus** (optional): all nice-to-haves, preferred qualifications
  - **Compensation**: salary range, equity details, every listed benefit and perk
  - **What to remove**: legal disclaimers, DEI/EEO boilerplate, E-Verify notices, recruitment fraud warnings, interview process descriptions, and generic filler phrases ("we are an equal opportunity employer", "join our team", etc.)
  - Use bullet points. Preserve specific numbers, names, and technical terms exactly as written.
  - Target up to **20,000 characters** — do not truncate content that fits within this limit.

If the extracted content is too short (under 100 chars), ask the user to paste the job description before continuing.

---

## Step 3 — Research the company

Use WebSearch to find current information on the company. Return a structured notes block with:

**Recent News** (last 12 months): 2–3 bullet points on notable events, launches, or controversies
**Glassdoor**: Overall rating (X/5), 2–3 bullet points on top pros and cons
**Funding**: Latest round — stage, amount, date, lead investors

Omit any section where no reliable data is found. Be factual and concise. End the block with a **Sources** list of URLs used.

---

## Step 4 — Resume match score

Read the base resume from the Google Docs API, then score it against this job description.

```python
import warnings
warnings.filterwarnings("ignore")

from googleapiclient.discovery import build
from google.oauth2 import service_account

DOC_ID = "{resume_doc_id}"
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=["https://www.googleapis.com/auth/documents.readonly"]
)
docs = build("docs", "v1", credentials=creds)
doc = docs.documents().get(documentId=DOC_ID).execute()

lines = []
for el in doc.get("body", {}).get("content", []):
    if "paragraph" in el:
        text = "".join(
            r.get("textRun", {}).get("content", "")
            for r in el["paragraph"].get("elements", [])
        ).strip()
        if text:
            lines.append(text)

resume_text = "\n".join(lines)
print(resume_text)
```

If the script fails, fall back to `mcp__claude_ai_Google_Drive__read_file_content` with fileId `{resume_doc_id}`.

Using the resume text and the job description from Step 2, produce a **lightweight match assessment**:

- **Match Score: X/100** — one sentence rationale
- **Top 3 Gaps** — the 3 most important missing keywords or skills

Format this as a 3-line block that will be prepended to the Notes column:
```
Match Score: X/100 — [one-sentence rationale]
Gaps: [gap1], [gap2], [gap3]

```
(Leave a blank line after the gaps so the research notes from Step 3 are visually separated.)

Save this as `MATCH_BLOCK` — it will be included in the tracker notes in Step 5.

### Threshold gate

**If the match score is below 65/100**, stop here and do NOT proceed to Steps 5–8.

Instead, report:

> ⚠️ **Match score too low to track ({score}/100)**
> **{Job Title} — {Company}**
> Gaps: {gap1}, {gap2}, {gap3}
>
> This job fell below the 65/100 tracking threshold. Add it anyway?

Wait for the user to confirm before continuing. If they confirm, proceed to Step 5. If they decline or don't respond, stop.

**Exception — always flag, never auto-skip:**
If a hard location mismatch is detected (role requires relocation to another country, or is international with no remote option), add a 🌍 flag to the report above regardless of score:
> 🌍 **Location note:** This role is based in {city/country} — outside the US or requires relocation.

---

## Step 5 — Add to the tracker

Call `mcp__job_tracker__add_job` with:
- `company`, `title`, `link`, `location` — from Step 2
- `summary` — the full Step 2 summary
- `notes` — `MATCH_BLOCK` (Step 4) combined with the research notes from Step 3 and the full raw job description from Step 1, in that order:
  ```
  Match Score: X/100 — [rationale]
  Gaps: [gap1], [gap2], [gap3]

  [Research notes from Step 3]

  ====

  [RAW_JOB_DESCRIPTION from Step 1 — the complete, unedited posting text]
  ```
- `status`: `Tracking`

The tool handles duplicate detection itself (matches on `link`): if a job with the same link already exists, it updates that entry in place (preserving its original `date_added`, `outreach_date`, `date_applied`, and `status`) instead of creating a new row. Use the tool's `updated` field in its response to know which happened — report it accordingly in Step 6.

Note: entries are keyed by `(company, date_added, position_title, link)`, so distinct postings — including several requisitions a company lists under one title — each get their own row. Re-adding the same posting URL overwrites in place.

---

## Step 6 — Report result

State:
- Job title and company
- Whether it was **newly added** or **updated** (duplicate link, per Step 5's `updated` field)
- Match score and top 3 gaps from Step 4

---

## Step 7 — Offer tailored resume (if good fit)

If the match score from Step 4 is **65/100 or above**, ask the user:

> Would you like me to create a tailored resume for **{Company}**?

Wait for their response. If they say yes, create a tailored resume copy by running the full resume-review skill pipeline (Steps 2–6 of the resume-review skill) using:
- The job description already fetched in Step 1
- The resume already read in Step 4
- Company name extracted from Step 2

If they say no (or don't respond), stop here.

Follow the resume-review skill exactly:
1. Run recruiter analysis (match score + gaps) — you already have this from Step 4, so skip to rewrites
2. Rewrite the experience section (XYZ formula, incorporate missing keywords honestly)
3. ATS + hiring manager scan
4. Final summary with revised score
5. Create Google Drive copy:
   - Copy base doc using `mcp__claude_ai_Google_Drive__copy_file` with:
     - `fileId`: `{resume_doc_id}`
     - `title`: `{owner_name} — Resume — {Company}`
     - `parentId`: `{resume_folder_id}`
   - Save the returned file ID as `COPY_DOC_ID`
   - Apply rewritten bullets via `replaceAllText`
   - Delete excess Meta bullets (keep 5, or 4 only if over 450 words) using `deleteContentRange` — never `replaceAllText` with empty string (leaves stranded empty paragraphs). Use this pattern:
     ```python
     # Re-read doc to get current indices after replaceAllText
     doc = docs.documents().get(documentId=COPY_DOC_ID).execute()

     bullets_to_remove = [
         "FULL TEXT OF BULLET TO DELETE",
         # one entry per bullet to remove
     ]

     ranges_to_delete = []
     for el in doc.get("body", {}).get("content", []):
         if "paragraph" not in el:
             continue
         text = "".join(
             r.get("textRun", {}).get("content", "")
             for r in el["paragraph"].get("elements", [])
         ).strip()
         if any(target in text for target in bullets_to_remove):
             ranges_to_delete.append((el["startIndex"], el["endIndex"]))

     # Must process highest index first to avoid index shifting
     ranges_to_delete.sort(key=lambda x: x[0], reverse=True)

     requests = [
         {"deleteContentRange": {"range": {"startIndex": s, "endIndex": e}}}
         for s, e in ranges_to_delete
     ]
     docs.documents().batchUpdate(documentId=COPY_DOC_ID, body={"requests": requests}).execute()
     print(f"Deleted {len(requests)} bullets")
     ```
   - Verify word count is 380–450; insert/delete bullets as needed
   - **After any `insertText`, always call `updateTextStyle` with `bold: false` on the inserted range to prevent inherited bold formatting**
   - Report the final doc link and word count
6. Download the resume as PDF and save locally:
   ```python
   import warnings
   warnings.filterwarnings("ignore")
   from googleapiclient.discovery import build
   from google.oauth2 import service_account
   import os

   COPY_DOC_ID = "{COPY_DOC_ID}"
   SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
   COMPANY = "{Company}"
   OUTPUT_DIR = os.path.expanduser("~/Documents/resumes")
   os.makedirs(OUTPUT_DIR, exist_ok=True)

   creds = service_account.Credentials.from_service_account_file(
       SERVICE_ACCOUNT_FILE,
       scopes=["https://www.googleapis.com/auth/drive.readonly"]
   )
   drive = build("drive", "v3", credentials=creds)

   content = drive.files().export(
       fileId=COPY_DOC_ID,
       mimeType="application/pdf"
   ).execute()

   filename = f"{owner_name} — Resume — {COMPANY}.pdf"
   filepath = os.path.join(OUTPUT_DIR, filename)
   with open(filepath, "wb") as f:
       f.write(content)

   print(f"Saved to {filepath}")
   ```
   Append to the result report:
   > 💾 Saved to `~/Documents/resumes/{owner_name} — Resume — {Company}.pdf`

If the match score is **below 65**, skip this step entirely.
