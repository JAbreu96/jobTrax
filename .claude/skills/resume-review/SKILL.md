---
name: resume-review
description: Analyze a resume against a job description like a senior recruiter. Gives a match score, top missing keywords, red flags, rewrites the experience section using the Accomplished X / measured by Y / by doing Z formula, then runs an ATS + hiring manager scan. Use when the user provides a job URL or pastes a job description.
argument-hint: "[job_url or company_name (optional)]"
---

Analyze the user's resume against a job description using the arguments: `$ARGUMENTS`

## Step 0 — Load the profile

Read `config/profile.md`. Every `{placeholder}` below is a key in its front
matter.

If that file does not exist, stop and tell the user to run
`cp config/profile.example.md config/profile.md` and fill it in. Do not guess a
name, address or document ID — a wrong address here sends real mail to a
stranger.

## Base Resume (Google Doc)

- **Google Doc ID:** `{resume_doc_id}`
- **Google Drive Resumes Folder ID:** `{resume_folder_id}`
- **Service Account:** path set via `GOOGLE_APPLICATION_CREDENTIALS` env var
- **Link:** https://docs.google.com/document/d/{resume_doc_id}/edit

**Read the live resume at the start using the Docs API:**

```python
from googleapiclient.discovery import build
from google.oauth2 import service_account

import sys; sys.path.insert(0, ".")
from src import config

DOC_ID = config.require("RESUME_DOC_ID")  # from config/profile.md
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=["https://www.googleapis.com/auth/documents.readonly"]
)
docs = build("docs", "v1", credentials=creds)
doc = docs.documents().get(documentId=DOC_ID).execute()

# Extract plain text from all paragraph elements
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

Use the output of this script as the resume content for the analysis. If the script fails, fall back to the `mcp__claude_ai_Google_Drive__read_file_content` tool with fileId `{resume_doc_id}`.

---

## Step 1 — Get the job description

If a job_url was provided:
- If it's a Greenhouse URL (`greenhouse.io/{company}/jobs/{id}`): fetch `https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{id}` and extract the `content` field (strip HTML).
- If it's a Lever URL (`jobs.lever.co/{company}/{uuid}`): fetch `https://api.lever.co/v0/postings/{company}/{uuid}` and extract `descriptionPlain`.
- If it's a LinkedIn URL or any URL that fails to fetch: ask the user to paste the job description.
- Otherwise: use WebFetch to retrieve the page content.

If no URL was provided and no description is available: ask the user to paste the job description before continuing.

---

## Step 2 — Recruiter analysis (match score + gaps)

Act as a **senior recruiter** for the exact company and role.

Analyze the resume against the job description and return:

**Match Score: X/100**

Brief 1–2 sentence rationale for the score.

**Top 5 Missing Keywords**
List the 5 most important keywords or skills from the job description that are absent or weak in the resume. For each, note where it could naturally be added.

**3 Red Flags a Hiring Manager Would Spot in Under 10 Seconds**
Be blunt. What would make a recruiter pause or skip this resume for this specific role?

---

## Step 3 — Rewrite the experience section

Rewrite the user's experience section to:
- Apply the **result-first formula** to every bullet: _[Impact verb] [X] as measured by [Y], by doing [Z]_ — lead with the impact, quantify it, then explain the action. Vary the opening verb naturally (Drove, Delivered, Reduced, Cut, Grew, Shipped, Improved, Eliminated, Accelerated, Established, Aligned, etc.) — never start multiple bullets with the same word, and never use "Accomplished" as a default opener
- Naturally incorporate the missing keywords from Step 2 **only where they genuinely apply** — if a keyword can't be tied to real work in the base resume, flag it as a gap instead of forcing it
- Address the red flags identified in Step 2 through honest reframing, not fabrication
- Maintain the same company names, titles, and date ranges

**Strict accuracy rules — no exceptions:**
- **Never invent metrics.** Every number (%, count, time saved) must come directly from the base resume. Do not estimate, round up, or add new figures.
- **Never invent responsibilities.** Only reframe what actually happened. If the base resume says "built a dashboard," you may call it a "real-time monitoring dashboard" if that's accurate — but you cannot add "built an anomaly detection pipeline" if it isn't there.
- **Never add technologies not in the base resume.** If the JD wants Snowflake/dbt and those aren't in the resume, note the gap in Step 2 — do not insert them into bullets.
- **Reframing is allowed; fabrication is not.** You may recontextualize work using industry vocabulary (e.g. "data export" → "policy enforcement reporting") as long as the underlying activity is the same. If the reframe materially misrepresents what was built, don't use it.
- When in doubt, keep the original phrasing and focus rewriting energy on structure and impact clarity.

Return the full rewritten experience section, formatted cleanly. For any missing keyword that could not be honestly incorporated, add a note at the bottom: `⚠️ Could not add: [keyword] — not present in base resume.`

---

## Step 4 — ATS + hiring manager scan

Now act as both:
1. An **ATS filter** scanning for keyword density and formatting issues
2. A **hiring manager** reading 200 resumes in one sitting

Using the rewritten experience section from Step 3:

**Sections That Would Get Skipped**
List any bullets or section that are weak, vague, or would get skimmed past — and why.

**Rewrites to Stop the Scroll**
For each flagged section, provide a sharper version that earns attention. Lead with impact, be specific, cut filler.

---

## Step 5 — Final summary

Wrap up with:
- Revised match score after the rewrites (X/100)
- 2–3 sentences on the strongest angle to emphasize when applying to this specific role

---

## Step 6 — Create a tailored resume copy in Google Drive

### 1-page rule
The final resume **must fit on one page — use as much of that page as possible**. Target **380–450 words** of body content (excluding header and section labels). Every experience section must have **at least 3 bullets**.

**Bullet targets per section:**
- Meta: 5 bullets (trim to 4 only if still over limit after tightening wording)
- Razortooth: 3 bullets
- Strategio: 3 bullets

**If over 450 words:**
- First trim any bullet over 40 words — cut filler, preserve the metric
- Then remove the lowest-impact bullet from Meta only (never drop below 3 bullets per section)
- Use `deleteContentRange` — never `replaceAllText` with empty string (leaves stranded empty paragraphs). Always delete from **highest index to lowest** to avoid index shifting:
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

**If under 380 words:**
- Add back a previously trimmed bullet, prioritizing the most role-relevant one
- Use `insertText` to insert at the right position, then `createParagraphBullets` to apply list formatting
- Process insertions from **highest index to lowest** in the batchUpdate so earlier inserts don't shift subsequent positions
- **After inserting**, always explicitly remove bold from the inserted range using `updateTextStyle` with `bold: false` — inserted text can inherit bold formatting from surrounding content:
  ```python
  requests_unbold = [
      {
          "updateTextStyle": {
              "range": {"startIndex": insert_index, "endIndex": insert_index + len(bullet_text) + 1},
              "textStyle": {"bold": False},
              "fields": "bold"
          }
      }
  ]
  docs.documents().batchUpdate(documentId=COPY_DOC_ID, body={"requests": requests_unbold}).execute()
  ```

After applying all changes, verify word count by re-reading the doc. Report the final word count alongside the result link.

---

1. **Extract the company name** from the job description (e.g. "Zoox", "Sesame", "Microsoft").

2. **Copy the base Google Doc** using `mcp__claude_ai_Google_Drive__copy_file`:
   - `fileId`: `{resume_doc_id}`
   - `parentId`: `{resume_folder_id}`
   - `title`: `{owner_name} — Resume — {Company}`
   - Save the returned file ID as `COPY_DOC_ID`

3. **Apply the rewritten bullets to the copy** using the Docs API. For each bullet that changed between the original and the rewrite, issue a `replaceAllText` request:

```python
import warnings
warnings.filterwarnings("ignore")

from googleapiclient.discovery import build
from google.oauth2 import service_account

COPY_DOC_ID = "{COPY_DOC_ID}"  # from step 2
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=["https://www.googleapis.com/auth/documents"]
)
docs = build("docs", "v1", credentials=creds)

# List of (original_text, rewritten_text) pairs — only bullets that changed
replacements = [
    ("ORIGINAL BULLET TEXT", "REWRITTEN BULLET TEXT"),
    # ... one entry per changed bullet
]

requests = [
    {
        "replaceAllText": {
            "containsText": {"text": old, "matchCase": True},
            "replaceText": new
        }
    }
    for old, new in replacements
]

result = docs.documents().batchUpdate(
    documentId=COPY_DOC_ID,
    body={"requests": requests}
).execute()

for reply, (old, _) in zip(result.get("replies", []), replacements):
    count = reply.get("replaceAllText", {}).get("occurrencesChanged", 0)
    status = "✅" if count > 0 else "⚠️  0 matches"
    print(f"{status} {old[:60]}...")
```

   **Important:** Only replace bullets that genuinely changed. Do not replace bullets that stayed the same — this preserves all original formatting, fonts, and styling in the copy.

   Share the service account with the new doc if needed — it inherits permissions from the copied doc automatically since it already has access to the base.

4. **Fix bold formatting** — after applying rewrites, run the following to enforce tasteful bolding. Rules:
   - **Bold**: name, section headers (`TECHNICAL SKILLS`, `WORK EXPERIENCE`, `EDUCATION`), skill category labels (`Proficient:`, `Exposure:`), company names only
   - **Not bold**: contact line, job titles, locations, dates, bullet text, education degree/school
   - Leave all other formatting untouched

```python
import warnings
warnings.filterwarnings("ignore")

from googleapiclient.discovery import build
from google.oauth2 import service_account

COPY_DOC_ID = "{COPY_DOC_ID}"
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=["https://www.googleapis.com/auth/documents"]
)
docs = build("docs", "v1", credentials=creds)
doc = docs.documents().get(documentId=DOC_ID).execute()

requests = []
for el in doc.get("body", {}).get("content", []):
    if "paragraph" not in el:
        continue
    para = el["paragraph"]
    for r in para.get("elements", []):
        tr = r.get("textRun", {})
        content = tr.get("content", "")
        is_bold = tr.get("textStyle", {}).get("bold", False)
        si = r.get("startIndex", 0)
        ei = r.get("endIndex", 0)

        # Remove bold from job title/location (starts with "|" in job header lines)
        if is_bold and content.strip().startswith("|") and "Software Engineer" in content:
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": si, "endIndex": ei},
                    "textStyle": {"bold": False},
                    "fields": "bold"
                }
            })

        # Remove bold from education degree/school if bolded
        if is_bold and any(x in content for x in ["B.A.", "B.S.", "Bachelor", "Forensic", "Computer Science"]):
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": si, "endIndex": ei},
                    "textStyle": {"bold": False},
                    "fields": "bold"
                }
            })

if requests:
    docs.documents().batchUpdate(documentId=COPY_DOC_ID, body={"requests": requests}).execute()
    print(f"✅ Bold formatting fixed ({len(requests)} changes)")
else:
    print("✅ Bold formatting already clean")
```

5. **Verify word count and report the result:**

   Re-read the doc and count words. Then report:

   > 📄 **[{owner_name} — Resume — {Company}]({viewUrl})**
   > {word_count} words · All rewrites applied · Bold formatting cleaned up

6. **Download the resume as PDF:**

   Export the Google Doc as a PDF and save it locally:

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

   print(f"✅ Saved to {filepath}")
   ```

   Append the local path to the result report:
   > 💾 Saved to `~/Documents/resumes/{owner_name} — Resume — {Company}.pdf`
