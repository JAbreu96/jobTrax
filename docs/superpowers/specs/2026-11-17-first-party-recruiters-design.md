# First-party recruiters go to the front of the line

Date: 2026-11-17. Status: draft, awaiting approval.

## Intent

Almost all recruiter mail comes from agencies (3rd party): of 191 recruiters in the
tracker, only a handful work at the company that is hiring. Those few (1st party) are
a direct line to the employer, and today they get lost among the agency pitches.

**1st party** means the person writing works at the hiring company. The test is the
sender's email domain: it belongs to the company the role is at.

Today triage has no such idea. `recruiter_outreach` is defined as "a staffing/agency
recruiter", so a company recruiter's cold pitch is scored like an agency blast. Below
60/100 it gets no task and no job row.

## Goals

- Every pitch from a 1st-party recruiter becomes a Google Task, whatever its fit score.
- Every such pitch gets a job row in the tracker, whatever its score.
- Those tasks are impossible to miss: a `★ DIRECT` title prefix, top of My Tasks, due
  the day triage runs.
- The recruiter is marked 1st party in the tracker.

## Non-goals

- No change to the Recruiters card or any other UI. This stores and exposes the flag;
  sorting by it comes later.
- No change to how agency recruiters are handled: score bar, gate and rows stay as they are.
- No tasks or flags for past mail. No backfill of existing recruiters.
- No change to the drafting rules in Step 5b.

## Anti-goal

An agency recruiter marked `★ DIRECT`. One false mark teaches the user to ignore the
mark, which is worse than missing a real one. **When unsure, it is not 1st party.**

## Approaches considered

1. **Triage instructions only.** Triage judges each sender by eye. Quick, but this
   project has seen eyeball rules applied inconsistently or skipped (the LinkedIn
   recruiter capture that never ran).
2. **A tested matching function, plus instructions.** Triage calls the function, then
   asks the tracker for a job row. The row still depends on triage remembering to ask.
3. **Same function, and the tracker tool enforces it.** `record_recruiter_outreach`
   runs the check itself, forces the job row and stores the flag.

**Picked: 3** (Joel, 2026-11-17). The score-bar job-row rule was moved into the tool
for the same reason: stated in the instructions alone, it was not followed.

## Design

### 1. The match: `is_first_party` in `src/triage_rules.py`

```python
def is_first_party(sender_email: str, company: str, agency: str) -> bool
```

True only when **both** hold:

- `agency` is blank, and
- the sender's domain belongs to `company`.

`agency` must be blank because of undisclosed employers. When an agency hides who it
is hiring for, the skill files `company` as the agency's own name, so the domain
matches. A filled `agency` is the only thing that tells those two cases apart.

Never true for:

- free mail (gmail.com, outlook.com, yahoo.com, icloud.com, ...);
- hiring-tool and job-board relays (greenhouse, lever, ashbyhq, gem, rippling,
  workday, paraform, dice, indeed, linkedin, ...).

**Loose match.** Take the domain's main label (`careers.acme.co.uk` → `acme`).
Normalise the company name: lowercase, legal suffixes dropped (inc, llc, corp, ltd,
co), non-letters removed. They match when equal, or when the label is the company
plus a common affix: suffixes like `hq`, `labs`, `ai`, `io`, `app`, `team`, `careers`,
`jobs`, `tech`, `group`, and prefixes like `get`, `try`, `join`.

These must hold:

| Sender | `company` | `agency` | 1st party? | Why |
|---|---|---|---|---|
| jane@acme.com | Acme | | yes | |
| jane@acmehq.com | Acme Inc. | | yes | affix |
| jane@careers.acme.co.uk | Acme | | yes | subdomain, two-part TLD |
| jane@getacme.io | Acme | | yes | affix |
| raj@staffco.com | Acme | StaffCo | no | agency named |
| raj@staffcollc.com | StaffCo LLC | StaffCo LLC | no | undisclosed employer |
| jane@acme.com | Acme | Acme | no | `agency` filled; fail safe |
| raj@gmail.com | Acme | | no | free mail |
| jane@gem.com | Acme | | no | hiring-tool relay |
| jane@acmeview.ai | Acme | | no | `view` is not an affix |
| sam@acme.com | Globex | | no | different company |

### 2. The tracker

- **New column** `recruiters.first_party INTEGER NOT NULL DEFAULT 0`. It is added by
  `ALTER` in `_ensure_recruiters_schema`, the same pattern as `manual_entry`. It only
  ever turns on (`MAX`), so a later message can't clear it.
- **Snapshot first.** The live Turso database gets the column the first time any
  entry point connects. Take the `turso db shell job-tracker ".dump"` snapshot from
  `CLAUDE.md` before that happens.
- `upsert_recruiter(..., first_party: bool = False)`.
- **`record_recruiter_outreach(..., first_party: bool = False)`**:
  - For `source="email"`, it computes `is_first_party(email or identity, company, agency)`
    and ORs the result with the `first_party` argument. For `linkedin` there is no
    domain, so only the argument counts.
  - When 1st party: it forces `create_job_row=True`, stores the flag, starts the job
    row's `notes` with `1st-party recruiter (<domain>)`, and returns `"first_party": true`.
  - It stays idempotent: re-processing the same email updates rather than duplicates.
- `list_recruiters` returns `first_party`. Ordering is unchanged.

### 3. Triage (`.claude/skills/inbox-triage/SKILL.md`)

- **Step 3, classification.** Define 1st party with a pointer to `is_first_party`.
  A 1st-party recruiter pitching a role the user never applied to is captured with
  `record_recruiter_outreach` even when the message names the user. Today that override
  routes it to `human_action`, which never records the role.
- **Step 4, capture.** Leave `agency` blank when the recruiter works for the hiring
  company. Score the role as usual; the score goes in the notes and the task.
- **LinkedIn.** InMail comes from a LinkedIn relay, so there's no domain to check.
  Triage reads the signature ("Recruiter at Acme", with the role at Acme) and passes
  `first_party=true`. When the signature doesn't say, it is not 1st party.
- **Step 5, the gate.** A 1st-party pitch skips the score bar and tests 2 and 3 (the
  ask and the sign-off). Test 1 still applies: if the user spoke last, they are
  waiting on the recruiter and there is no task. Other messages from someone at the
  hiring company, such as an ongoing process or a hiring manager, go through the
  normal gate.
- **The task.** Any task where the person writing is at the hiring company gets:
  - title prefix `★ DIRECT · `, for example
    `★ DIRECT · Reply to Jane Doe (Acme) — interested in Senior FE?`;
  - due today, the day triage runs;
  - a notes line `direct: <domain> matches <company>`, plus `Match Score: X/100`
    for pitches.
- **Top of the list.** Google Tasks puts each new task at the top, so a later ordinary
  task would bury a `★ DIRECT` one. After all tasks are created, triage moves every open
  `★ DIRECT` task to the top of My Tasks with `mcp__gtasks__move` (no `previous`).
- **Step 8, report.** Add `direct: <n> tasks, <n> recruiters flagged`.

Unchanged: the `thread:<id>` duplicate check, never completing or deleting tasks, and
the read-only stance on Gmail.

### 4. Tests

- `tests/test_triage_rules.py`: the table above.
- `tests/test_recruiters.py`: the column is added idempotently; the flag only turns on;
  a 1st-party email with `create_job_row=False` still gets a row; an agency sender
  doesn't; LinkedIn with `first_party=True` gets a row and the flag; re-processing
  doesn't duplicate.
- Fixtures use placeholder companies only (Acme, Globex, StaffCo), because the repo is public.
- `tests/conftest.py` already keeps tests off the live database.

### 5. Delivery

One PR off `main`, branch `first-party-recruiters`. It touches about five files and
fits one phase, so it isn't a stack.

## Calls made without asking (check these)

1. The "you spoke last" check still stops a 1st-party pitch from becoming a task.
2. Anyone at the hiring company gets the `★ DIRECT` mark on their tasks, including a
   hiring manager, not only a recruiter. Their ongoing threads keep the normal gate.
3. `agency` must be blank for a match. A company recruiter whom triage files with an
   agency name is missed, which fails safe to today's behaviour.
4. No backfill and no UI change.
5. Drafts stay as they are: only for pitches scoring 60+.
6. The job row's notes start with `1st-party recruiter (<domain>)`.

## Left to the builder

- The exact free-mail, relay and affix lists, as long as the table holds.
- The order of several `★ DIRECT` tasks among themselves at the top.
