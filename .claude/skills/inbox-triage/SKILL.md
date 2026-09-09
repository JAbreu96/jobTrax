---
name: inbox-triage
description: Reconcile new Gmail against the job tracker and turn only the things that need a human into Google Tasks. Reads mail since a stored watermark across both inboxes and updates rows that already exist; the only rows it creates are recruiter outreach. Records interviews and follow-ups. Runs daily on a schedule, or on demand.
argument-hint: "(no arguments required)"
---

Reconcile everything that arrived in Gmail since the last run into the local job tracker, and create Google Tasks **only** for items that need Joel personally.

This is the single scheduled owner of Gmail→tracker reconciliation. It does not send email.

## Operating principles

- **Silence is the default.** Roughly 90% of inbound mail is auto-acknowledgment or rejection. Those update the tracker and are never surfaced as tasks. Joel receives ~40 such emails a day; adding them to a task list recreates the problem this skill exists to solve.
- **Never guess a row.** A wrong silent write is worse than an unanswered question. When an email cannot be tied to exactly one tracked role, ask via a task.
- **Never downgrade a status.** `Phone Screen` outranks `Applied`. Only move a job forward, except for `Rejected`, which may always be set.
- **The gate in Step 5 is the only thing that creates tasks.** No earlier step may create one. Categories and scores decide what is *worth* surfacing; the gate decides whether the ball is actually in Joel's court, and both must agree.
- **`record_recruiter_outreach` is the only thing that creates job rows.** Triage reconciles mail against rows that already exist; it does not open new ones from receipts, rejections, or interview requests. A role Joel was pitched has no other way in — everything else arrives through `/applypass-inbound` with a real URL and description. Before adding any write path, check it against this line.
- **Never destroy work.** Triage adds tasks and annotates them. It does not complete or delete them — a wrong annotation is visible and reversible, a wrong completion silently erases a real obligation.
- **Idempotent.** Running twice in a row must produce zero new tasks and zero new writes.

## The predicates

The mechanical rules live in `src/triage_rules.py`, not in this file. Call them; do not
re-derive them by eye:

```bash
python3 -c "
from src.triage_rules import detect_rejection, detect_closing_statement, contains_ask
body = open('/tmp/msg.txt').read()
print('rejection:', detect_rejection(body))
print('closing:  ', detect_closing_statement(body))
print('ask:      ', contains_ask(body))
"
```

`normalize_subject`, `is_from_owner`, `strip_quoted_chain`, `strip_html` and
`unescape_title` are there too. Every predicate strips the quoted reply chain first — a
fetched body carries the history inline, and a scan over the raw text reads sign-offs and
rejection language out of *earlier* messages, so every long thread eventually looks closed.

`scripts/read_mail.py` already applies `strip_html` and `strip_quoted_chain`, so its output
goes straight to the predicates.

---

## Step 1 — Read the watermarks

There are two inboxes and two watermarks, advanced independently. A failure against one must
not roll back the other's progress.

```bash
python3 -c "from src import jobs_db; print(jobs_db.get_meta('inbox_triage.last_seen','0'))"
python3 -c "from src import jobs_db; print(jobs_db.get_meta('inbox_triage.last_seen_alt','0'))"
```

| Watermark | Inbox | Tools |
|---|---|---|
| `inbox_triage.last_seen` | `joelchristabreu4044@` — applications, ATS, direct recruiters | `mcp__gmail_personal__*` |
| `inbox_triage.last_seen_alt` | `ajoelcrist@` — LinkedIn InMail and notifications | `mcp__gmail_alt__*` |

`0` means this has never run against that inbox. Use the last 24 hours rather than all
history, and say so in the report — a zero watermark on an inbox with a backlog means the
backlog needs a supervised pass, not a silent 24-hour window that declares it processed.

Capture the current time **before** searching — it bounds the search window:

```bash
python3 -c "import time; print(int(time.time()))"
```

### A run is bounded; the watermark follows what was processed

Process at most **400 messages per inbox**, taking the **oldest** first.

Oldest-first is the load-bearing half. Gmail returns newest-first, so a capped run
that took the newest 400 and then set the watermark to the captured time would skip
everything older *permanently* — a silent loss dressed up as a safety feature. So the
watermark advances to the internal date of the newest message actually processed, not
to the captured time. Whatever is left is still ahead of the watermark and the next
run picks it up.

If a cap was hit, say so in Step 8 with the number remaining. A backlog that never
shrinks means the cap is too low or the schedule too infrequent, and that is only
visible if it is reported.

---

## Step 2 — Fetch new mail, and group it into threads

Each inbox has its own set of queries. They are narrow on purpose: a run that listed
everything cost ~17k tokens in subject lines alone, and most of what it listed was
never going to be read.

### The queries

Substitute each inbox's own watermark. `maxResults: 100`; pre-split a wide window into
~6h slices, because a single wide search times out.

**Primary** (`mcp__gmail_personal__search_emails`):

```
1.  after:<wm> -from:linkedin.com label:simplify/rejected
2.  after:<wm> -from:linkedin.com label:simplify/interviewing
3.  after:<wm> -from:linkedin.com
      -label:simplify/rejected -label:simplify/interviewing
      -subject:"Security code for your application"
      -subject:"Indeed Application:"
      -subject:"EEO survey for"
      -from:(dice.com OR glassdoor.com OR my.theladders.com OR simplify.jobs OR
             match.indeed.com OR alert.refer.io OR trueup.io OR
             us.greenhouse-jobs.com OR builtin.com)
```

**Alt** (`mcp__gmail_alt__search_emails`):

```
4.  after:<wm_alt> from:(hit-reply@linkedin.com OR inmail-hit-reply@linkedin.com)
5.  after:<wm_alt> -from:linkedin.com
      subject:(engineer OR developer OR hiring OR opportunity OR role OR position)
```

Measured over a 10-day window: primary 1127 → 847, alt 1131 → 103. Query 3's
exclusions are only the four patterns that are *mechanically* meaningless — a security
code, an Indeed submission receipt, an EEO survey, a job-alert sender. A broader ATS
deny-list was considered and rejected: Greenhouse and Workday carry rejections and
interview invitations as well as receipts, so excluding them by sender loses real mail.

Query 5 replaces `category:primary`, which was measured and rejected — it returns ~40
irrelevant messages (Petco, Bank of America, Discover, TLDR, Apple) and does **not**
contain the one message it existed to recover.

If more than 100 come back for a slice, narrow it further — never silently drop the
overflow. This is not theoretical: a 60-result cap once hid Kim Hanson's *"please send
an updated resume"* for four days.

### Why LinkedIn is excluded from the primary queries

A **Settings→Forwarding rule** (not a Gmail filter — `list_filters` returns empty on
both accounts, which is why this was once thought stale) copies LinkedIn mail from
`ajoelcrist@` into `joelchristabreu4044+linkedin@gmail.com`, so Joel sees it in the
inbox he actually reads. Triage must ignore those copies: it reads the originals
through `gmail_alt`, and the forwarded duplicate is the *same conversation* arriving a
second time. The `thread:<id>` key cannot catch it — Gmail message and thread ids are
per-account, so the two copies look like unrelated threads and would earn two tasks for
one recruiter.

Exclude on the **sender**, not the recipient. Gmail preserves the original `To:` header
when it forwards, so the forwarded copy still reads `To: ajoelcrist@gmail.com` and
`-to:joelchristabreu4044+linkedin@gmail.com` would quietly match nothing.
`deliveredto:` is the precise operator if a recipient test is ever needed, but sender
exclusion is simpler and costs nothing: native LinkedIn mail reaching the primary inbox
is job-alert `noise` anyway.

### Group before reading anything

The search results include Joel's own sent mail, which is what makes this free:

1. Compute `normalize_subject(subject)` for every result.
2. Group by that key.
3. If a group's **newest** message is `is_from_owner(from)`, the user spoke last. The whole
   group drops out here, before any body is fetched.

### Reading bodies

**Do not call `read_email`.** It returns the raw payload. One Indeed message came back
at 55,491 characters — large enough to overflow the tool-result cap and spill to disk —
of which about 760 were words. Across a run that was ~100–140k tokens spent on markup.

Use the script instead. It fetches through the same credentials, strips the HTML,
tracking URLs and invisible padding, and cuts the quoted chain:

```bash
python3 scripts/read_mail.py --account primary <id> <id> <id> ...
python3 scripts/read_mail.py --account alt --format json <id> ...
```

That same Indeed message comes back at 764 characters with the sender, role, company,
location and the decisive *"This message is nonrepliable… log in"* line all intact.

**Batch the ids** — one invocation per ~30 messages. The per-call overhead is what made
even short messages expensive, and it is paid once per invocation, not once per message.

Read bodies only for the newest message of each surviving group, and only where Step 3
routes the group to a body read. Subject and sender are enough to discard noise, and a
`simplify/rejected` message needs no body at all.

The script prints `Thread ID:` — record it. It confirms the grouping (subjects drift,
and two threads can share one) and it is the task key in Step 5.

---

## Step 3 — Classify

Assign each thread exactly one category, judged on its **newest message**.

### The Simplify labels come first

Joel runs the Simplify browser extension, which labels application mail as it arrives.
Two of its labels are trustworthy enough to route on, before any other test:

| Label | Routing |
|---|---|
| `simplify/rejected` | `rejection`. **No body read.** Step 4 has the write rule |
| `simplify/interviewing` | Read the body, then classify normally. The label decides only that this is worth opening |
| `simplify/screen`, `simplify/offer` | Ignore. Fall through to the rules below |

This is not a guess. Fifteen `simplify/rejected` messages were read in full and checked:
**all fifteen were genuine rejections.** `detect_rejection` agreed with only nine of them
at the time — the label was right and the predicate was short, which is the opposite of
what was assumed. Six phrasings were added to `src/triage_rules.py` as a result, and it
now agrees on fourteen. The fifteenth is an Indeed template whose body contains no
rejection language at all, which is exactly the case the label exists to cover.

`simplify/interviewing` **routes but never writes.** It says a process is live, not what
just happened in it — a message in an interviewing thread can be a reschedule, a
question, or a rejection. The body still decides. `simplify/offer` has fired twice ever
and was wrong both times; it carries no information.

Everything unlabelled — the whole alt inbox included — classifies exactly as it always
has. The labels are a shortcut on the primary inbox, not a replacement for the rules.

| Category | Test | Outcome |
|---|---|---|
| `human_action` | A real person wrote and wants something from Joel | Gate |
| `deadline` | Something has a clock: assessment expiry, incomplete application, scheduled interview | Gate |
| `rejection` | `detect_rejection` finds language in the message's own text | Update a tracked row, silent. Never creates one |
| `auto_ack` | "Thank you for applying", "we've received your application", Indeed/Workday/Greenhouse receipts | Update a tracked row. **Never create one** — untracked receipts are reported in Step 8, not written |
| `recruiter_outreach` | A staffing/agency recruiter pitching a role Joel never applied to | **Always** record the recruiter; job row and gate only if scored 60+ |
| `noise` | Job alerts, marketing, newsletters, Glassdoor/Dice/LinkedIn digests, security codes | Ignore entirely |

**Identifying a human:** a named sender at a company domain, writing prose addressed to Joel,
expecting a reply. Not `no-reply@`, `noreply@`, `notifications@`, `donotreply@`, and not an
ATS template even when it carries a person's name in the signature.

**When you genuinely cannot tell — flag it `unsure` and carry it to Step 5.** Do not promote
it to `human_action`. That promotion used to happen here, before the gate ran, and it chose
the verb `Reply to` on the way past. Tests 2 and 3 both require reading intent, so a message
promoted *because* its intent was unreadable fell straight through the gate — which is
exactly how a task came to tell Joel to reply to a JustPower rejection.

**LinkedIn senders** (`ajoelcrist@`) split by envelope:

- `hit-reply@linkedin.com` / `inmail-hit-reply@linkedin.com` carry the **full message text**
  and are a live conversation. Read them; the predicates work normally.
- `messages-noreply@` / `jobs-noreply@` / `notifications-noreply@` are digests. `noise`.
- A LinkedIn thread is a task candidate **only if its newest message is from the recruiter**.
  If Joel answered last, Step 2 has already dropped it.

**`human_action` vs `recruiter_outreach`.** Both come from a real person, so the split is
whether Joel is already in a process. `human_action` refers to something Joel did — his
application, his interview, a question he must answer. `recruiter_outreach` pitches a role he
never applied to, and is usually blasted to a list. The mechanical tells of a blast are an
unsubscribe link, a tracking pixel, and a body that never references Joel's background; any
one of them, on mail pitching an unsolicited role, makes it `recruiter_outreach`.

Two things override that and make it `human_action` — a reply within a thread Joel started,
and any request that names him specifically.

---

## Step 4 — Update the tracker

### A labelled rejection may be written without reading it

For a message carrying `simplify/rejected`, take the company and role from the **subject
line**, run the lookup in the numbered steps below, and then:

| `match` | Action |
|---|---|
| `exact` | Set `Rejected`. Silent, and **no body is fetched** |
| anything else | Fetch the body and follow the ordinary path below |

The label decides *what kind of message this is*; `find_job_for_email` still decides
*which row*. "Never guess a row" is untouched — an `ambiguous` or `none` result reads
the body exactly as it always did. What the label buys is not permission to guess, it is
permission to skip ~14k tokens of markup when the row is already unambiguous.

For every other `rejection`, and every status-advancing `human_action`/`deadline`:

1. Extract the company and the role title as quoted in the email, and pass the title through
   `unescape_title` before any lookup or write. Most of this mail is HTML, so an ampersand
   arrives as `&amp;`; passing that through creates rows titled
   `Software Verification &amp; QA Specialist` that match nothing and need repair by hand.
2. Call `mcp__job_tracker__find_job_for_email` with `company` and `title_hint`.

   **Always pass the title.** Without one, a company with a single row returns `exact` for
   whatever that row happens to be — not necessarily the role the email is about. An ALTEN
   rejection for *IT/OT Engineer* resolved `exact` onto their *ADAS Performance Engineer* row
   purely because that was the only row filed under the sender's company string.

   If the title returns `none`, try a **shorter company string** before giving up. The ATS
   name and the tracked name often differ: that same IT/OT row was filed under `ALTEN SA`
   while the email said `ALTEN Technology USA`, and searching `ALTEN` with the title found it
   exactly.
3. Act on the result:

| `match` | Action |
|---|---|
| `exact` | `mcp__job_tracker__update_job_status` with the returned `position_title`. Silent. |
| `ambiguous` | **No write.** Carry to the gate as `unsure`: "Which <company> role does this refer to?", listing candidates. |
| `none` + it is a rejection | **No write.** No task — a rejection for an untracked role needs nothing. |
| `none` + it is an `auto_ack` | **No write, no task.** Count it for Step 8 and move on. |
| `none` + it is human/deadline | **No write.** Carry to the gate so it becomes a task. The thing worth capturing is Joel's attention, not a row. |

Status mapping: interview scheduled/requested → `Phone Screen`; rejection → `Rejected`.
Both apply only to a row that already exists. A status is not a booking — if a date and
time were agreed, Step 6 records the round as well, or the date is lost.

### Triage does not create job rows from receipts

It used to. `auto_ack` for an untracked role created a row at `Applied`, and an
untracked human/deadline message called `mcp__job_tracker__add_job`. Between them they
produced **53 rows with nothing in them** — no posting URL, no description, no location,
and for 38 of them the title `Role not specified`. A receipt names a company and
sometimes a role; it never carries the posting, so `link` was filled with a synthetic
`email:<gmail-message-id>` just to satisfy the primary key.

Those rows were never needed. Auto-apply submissions reach the tracker through
`/applypass-inbound` with the real URL, the real title and a ~2500-character
description. The receipt arrives *because* the application was submitted — it is a
duplicate of a row the import is already going to write, minus everything useful.

So: acknowledge receipts against rows that exist, and let the import own creation.
An untracked interview request still reaches Joel — as a task, which is what he acts
on anyway.

### A rejection closes the row it names, not the thread

`detect_rejection` returns the *sentence* the language appears in, not a bare boolean,
because a rejection and a fresh pitch routinely arrive together:

> *"Unfortunately we've moved forward with other candidates for the Front End role. That
> said, I have a Full Stack opening on another team — would you be interested?"*

Read the returned sentence to attribute the rejection to **one** role, set that row to
`Rejected`, and stop. If the message pitches a *different* role, that role is a new
`recruiter_outreach` item — a new row, scored below, gated below. Agency recruiters send this
constantly, and it carries the warmest lead the inbox produces: they have already read his
resume. Closing the thread throws it away.

### Capturing inbound roles

**Split the message into roles before writing anything.** One email routinely carries
several: Laxman Ottem sent a Frontend Engineer role and a Cloud Backend Engineer role
fourteen minutes apart, and they were captured as one row titled
`Frontend Engineer / Cloud Backend Engineer`. Two roles in one row cannot carry independent
statuses, so you cannot reject one and pursue the other.

Then call `mcp__job_tracker__record_recruiter_outreach` **once per role**, all sharing the
same `message_id`:

| Argument | Value |
|---|---|
| `source` | `email`, or `linkedin` for `hit-reply@` / `inmail-hit-reply@` mail |
| `identity` | the sender address, or the **LinkedIn profile slug** |
| `company` | the agency name when the employer is undisclosed (`Kastech SSG`) |
| `position_title` | this role alone, never two joined by a slash |
| `name`, `agency`, `email` | as signed |
| `account` | `primary`, or `alt` for the `ajoelcrist@` inbox |
| `message_id`, `thread_id`, `subject` | from `scripts/read_mail.py` |
| `notes` | the score and rationale, below |

It creates the job row at status `Tracking` with a deterministic synthetic link, so
**re-processing the same email updates rather than duplicating** — and it never downgrades a
status that has since moved on.

### The recruiter is always recorded; the job row is not

Call it for **every** recruiter-sourced role, whatever the score. Who is contacting Joel is
the thing the Recruiters card exists to show, and a cold blast still answers that.

But only let it create a **job row** when the score clears 60 — the same bar the gate uses.
InMail arrives at roughly 40 messages per six weeks, nearly all cold, and a row apiece buries
the tracker in roles nobody is pursuing. For a sub-60 role, record the recruiter and the
message and stop there.

A sub-60 role that later turns real gets its row by hand. That is the same trade the tracker
already makes everywhere else: it would rather be missing a row you can add than carry forty
you have to ignore.

**`identity` is not always the sender address.** LinkedIn InMail arrives from the shared relay
`inmail-hit-reply@linkedin.com`; keying on that address would file every LinkedIn recruiter
Joel ever hears from as one person.

For `linkedin`, use the **sender display name from the `From:` header**, lowercased with
non-alphanumerics collapsed to hyphens — `Jack Dahler` becomes `jack-dahler`.

This used to say "use the profile slug from their message or profile link", and **an InMail
body contains no profile slug**. The only LinkedIn URL in one is the messaging thread. The
rule was unfollowable, so the capture step was skipped every time and the recruiter's name
ended up as prose in `contacts` instead: 40+ InMails since 14 July produced **zero** LinkedIn
recruiter records, while nine tracked roles named their recruiter in a field no query reads.

Not the thread id, though it is always present: that identifies the conversation, so the same
recruiter opening a second thread becomes a second recruiter, each with one role — which is
the exact number the Recruiters card exists to disprove. Two people who genuinely share a
name will merge, and a merge is visible and fixable where a split is neither.

If the same firm pitches again, that is a new role and a new call — never overwrite the old one.
Two people at one agency (AceStack wrote from both `gautamk@` and `dhruvr@`) are two recruiters.

Score each role and put `Match Score: X/100` plus a one-line rationale and the top gaps in
`notes`:

- **Stack** — TypeScript, React, Node.js, GraphQL, JavaScript, Hack/PHP are the core;
  Python, SQL, AWS, Docker, Mongo, Postgres, Java are exposure only.
- **Seniority** — 2-5 years fits. A hard 5+ requirement is a real miss, not a stretch.
- **Shape** — AI and product engineering score high; infra, ML research, embedded and
  data-engineering score low.
- **Location** — NYC or remote preferred; onsite anywhere else is a flag.

**60 or above reaches the gate**; below that the row is written and nothing is surfaced. An
Alibaba Cloud DevOps or embedded firmware pitch scores in the teens and stays silent, while a
genuinely matched inbound role still gets its chance at a task. Anything already tracked is
not re-scored.

**Roles score individually; the thread produces at most one task.** Step 5 is the only thing
that creates tasks, and its `thread:<id>` duplicate check already collapses several qualifying
roles from one email into a single interruption. Do not create a task here, and do not create
one per role.

**Never advance a status on a message you cannot read.** Indeed and some ATS portals send
"you have a new message" with the body behind a login. That is an `unsure` item worth a task,
but the row stays where it is: the hidden text may be an interview request or a rejection,
and guessing either way is a silent wrong write.

---

## Step 5 — The gate, and the tasks that survive it

Task list: `My Tasks`. **Every** candidate passes through this gate — `human_action`,
`deadline`, `unsure`, and any `recruiter_outreach` scoring 60+. No category is exempt.

The score and the gate answer different questions. The score asks *is this role worth Joel's
attention?* The gate asks *is the ball in Joel's court right now?* A 72/100 role he has
already replied to earns no task until they answer.

### The three tests, in order

1. **Who spoke last?** If Joel did, he is waiting on them. No task. Step 2's grouping catches
   most of these for free; confirm against the thread you read. Chasing a recruiter who owes
   *him* a reply belongs to the follow-up skills, not here.
2. **Did they actually ask for something?** `contains_ask` — a question mark or an imperative
   aimed at Joel. *"Let me know which would be your favorite one"*, *"could you please share
   a few times?"* and *"Have you managed to answer the screening questions"* all qualify.
   *"I will be sending the job details to you shortly"* does not: he owes Joel, not the
   reverse. **A `deadline` satisfies this test by definition** — a scheduled interview or an
   expiring assessment is an ask whether or not it is phrased as one.
3. **Is it only a sign-off?** `detect_closing_statement`. *"Thanks!"*, *"Sounds good!"*,
   *"Okay cool, I will keep you updated :)"*, *"Will keep you posted regarding your
   application"* — the exchange is complete and the next move is theirs. Test 2 has strict
   precedence: an ask anywhere in the message defeats a sign-off, because recruiters wrap
   real requests in friendly packaging. The same goes for logistics that have already expired
   (*"I'll be 3 minutes"*) and for bare attachments (*"Job spec"*).

A thread that fails any test is still worth a tracker note if it moved the process — it just
does not interrupt.

**Read for a rejection before making a task to read something.** A thread can go quiet
because it ended badly, and "go and read this" is a wasted errand when the answer is no. Run
`detect_rejection` first; if it fires, this is a `rejection` — set the row and stay silent.
Only when the text genuinely is not available — Indeed's login-gated messages — does the
"cannot read" rule apply.

### Writing the task

**Check for duplicates first.** Call `mcp__gtasks__list` and skip creation if an open task
already carries this `thread:<id>`. That key is exact; a title comparison is not, and this is
what keeps re-runs clean.

- **Title** — the action and who it concerns: `Reply to <Person> (<Company>) — <what they
  want>`. Never a bare subject line.
- **`unsure` items get a different verb**: `Check <Person> (<Company>) — <what is unknown>`,
  never `Reply to`. The notes must say plainly what could not be determined and that the row
  was left untouched. The task list must not assert an obligation it has not verified.
- **Due** — the deadline if one exists; the day before an interview for prep; otherwise
  tomorrow.
- **Notes** — `thread:<Thread ID>` on the first line, then sender name and address, a
  verbatim quote of what they asked, any link or portal URL, the tracker status, and whether
  the company is tracked at all.

```
Check JustPower LLC — outcome unknown, body behind a login

  thread:1a02060e9e3ab049
  from: no-reply@indeed.com (portal message, text not retrievable)
  tracker: Applied — row left unchanged
  may be a rejection; open the portal to find out
```

The notes are the point: Joel should be able to act without going back to the inbox.

### Superseding a task the mail has overtaken

Before finishing, check open tasks against the threads seen this run. When a later message
resolves a thread that already has an open task — a rejection arrives, or Joel replied —
append a line to its notes with `mcp__gtasks__update` and **leave it open**:

```
  [SUPERSEDED 2026-08-25: rejection received; row set to Rejected]
```

Do not complete it and do not delete it. Triage must not be able to make work disappear on a
mis-classification; Joel ticks it off himself.

---

## Step 5b — Draft the reply, where a draft is worth having

A task that says "reply to this" still leaves the writing to Joel. Where the reply is
predictable, leave a Gmail draft beside it with `mcp__gmail_personal__draft_email`, and say
in the task notes that a draft is waiting.

Draft only for:

- **`recruiter_outreach` scoring 60 or above** — a cold pitch worth answering.
- **`human_action` where a recruiter asked something answerable from what is already known** —
  availability from the calendar, a role preference, confirmation of interest.

Do **not** draft when the answer is Joel's alone to give: salary expectations, why he left a
job, which of three roles he prefers, anything needing judgement about his own history. A
confident draft of something only he can answer is worse than no draft, because it invites
sending without thinking. Never draft for an `unsure` item — by definition you do not know
what you are answering.

**Primary inbox only.** There is no drafting from `ajoelcrist@` until Joel decides which
address should reply to LinkedIn threads; `gmail_alt` has read tools only.

Follow the `outreach-email` skill's format and constraints — that skill owns the voice, and
this one should not grow a second copy of it. Lead with the Meta experience, keep it to
roughly 120-150 words, and never name an employer in a subject line.

Drafts are never sent. Triage does not send email; it leaves work ready for Joel to review.

---

## Step 6 — Record what happened

- **An interview was booked** (mail names an agreed date *and* time — a confirmation, a
  calendar invite, an "you're all set for Tuesday at 2"): `jobs_db.add_interview` with
  `scheduled_date` and no `occurred_date`. A date still ahead puts it in the "Coming up"
  table; a date already past is counted on the card's "no outcome recorded" line instead,
  since the table is future-only. Either way it is visible, and either way
  `mark_interview_occurred()` is what clears it once the round has actually happened.

  Recording a booking **cannot** move any rate. `classify_interviews()` drops
  booked-but-not-held rounds before `interview_stats()` sees them, and `add_interview`'s
  own docstring is explicit that only `occurred_date` makes a round count toward an
  outcome. An earlier version of this skill banned recording invites to protect the funnel;
  that protection now lives in the data layer, and the ban only lost the dates. Do not
  reinstate it.

  **A time must actually be agreed.** "Can you send some availability?" or a bare
  scheduling link is not a booking — move the status and leave the round alone. Writing a
  guessed date puts a fiction on the card, which is worse than the gap it fills.

- **An interview occurred** (a screen took place, a thank-you or outcome references it):
  `jobs_db.add_interview` with `occurred_date`. Only rounds that actually happened, and
  never a cancelled one. This table feeds the funnel stats and cannot be rebuilt from
  anywhere else. If the round was already recorded as booked, use
  `jobs_db.mark_interview_occurred(<id>)` rather than adding a second row.

  **Only against a row that already exists.** `add_interview` keys off the full composite
  `(company, date_added, position_title, link)` and does not check that a job matches, so a
  round recorded for an untracked company attaches to nothing: it still counts in
  `interview_stats` and the funnel while being unreachable from the table — a number Joel
  cannot click through to. Since triage no longer creates rows, this is now reachable. If
  the job is untracked, skip the round and let the gate task carry it; record it once the
  row exists.
- **A row was acted on**: `jobs_db.update_followup_log` with today's date, so "have I dealt
  with this" stops being invisible.
- **Joel answered a recruiter**: `mcp__job_tracker__record_recruiter_reply` with their
  `identity` and the sent message's id. Step 2 already drops threads whose newest message is
  `is_from_owner` — record the reply *before* dropping one that belongs to a known recruiter,
  or the only evidence he engaged is lost. Step 5b's drafts are not replies; record sent mail
  only.

---

## Step 7 — Advance the watermarks

Only after Steps 4–6 succeeded, and **each inbox separately**.

The value is the internal date of the **newest message actually processed** — not the
time captured in Step 1. Those are the same thing only when the run was not capped, and
using the captured time on a capped run skips the unprocessed remainder permanently.

```bash
python3 -c "from src import jobs_db; jobs_db.set_meta('inbox_triage.last_seen','<newest_processed_epoch>')"
python3 -c "from src import jobs_db; jobs_db.set_meta('inbox_triage.last_seen_alt','<newest_processed_epoch>')"
```

If one inbox failed, leave *its* watermark alone and advance the other. The next run
reprocesses, and the `thread:<id>` duplicate check makes that safe.

Never write a *label* to the mailbox to mark progress. A `triaged` label was considered
and rejected: it would break exactly this property — a failed run that had already
labelled its mail would not reprocess — and it writes to Joel's mailbox every day for
the benefit of a value the `meta` table already holds. Triage is read-only against Gmail.

---

## Step 8 — Report

Print a short summary to stdout (the log). Do **not** send email:

```
inbox-triage <date>
  primary: <N> messages since <watermark>   alt: <N> since <watermark>
  threads: <n> grouped, <n> dropped (Joel spoke last)
  human: <n>  deadline: <n>  rejection: <n>  auto_ack: <n>  outreach: <n>  noise: <n>
  gate: <n> passed, <n> stopped (no ask: <n>, sign-off: <n>, score < 60: <n>)
  recruiters: <n> seen (<n> new), <n> roles captured, <n> replies recorded
  tracker: <n> updated, <n> created, <n> ambiguous (asked)
  untracked receipts: <n> not written — <company> (<role or "role not named">), …
  tasks: <n> created, <n> skipped as duplicates, <n> superseded
  interviews recorded: <n> held, <n> booked
  backlog: <n> primary, <n> alt still ahead of the watermark
```

The `backlog` line reports what the 400-per-inbox cap left behind. Zero is the normal
reading. A number that appears once is a burst; a number that never shrinks across runs
means the cap is too low or the schedule too infrequent, and neither is visible without
this line.

`tracker: <n> created` counts recruiter roles only, and must be 0 whenever
`roles captured` is 0 — nothing else writes a row.

The `untracked receipts` line is the whole record that those emails arrived. Name the
company and the role where the mail states one, so a genuinely missing job is visible
and can be added by hand. Expect most of them to appear in the next
`/applypass-inbound` run with a real posting URL; if one never does, that is worth
looking at rather than silently filing.
