---
name: interview-fit
description: Fit analysis before an interview — how the candidate's projects map onto what a company needs: positioning, project-by-project fit, top connections with caveats, a talk track, gaps, coach probes and questions to ask. Saves an Obsidian note, a printable page and the tracker's Prep questions, after company-research brings the company profile up to date. Use when the user asks how they fit a company or role, what to ask an interviewer, or for a talk track or positioning before a round.
argument-hint: "[company] [optional: job URL or pasted JD, interviewer and their role, interview date]"
---

Build a pre-interview fit analysis for: `$ARGUMENTS`

The output is a **fit map**: where the candidate's real work meets this company's real problem,
how strong each link is, and where it is thin. Relevance is cheap to claim and costly to
overclaim, so every link carries its evidence and its caveat.

## Step 0 — Load the profile

Read `config/profile.md` for `owner_name`, `star_vault_path`, `companies_path` and
`resume_doc_id`, and its `## Sender background` section. If the file does not exist, tell the
user to run `cp config/profile.example.md config/profile.md` and fill it in, and stop.

The vault holds the facts this analysis stands on. If `{star_vault_path}` is blank, or this
session cannot read it (a remote session has no access to the user's machine), stop. Ask the
user to run from a local session, or to paste the STAR stories that matter.

`{companies_path}` is where the note is saved (Step 8). If it is blank, ask the user for their
company-notes folder and to add it to the profile.

Done when the four keys are known and `{star_vault_path}/STAR Index.md` has been read, its
Docket included.

## Step 1 — Pin down the round

- Call `mcp__job_tracker__filter_jobs` with the company. The **canonical name** is the row's
  `company` string; keep the row's exact `title` and `link`. With several roles, take the one
  in an interview stage, else ask. With no row, the job is **untracked**.
- Call `mcp__job_tracker__list_interviews` with the canonical name. The round is the first one
  with a `scheduled_date` of today or later. Rounds before today are earlier rounds, read in
  Step 4.
- The interviewer and their role come from `$ARGUMENTS`, else the round's label, else one ask,
  else "Next round". The date comes from `$ARGUMENTS`, else the round, else today.

Done when company, role, row (or untracked), interviewer and date are each named or marked
unknown.

## Step 2 — Bring the research up to date

Unless `company-research` started this run, invoke it with the Skill tool, passing
`<canonical name> | <role> | <interviewer> | <date> | called by interview-fit`. Its Step 2
decides whether the stored profile is fresh, so that rule lives in one place; a fresh profile
comes straight back.

Done when `about` and all eight `product` parts are in context, with their `researched_at`
date.

## Step 3 — Read what the role needs

Take the first job description found:

1. `$ARGUMENTS` — a URL or pasted text;
2. the row's `job_summary`;
3. the raw posting after `====` in the row's `notes` (read the row as company-research Step 3,
   source 5 does);
4. the row's `link`, when it is http(s);
5. a posting the research cited in the Company tab;
6. one ask.

Fetch a URL as `job-tracker` Step 1 does. For `linkedin.com`, `indeed.com` and
`glassdoor.com`, ask for the text instead.

Then write the **needs**: five to eight engineering needs, each tagged `(JD)`,
`(call <date> <mm:ss>)` or `[inferred from product]`.

- With no job description, the needs come from product part 6 and the calls, and the note's
  Context says "JD: none".
- When a call and the posting disagree, lead with the call — the hiring person said it more
  recently — and keep the difference as an open question.
- Carry hard requirements, such as years or languages, through to the gaps.

Done when every need has a tag and the JD source is recorded.

## Step 4 — Read earlier rounds

Read in full every earlier-round source for this company: call transcripts (found as in
company-research Step 3, source 4), notes in `{star_vault_path}/Interview Analyses/` that name
it, every note in its **company folder** (Step 8) — hub, job description, round notes and
earlier fit analyses — and its entries in `Questions I Failed At.md`. Take from them:

- what the company said it needs, quoted with date and `mm:ss`, added to the needs;
- what the candidate claimed, so the story stays consistent;
- the questions the candidate already asked;
- the interviewer's signals, and any analysis's coaching pattern.

Done when every matching file is read, or "no earlier rounds" is recorded.

## Step 5 — Build the evidence ledger

The **ledger** is working material, not output: one row per project the candidate could cite,
as project | what they built | owned vs team or platform | metric | source file.

- The resume: `mcp__claude_ai_Google_Drive__read_file_content` with `fileId` `{resume_doc_id}`.
- The vault: `STAR Index.md`; every STAR story whose `project/*` tag or content could meet a
  need, Bullet Outline first and the full text for metrics and ownership; `type/pitch` notes;
  and `Hypothetical Technical Questions.md`.

When sources disagree, the STAR story wins and the disagreement is **fact drift**. A project
with no STAR story is "resume only".

Done when every project the analysis will cite has a sourced row.

## Step 6 — Map the fit

Write note sections 1–4, 6 and 7, laid out as in Note layout below.

Fit scale, for section 3:

- **Very strong** — the same problem and the same kind of system, and the candidate owned it.
- **Strong** — the same problem shape, in a different domain.
- **Potential** — one skill transfers.
- **Indirect** — background only.

Evidence scale, for section 6:

- **Directly relevant** — built it, or its twin. Cite it.
- **Adjacent** — built something next to it. Name what.
- **Not demonstrated** — nothing in the ledger. Say so plainly.

Coach probes, for section 7: five to eight questions an interviewer would use to test whether a
link is real, each tied to a section 3 project. Add any `Questions I Failed At` entry that
matches a need. A probe the ledger cannot answer gets `[gap: no STAR detail]` and a task in
Before the round.

Done when every need from Step 3 appears in section 3 or section 6, every Very strong row cites
a ledger row the candidate owned, and each top-3 connection has a Verify first.

## Step 7 — Questions to ask, then the talk track

Questions, for section 8, take the candidate's format: one open question starting with "What"
or "How", **specific** to this company. A specific question names one of their real things: a
focus area, product, team, office or launch.

An **anchor** sentence goes before the question only when it **leads into** it.

- The anchor comes from the ledger: something the candidate built or did. It leads into the
  question when the question is the natural follow-up to it. Read the pair aloud to test it.
  Example: "At my last job, I redesigned our data quality checks so they stopped failing good
  exports. How much of your delivery checking is automated today?"
- When no ledger row leads into the question, a line of the company's own context may set it
  up. That line comes from the Company tab, a call quote or the JD. Otherwise the question
  stands alone.
- Label each with its **pairing**, `<anchor> → <topic>`, such as "Data quality checks →
  delivery checks". A question with no anchor is labelled with its topic alone, such as "Team
  and manager".
- Seven at most. Mark the three for a short call with ★, and list them first.
- Fit the interviewer. A recruiter gets the team, the manager, the focus area and where the team
  sits. A CEO gets product, customers and direction. A CTO gets the data model, agents and the
  quality bar. A peer gets the day-to-day.
- Draw on product part 8. Skip anything an earlier round already asked, or the Company tab
  already answers.
- Compensation, equity and logistics go on one "Save for later" line, outside the seven.
- Two sentences at most, written to be said aloud.

The talk track, for section 5: first person, 60–90 seconds aloud. In order: their problem in
their words → the project that met it, with its metric → what transfers → one gap, owned
honestly → ★1, word for word.

Done when every question is specific and starts with What or How, every anchor leads into its
question, none repeats an earlier round, the ★ rows come first, and the talk track ends on ★1.

## Step 8 — Save the note and the print page

The note lives in the **company folder**: the folder in `{companies_path}` named for the
company. Match the canonical name case-insensitively, as the whole name or its first word
("Acme" finds `Acme AI/`), and use that folder's name as `<Folder>`. With no match, create
`{companies_path}/<canonical name>/`.

Save the note as `<Folder>/<Folder> - Fit - <YYYY-MM-DD> <Interviewer>.md`, dated by the round.
When the file exists, carry its `## My notes` section over word for word and replace the rest.

Link it from the hub, `<Folder>/<Folder>.md`:

- When the hub has a `**Fit analysis:**` line, point it at this note.
- Otherwise add `**Fit analysis:** [[<note name>]]` on the line after `**Job description:**`,
  or after the hub's opening block when that line is missing.
- With no hub, create one: `Role: <role>`, `Posting: <link>`, a blank line, then the
  `**Fit analysis:**` line. Change nothing else in an existing hub.

Before saving, write the **Glossary** from the finished note: every acronym and industry term
it uses, from the company's domain (ERP, CSRD), its stack (Temporal, DuckDB) and interview
jargon (fit-gap, cutover). Spell each acronym out, then say what it means in plain words.

Run `bash ~/.claude/skills/readable-output/check.sh "<note path>"` and fix every finding in
prose.

Build the print page from the saved note. Copy `print.html` from this skill's folder, keep its
`<style>`, and fill each `<!-- slot -->` with that section, in note order: the same content in
a print shell, not a summary. Render `[[links]]` as plain names, and give ★ rows
`class="top3"`. Save it next to the note, with the same name and `.html`.

Done when both files exist, the hub links the note, every acronym in the note has a Glossary
row, check.sh reports no prose findings, and the note's `## ` heading count equals the page's
`<h2>` count.

## Step 9 — Update the tracker

`why_me` gets the short version, ten lines at most, in the Company tab's Markdown subset (see
company-research, Profile format):

- a `**Positioning:**` line and a `**Shared problem:**` line;
- `### Top connections`, three bullets of `<project> → <need> (<fit>)`;
- `### Gaps to handle`, up to three bullets;
- last, the **marker** line: ``**Full analysis:** `<Folder>/<file name>.md` (<date>)``.

Read the profile with `mcp__job_tracker__get_company_profile` first. Replace `why_me` when it
is empty or its last line is a marker. Anything else is the candidate's own writing: show it,
and ask whether to replace it or keep it. Write with `mcp__job_tracker__set_company_profile`,
passing only `why_me`.

For a tracked job, add the questions and tasks to the Prep tab:

1. Call `mcp__job_tracker__get_prep_plan` with the canonical name and the row's `link`.
2. Keep only questions whose substance is not already there, done or not.
3. Write bodies as plain text: `★ <pairing> — <question>` for the top three, then
   `<pairing> — <question>`.
4. Tasks, five at most: placeholders to fill, open Verify first items, fact drift to settle.
5. Call `mcp__job_tracker__add_prep_plan` with `questions`, `tasks` and the row's `link`.

An untracked job skips the Prep tab. The report says to run `/job-tracker <url>`, then this
skill again.

Done when `why_me` is written, or the candidate chose to keep theirs, and a `get_prep_plan`
read-back shows each new item exactly once.

## Step 10 — Report

In chat:

- the positioning line;
- the ★ questions;
- gap counts by evidence level;
- the placeholders to fill;
- both file paths;
- what changed in the tracker: `why_me` written or kept, questions and tasks added, any skipped
  as already there.

Done when all six are in the chat.

## Note layout

```markdown
---
tags:
  - type/fit-analysis
---
Back to [[<Folder>]]

# <Folder> - Fit - <YYYY-MM-DD> <Interviewer>

## Context
Table: Company | Role | Round (interviewer, their role) | Date | JD source | Research date | Earlier rounds.
Then "Their product", five rows at most: what it does · for whom · how it works · the shift · the hardest problem.

## Glossary
Table: Term | Plain meaning | Why it matters here. Written last (Step 8), placed here so it is read first.

## 1. Positioning
"Your strongest positioning is not <X>. It's <Y>." Then two lines at most on why.

## 2. The shared problem
One sentence naming the problem both sides solve. Then a table, | | You at <employer> | <Company> |,
with rows: the data · the mess · what gets built · who relies on it · the cost of being wrong.

## 3. Project fit
Table: Your project | What <Company> needs | Fit | Why | Source.
Then: "Fit grades relevance, not proven depth. Section 7 tests depth."

## 4. Top 3 connections
One `### <project> → <need>` per connection, each a four-row table:
You built | They need | Transferable skill | Verify first.

## 5. Talk track
A blockquote, first person, ending on ★1.

## 6. Gaps
Table: Their challenge | Your evidence | What you know | Not built yet | How you'd approach it.

## 7. Coach questions
Table: Project | Probe | A strong answer draws on.

## 8. Questions to ask
Table: ★ | Pairing | Question. Then the "Save for later:" line.

## Before the round
A `- [ ]` checklist: placeholders to fill, open Verify first items, fact drift.

## Sources
Candidate side: STAR links, the resume, calls. Company side: the Company tab and its date, the JD source.

## My notes
Carried over word for word on a re-run.
```

In a table cell, link a STAR story as `[[STAR Stories - <name>]]`, without an alias: the alias
pipe would split the cell.

## Grounding

- **Ground every fact** about the candidate in a ledger row. A missing fact becomes a bracketed
  placeholder, such as `[how many entity types the graph joined]`, listed in Before the round.
- **Own the boundary.** Name what the candidate owned and what the team or platform owned, as
  the STAR story states it.
- **Caveat over claim.** A link that rests on relevance gets a Verify first: "Did you design the
  data relationships, or the view on top of them?" When a STAR story settles it, write the
  answer and its source instead.
- Company-side claims carry their origin: `(JD)`, `(call <date> <mm:ss>)`, `(Company tab)` or
  `[inferred]`.
- The STAR Index Docket's "don't claim" lines bind every section.

## Voice

Follow the `readable-output` skill. The talk track and the questions are said aloud, so they
are exempt from its block cap, but every sentence in them stays at 20 words or fewer. Address
the candidate as "you". Use a pronoun for them only if the profile states one; otherwise use
they/them.
