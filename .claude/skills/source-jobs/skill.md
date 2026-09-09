---
name: source-jobs
description: Run Google X-ray searches across Ashby, Greenhouse, Lever, and Notion to find job postings, fetch each one, score them against the resume, and return a ranked list for review. Does NOT auto-track — user decides which jobs to send to /job-tracker.
argument-hint: "[role keywords] [location (optional)]"
---

Find and score job postings using Google X-ray search. Arguments: `$ARGUMENTS`

Parse the arguments:
- **role** — what to search for (e.g. "software engineer AI React", "frontend engineer TypeScript")
- **location** — optional filter (e.g. "New York", "remote", "San Francisco"). If omitted, search broadly.

## Step 0 — Load the profile

Read `config/profile.md`. Every `{placeholder}` below is a key in its front
matter.

If that file does not exist, stop and tell the user to run
`cp config/profile.example.md config/profile.md` and fill it in. Do not guess a
name, address or document ID — a wrong address here sends real mail to a
stranger.

## Candidate profile (for scoring)

Use the profile's `## Candidate profile (for scoring)` section — stack, years of
experience, strengths, location. Score against what it says, not against what
the role sounds like it wants.

The rules below stay here rather than in the profile: they are this skill's
policy on how to weigh a mismatch, not a fact about the candidate.

### Experience-level scoring rules
Apply these adjustments **before** finalizing any match score:

- **Ideal range:** roles asking for 0–3 years → no penalty
- **Slight stretch:** roles asking for 3–5 years → subtract 8 points and note "experience stretch"
- **Too senior:** roles explicitly titled Senior, Staff, Principal, Lead, or requiring 5+ years → subtract 15 points and flag `⚠️ senior role`
- **New grad / intern:** roles requiring current enrollment in a degree program → subtract 20 points and flag `⚠️ eligibility concern`

Do NOT filter out senior roles entirely — just score them honestly so the user can decide.

---

## Step 1 — Read the resume

Use `mcp__claude_ai_Google_Drive__read_file_content` with fileId `{resume_doc_id}` to get the full resume text.

Save this as `RESUME_TEXT` — used for scoring all jobs in Step 4.

---

## Step 2 — Run X-ray searches

Run the following searches using `WebSearch`. Construct the query from the parsed role and location arguments.

Run all four in parallel:

**Greenhouse:**
```
site:boards.greenhouse.io "{role}" {location}
```

**Ashby:**
```
site:jobs.ashbyhq.com "{role}" {location}
```

**Lever:**
```
site:jobs.lever.co "{role}" {location}
```

**Notion:**
```
site:notion.so "we're hiring" "{role}" {location}
```

From each search result, collect all URLs that match the ATS pattern:
- Greenhouse: `boards.greenhouse.io/{company}/jobs/{id}`
- Ashby: `jobs.ashbyhq.com/{company}/{uuid}`
- Lever: `jobs.lever.co/{company}/{uuid}`
- Notion: any notion.so URL with job content

Deduplicate across all four searches. Aim for up to **10 unique job URLs** total. Prioritize results where the URL + title snippet look most relevant to the role searched.

---

## Step 3 — Cross-reference against the job tracker

Before fetching, filter out postings already in the tracker so effort isn't wasted re-surfacing jobs the user has already seen.

Call `mcp__job_tracker__list_all_jobs`. The result is usually too large for context — if it exceeds the token limit, the tool saves it to a file and returns the path. In that case, extract just `company` and `link` with `jq` via Bash rather than reading the full file:

```bash
jq -r '.result[] | [.company, .link] | @tsv' "{saved_file_path}"
```

Against this existing list, apply two checks to the URLs collected in Step 2:

- **Exact link match** → drop the URL entirely from this run's candidate pool. It's already tracked; don't re-fetch or re-present it.
- **Same company, different link** → keep it (it may be a distinct role), but annotate it later in Step 6 with a note, e.g. `↺ already have a tracked role at this company ({status})`.

Do this before Step 4 so fetch effort (Greenhouse/Lever/Ashby API calls, WebFetch) is only spent on genuinely new postings.

---

## Step 4 — Fetch each job description

For each URL collected, fetch the job description using the appropriate method:

**Greenhouse** (`boards.greenhouse.io/{company}/jobs/{id}`):
Call the Greenhouse API:
```
https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{id}
```
Extract: `title`, `location.name`, `content` (strip HTML tags), and `updated_at` (ISO 8601 — treat as the posted date, this is the field Greenhouse actually keeps fresh).

**Lever** (`jobs.lever.co/{company}/{uuid}`):
Call the Lever API:
```
https://api.lever.co/v0/postings/{company}/{uuid}
```
Extract: `text` (title), `categories.location`, `descriptionPlain`, and `createdAt` (epoch milliseconds — convert to a date for the recency check).

**Ashby** (`jobs.ashbyhq.com/{company}/{uuid}`):
Call the public Ashby job board API for the company, then find the matching posting by `{uuid}`:
```
https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true
```
The response is `{ "jobs": [ ... ] }`. Match the entry whose `jobUrl` contains `{uuid}` (or whose `id` equals `{uuid}`). Extract: `title`, `location`, `descriptionPlain` (strip any residual HTML), and `publishedAt` (ISO 8601 — the recency check field; NOT `publishedDate`, which doesn't exist on this response).

If the company slug from the job URL 404s, retry with the URL-decoded form (e.g. a slug containing `%20` may need to be passed through literally rather than decoded to a space, or vice versa — Ashby org slugs are inconsistent here).

If the company's board returns no match for the uuid (posting pulled, or board is on a non-standard domain), fall back to `WebFetch` on the original URL; if that also fails or returns under 200 characters, skip the URL per the fetch-failure rule below.

**Notion:**
Use `WebFetch`. If it fails or returns fewer than 200 characters, skip this URL.

**If a fetch fails or returns under 100 characters of content:** skip that URL and note it in the final report as "could not fetch."

Derive the company name from the URL slug for each posting.

---

## Step 5 — Score each job against the resume

For each successfully fetched job, produce a **lightweight match assessment** using `RESUME_TEXT` from Step 1:

- **Match Score: X/100** — one sentence rationale
- **Top 3 Gaps** — the 3 most important missing skills or keywords

Keep scoring fast and consistent — this is a triage pass, not a deep analysis.

**Location flag:** If the role is in-person outside New York (e.g. SF, LA, Chicago) with no remote option, add `⚠️ relocation` to the result.

**Recency flag:** Using the date field captured in Step 4 (Greenhouse `updated_at`, Lever `createdAt` — convert from epoch ms, Ashby `publishedAt`), compare against today's date:
- **≤ 48 hours old** → add `🆕 new` — early-applicant window, surface this prominently
- **3–7 days old** → add `🕓 this week`
- **> 7 days old** → no flag
- **Notion or no date available** → no flag; Notion pages don't expose a reliable posted date, don't guess one

Note that this reflects when the posting was published to the ATS, not when it was indexed by Google — a listing can be a day or two old by the time it surfaces in Step 2's search results, so `🆕 new` still means "early" in practical terms, not "posted in the last hour."

---

## Step 6 — Present ranked results

Sort all scored jobs by match score (highest first); within a 5-point score band, break ties in favor of `🆕 new` over `🕓 this week` over unflagged. Present as a clean digest:

```
SOURCE JOBS — "{role}" [{location}] — {Today's Date}
──────────────────────────────────────────────────────
Found {N} jobs across Greenhouse / Ashby / Lever / Notion.
{M} already in the tracker were filtered out before fetching.
Ranked by match score. Run /job-tracker {url} to track any of these.

 #  Score  Company                 Title                          Location
────────────────────────────────────────────────────────────────────────────
 1   88    Vercel                  Software Engineer (AI)         Remote 🆕 new
           Gaps: Go, infra-at-scale, SRE
           https://jobs.ashbyhq.com/vercel/...

 2   81    Letta                   AI Engineer                    SF ⚠️ relocation
           Gaps: LangChain, Python-primary, memory systems
           https://boards.greenhouse.io/letta/...

 3   76    Linear                  Frontend Engineer              Remote 🕓 this week
           Gaps: Electron, desktop app experience, Rust
           ↺ already have a tracked role at this company (Outreached)
           https://jobs.lever.co/linear/...
...

──────────────────────────────────────────────────────
ALREADY TRACKED (excluded): {M} URLs
  - SafeLease — Full Stack Software Engineer (exact link match, status: Rejected)

SKIPPED (could not fetch): {N} URLs
Run /job-tracker {url} on any job above to research, score fully, and add to your tracker.
```

If fewer than 3 jobs were found or scored, note that and suggest refining the search terms.
