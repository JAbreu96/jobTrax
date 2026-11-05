---
name: company-research
description: Company research before an interview — what the product does and how it works, how it started versus now, customers, competitors, the hard engineering problems, team, funding and recent news — saved to the tracker's Company tab. Use when the user asks to research a company or employer, or asks what a company's product does or how it works.
argument-hint: "[company, website or job URL] [optional: role, interviewer, interview date, refresh]"
---

Research the company in: `$ARGUMENTS`

The output is a **briefing**: what the candidate needs to know about this company the night
before an interview, saved where they will read it — the tracker's Company tab. It uses the
company's own words where it can, and labels every guess.

## Step 0 — Load the profile

Read `config/profile.md` for `owner_name` and `star_vault_path`. If the file does not exist,
tell the user to run `cp config/profile.example.md config/profile.md` and fill it in, and stop.

Check whether this session can read `~/Downloads` and `{star_vault_path}`. A remote session
cannot; research still runs, without the calls.

Done when `owner_name` is known and you have noted which of the two folders are readable.

## Step 1 — Resolve the company

`$ARGUMENTS` holds a company name, a website or a job URL, plus an optional role, interviewer,
interview date, and the word `refresh`.

- For a job URL, take the company from it as `job-tracker` Step 1 does: the Greenhouse or Lever
  slug, or JSON-LD `hiringOrganization`. For `linkedin.com`, `indeed.com` or `glassdoor.com`,
  ask for the company name instead; their terms prohibit automated access.
- Call `mcp__job_tracker__filter_jobs` with the name. On a match, the **canonical name** is the
  row's `company` string, character for character. The Company tab looks a profile up by that
  string, so research saved as "Acme AI" never shows on a job tracked as "Acme". When rows
  with different company strings match, ask which one.
- With no match, the canonical name is the company's short name from its own website, and the
  job is **untracked**.

Done when the canonical name is written down, with tracked or untracked.

## Step 2 — Fresh or stale

Call `mcp__job_tracker__get_company_profile` with the canonical name. The profile is **fresh**
when all four hold:

- `researched_at` is 30 days old or less;
- `about` and `product` both have text;
- no call with the company is dated after `researched_at` — list the calls as in Step 3,
  source 4, by filename and frontmatter only;
- `$ARGUMENTS` does not say `refresh`.

Fresh: skip to Step 7 and report from the stored profile.

Stale or missing: research it. The stored sections are the **baseline**. Keep every stored line
that no newer source contradicts, since the candidate may have written it by hand in the GUI.
Replace a line only when a newer source contradicts it, and note each replacement for the
report.

Done when one line states fresh, stale or new, with the reason.

## Step 3 — Gather sources

Run independent fetches in parallel.

1. **The company's own pages** (WebFetch): home, product and solution pages, customers or case
   studies, about or team, careers, blog, docs and changelog.
2. **How it started**: the oldest blog or launch posts, and the Wayback Machine — fetch
   `https://archive.org/wayback/available?url=<domain>&timestamp=<founding year>0101`, then the
   snapshot it names.
3. **Everyone else** (WebSearch): funding announcements, press, founder podcasts and talks,
   partner case studies, competitors (`<company> alternatives`, `<category> software`) and
   founder backgrounds. LinkedIn, Glassdoor and Indeed count as search snippets only.
4. **Calls with the company**: transcripts in `~/Downloads` matching `*transcript*.txt` or
   `*transcript*.md` whose filename, frontmatter `title`, or participant email domain names the
   company, plus notes in `{star_vault_path}/Interview Analyses/` that name it. Read each in
   full. Quote what the company's people said about the product, data, customers, team and
   plans, with the call date and the `mm:ss` of the turn.
5. **The tracker**, for a tracked job:
   - `mcp__job_tracker__get_job_by_company` returns the full row: `job_summary`, and `notes`
     with the raw posting after the `====` line. It refuses when the company has several roles;
     then read the rows directly:
     `python3 -c "import sys,json; sys.path.insert(0,'.'); from src import jobs_db; print(json.dumps([r for r in jobs_db.get_all_jobs() if r['company']=='<canonical>'], default=str))"`
   - `mcp__job_tracker__list_interviews` gives the rounds and the people met.

Done when every call naming the company is read in full, the product has at least two
company-owned sources (or one plus a call), and `about`, `team`, `funding` and `recent_news`
each have a source or a noted "nothing reliable found".

## Step 4 — Analyse the product

The `product` section is the heart of the briefing. Write it as these eight `###` parts, in
order:

1. **What it does, for whom.** One line in the company's own words. Then the buyer, the daily
   user, and the industries served.
2. **How it works.** Four bold-led bullets: **Inputs** (the data and where it comes from),
   **Processing** (models, matching, agents, rules), **Outputs** (what the user sees),
   **Workflow** (onboarding, integrations, the user's week).
3. **Then vs now.** The earliest framing and today's, each dated. When the question the product
   answers has changed, name **the shift** on one ⚠️ line: it is worth asking about.
4. **Customers and proof.** Named customers, each marked "logo only" or "case study". Claimed
   results, marked "no method given" where none is.
5. **Competitors and edge.** Two to four named alternatives, including "spreadsheets /
   in-house" when that is the real rival. The claimed edge, and one counter-argument marked
   `[inferred]`.
6. **Hard engineering problems.** Three to six problems an engineer here would face — data
   quality, entity resolution, scale, evaluation, integrations. These are what a candidate's
   experience gets measured against.
7. **Where it's heading.** The stated roadmap, hiring signals and launches.
8. **Open questions.** Three to seven facts the research could not settle, phrased as things to
   find out.

Done when all eight parts exist, every bullet ends in a source or `[inferred]`, and part 8 has
at least three items.

## Step 5 — Write the other sections

- `about`: what the company is, its stage and market, HQ, founding year, headcount and work
  model. Seven bullets at most.
- `team`: founders and leaders with one line of background each, the hiring team, and one
  `**You met:** <name> (<role>), <date>` line per call or logged round.
- `funding`: rounds with date, amount and lead investor. When sources disagree, give both, each
  with its source; an unsettled round also becomes a product part 8 item.
- `recent_news`: the last 12 months, newest first, as `**Mon YYYY** — event (source)`. Seven at
  most.
- `website`: the canonical https URL.

Done when each section is written, or left out on purpose with the reason noted for the report.

## Step 6 — Save to the Company tab

Call `mcp__job_tracker__set_company_profile` with the canonical name and every section from
Steps 4 and 5. Leave `why_me` out: it holds the candidate's own case for the job, which this
skill does not write. Then read the profile back with `mcp__job_tracker__get_company_profile`.

Done when `researched_at` is today and every section you passed comes back as written.

## Step 7 — Report

In chat, six lines at most:

- what the company does, in one line;
- the shift, if there is one;
- stage and funding;
- the top open question;
- sections written, kept and replaced;
- how many sources were used.

Done when all six lines are in the chat.

## Profile format

The Company tab renders a small Markdown subset (`frontend/src/lib/markdown.ts`): headings (all
levels look the same), flat `- ` bullets, `**bold**`, `` `code` ``, and `[text](https://…)`
links. Write flat bullets wherever a table, numbered list or nested list would go — those three
show up as raw text. Keep each list to seven bullets.

## Sources and inferences

Every factual bullet ends in its source:

- a page: `([Company blog, Aug 2025](https://…))`
- a call: `(call with <name>, 2026-10-29, 05:40)`
- a page seen only through search: `(search snippet: PitchBook)`

A bullet with no source is your own reasoning and ends `[inferred]`. Prefer the company's own
dated words, and attribute a third party's claim to that party. Write absolute dates. Pick one
name per concept — "plant profile", say — and keep it in every section.

## Voice

Follow the `readable-output` skill in every section and in the chat report. Quotes from calls
are exempt from its length caps; trim them with `...`, and keep the words inside quotation
marks exactly as said.
