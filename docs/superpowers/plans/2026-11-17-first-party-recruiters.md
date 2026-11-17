# First-Party Recruiters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A recruiter who works at the hiring company always gets a job row, a `first_party` flag, and a `★ DIRECT` Google Task at the top of My Tasks.

**Architecture:** A pure matching function in `src/triage_rules.py` decides 1st party from the sender address, company and agency. `record_recruiter_outreach` (the MCP tool) calls it, forces the job row and stores a sticky flag on `recruiters`. The inbox-triage skill uses the same function to mark, date and reorder tasks.

**Tech Stack:** Python 3, sqlite/libsql via `src/jobs_db.py`, FastMCP, pytest. Markdown skill file.

**Spec:** `docs/superpowers/specs/2026-11-17-first-party-recruiters-design.md`

## Global Constraints

- **The repo is public.** Use placeholders only (Acme, Globex, StaffCo, Jane Doe) in code, tests, commit messages and the PR body. No real companies, recruiters or domains from the live tracker.
- **Tests never touch the live database.** `tests/conftest.py` blanks `TURSO_*` for the session. Do not run ad-hoc `python3 -c` writes from this worktree.
- **Snapshot before the merge.** Take the snapshot before the merge that brings in the new column: `turso db shell job-tracker ".dump" > data/turso-snapshot-$(date +%Y%m%d-%H%M%S).sql`.
- **Exact strings:**
  - task title prefix `★ DIRECT · `;
  - job-row notes first line `1st-party recruiter (<domain>)`, or `1st-party recruiter (LinkedIn)` for LinkedIn;
  - task notes line `direct: <domain> matches <company>`.
- **The flag only turns on.** `recruiters.first_party` is set with `MAX`, like `manual_entry`.
- **When unsure, it is not 1st party.** Every unclear input returns `False`.
- **Git and commits.** Use `/usr/bin/git` in this worktree. End each commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A full From header** (`Jane Doe <jane@acme.com>`) still matches. Task 1 has a table row for it.
2. **Mixed case** in the address or company still matches. Task 1 has a table row for it.
3. **A company's no-reply or newsletter address** that was misread as outreach is not 1st party, so no forced row. Task 1 has table rows. The existing `test_sub_threshold_role_records_recruiter_without_a_job_row` must stay green (Task 3).
4. **A blank or malformed sender or company** returns `False` and never raises. Task 1 has table rows.
5. **Re-processing a 1st-party email** leaves one row and one recruiter, the flag still on, and the notes prefix written once. Task 3 has `test_first_party_reprocessing_is_idempotent`.

---

### Task 1: The matching function

**Files:**
- Modify: `src/triage_rules.py`: add a `# ---- first-party senders` section after `unescape_title`.
- Test: `tests/test_triage_rules.py`.
- Also commit: the spec and this plan.

**Interfaces:**
- Produces:
  - `email_domain(sender: str) -> str`: the lowercased host of a bare address or a full From header; `""` when there's no address.
  - `is_first_party(sender_email: str, company: str, agency: str) -> bool` (`agency` required, added in review).

- [ ] **Step 1: Write the failing tests** in `tests/test_triage_rules.py`:

```python
import pytest
from src.triage_rules import email_domain, is_first_party

FIRST_PARTY_CASES = [
    # sender,                     company,                    agency,        expected
    ("jane@acme.com",             "Acme",                     "",            True),
    ("jane@acmehq.com",           "Acme Inc.",                "",            True),
    ("jane@careers.acme.co.uk",   "Acme",                     "",            True),
    ("jane@getacme.io",           "Acme",                     "",            True),
    ("jane@acme.com",             "Acme Labs",                "",            True),
    ("jane@acme.com",             "Acme Technologies, Inc.",  "",            True),
    ("Jane Doe <jane@acme.com>",  "Acme",                     "",            True),
    ("JANE@ACME.COM",             "acme",                     "",            True),
    ("raj@staffco.com",           "Acme",                     "StaffCo",     False),
    ("raj@staffcollc.com",        "StaffCo LLC",              "StaffCo LLC", False),
    ("jane@acme.com",             "Acme",                     "Acme",        False),
    ("raj@gmail.com",             "Acme",                     "",            False),
    ("jane@gem.com",              "Acme",                     "",            False),
    ("mail@ats.rippling.com",     "Acme",                     "",            False),
    ("noreply@acme.com",          "Acme",                     "",            False),
    ("newsletter@acme.com",       "Acme",                     "",            False),
    ("jane@acmeview.ai",          "Acme",                     "",            False),
    ("sam@acme.com",              "Globex",                   "",            False),
    ("",                          "Acme",                     "",            False),
    ("jane@acme.com",             "",                         "",            False),
    ("not-an-address",            "Acme",                     "",            False),
]

@pytest.mark.parametrize("sender,company,agency,expected", FIRST_PARTY_CASES)
def test_is_first_party(sender, company, agency, expected):
    assert is_first_party(sender, company, agency) is expected

def test_email_domain_reads_a_full_from_header():
    assert email_domain("Jane Doe <Jane@Acme.COM>") == "acme.com"

def test_email_domain_is_blank_without_an_address():
    assert email_domain("not-an-address") == ""
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m pytest tests/test_triage_rules.py -q`
Expected: collection error, `ImportError: cannot import name 'email_domain'`.

- [ ] **Step 3: Implement both functions in `src/triage_rules.py`**

- **`email_domain`:** use `email.utils.parseaddr`, then take the part after `@`, lowercased.
- **Constants:** module-level tuples with these minimums:
  - `_FREE_MAIL`: gmail.com, googlemail.com, outlook.com, hotmail.com, live.com, yahoo.com, icloud.com, me.com, aol.com, proton.me, protonmail.com.
  - `_RELAY_LABELS`, matched against the main label: greenhouse, lever, ashbyhq, gem, rippling, workday, myworkday, paraform, dice, indeed, linkedin, smartrecruiters, workable, jobvite, icims.
  - `_NO_PERSON_LOCALS`, matched against the local part: noreply, no-reply, donotreply, do-not-reply, newsletter, news, notifications, marketing, info, hello.
- **The match:**
  1. False if `agency.strip()` is non-empty.
  2. False if the domain or company is blank, the domain is free mail, the main label is a relay, or the local part is a no-person address.
  3. **Main label:** drop the TLD. If what remains ends in `co`/`com`/`org`/`net`/`ac`/`gov` and the TLD was two letters, drop that too. Take the last remaining label.
  4. **Company:** lowercase it, drop the words inc, llc, ltd, corp, corporation, co, company, plc, gmbh, technologies, technology, holdings, then strip non-letters and non-digits.
  5. **True** when label == company, or one is the other plus an affix. Affix suffixes: hq, labs, ai, io, app, team, careers, jobs, tech, group, inc. Affix prefixes: get, try, join, use. Check both directions, so `acmehq` and `Acme`, and `acme` and `Acme Labs`, both match.

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m pytest tests/test_triage_rules.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add src/triage_rules.py tests/test_triage_rules.py docs/superpowers/specs/2026-11-17-first-party-recruiters-design.md docs/superpowers/plans/2026-11-17-first-party-recruiters.md
/usr/bin/git commit -m "triage_rules: is_first_party, the sender-belongs-to-the-hiring-company test"
```

---

### Task 2: The `first_party` column

**Files:**
- Modify: `src/jobs_db.py`, in three places:
  - `_ensure_recruiters_schema`, next to the `manual_entry` ALTER;
  - `upsert_recruiter`;
  - `RECRUITER_COLUMNS`.
- Test: `tests/test_recruiters.py`, next to `test_manual_entry_only_ever_turns_on`.

**Interfaces:**
- Produces:
  - `upsert_recruiter(..., first_party: bool = False) -> int`;
  - `get_recruiters()` rows carry `first_party` as 0 or 1, through the existing `r.*`;
  - `"first_party"` in `RECRUITER_COLUMNS`, so the Drive export carries it. A LinkedIn flag can't be rebuilt from mail.

- [ ] **Step 1: Write the failing tests**

```python
def test_first_party_defaults_off(db):
    db.upsert_recruiter("email", "raj@staffco.com", agency="StaffCo")
    assert db.get_recruiters()[0]["first_party"] == 0

def test_first_party_only_ever_turns_on(db):
    db.upsert_recruiter("email", "jane@acme.com", first_party=True)
    db.upsert_recruiter("email", "jane@acme.com", first_party=False)
    assert db.get_recruiters()[0]["first_party"] == 1

def test_first_party_column_is_added_to_an_existing_table(db):
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute(db._RECRUITERS_DDL)          # the pre-column shape
    conn.execute("INSERT INTO recruiters (source, identity, first_seen) "
                 "VALUES ('email', 'jane@acme.com', '2026-11-01')")
    conn.commit(); conn.close()
    db.upsert_recruiter("email", "jane@acme.com", first_party=True)
    assert db.get_recruiters()[0]["first_party"] == 1

def test_first_party_is_exported(db):
    assert "first_party" in db.RECRUITER_COLUMNS
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m pytest tests/test_recruiters.py -q -k first_party`
Expected: FAIL. The first test gets `KeyError: 'first_party'`, and the second gets `TypeError: unexpected keyword argument 'first_party'`.

- [ ] **Step 3: Implement**

- **The column:** `ALTER TABLE recruiters ADD COLUMN first_party INTEGER NOT NULL DEFAULT 0`, wrapped in `try/except _SCHEMA_EXC`.
- **UPDATE branch:** add `first_party = MAX(first_party, ?)`.
- **INSERT:** include the column.
- **Docstring:** one line saying it only ever turns on, like `manual_entry`.
- **Export:** append `"first_party"` to `RECRUITER_COLUMNS`.

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m pytest tests/test_recruiters.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add src/jobs_db.py tests/test_recruiters.py
/usr/bin/git commit -m "recruiters: first_party flag, only ever turns on"
```

---

### Task 3: The tracker tool enforces it

**Files:**
- Modify: `mcp_servers/job_tracker/server.py`, in `record_recruiter_outreach` and `list_recruiters`.
- Test: `tests/test_recruiters.py`, in the `# --- the MCP write path` section, using the existing `srv` fixture and `_call`.

**Interfaces:**
- Consumes: `is_first_party` and `email_domain` from Task 1; `upsert_recruiter(first_party=...)` from Task 2.
- Produces:
  - `record_recruiter_outreach(..., create_job_row: bool = True, first_party: bool = False) -> dict`; the result always carries `"first_party": bool`;
  - `list_recruiters()` items carry `"first_party": bool`.

- [ ] **Step 1: Write the failing tests**

```python
def _acme(srv, **kw):
    base = dict(source="email", identity="jane@acme.com", email="jane@acme.com",
                company="Acme", position_title="Senior Frontend Engineer",
                occurred_date="2026-11-17", name="Jane Doe", message_id="msg-1",
                notes="Match Score: 40/100", create_job_row=False)
    return _call(srv.record_recruiter_outreach, **{**base, **kw})

def test_first_party_email_gets_a_row_below_the_bar(srv):
    out = _acme(srv)
    assert out["first_party"] is True and out["job_row_created"] is True
    assert "link" in out
    assert len(_call(srv.recruiter_roles)) == 1
    assert _call(srv.list_recruiters)[0]["first_party"] is True

def test_first_party_row_notes_name_the_domain(srv):
    out = _acme(srv)
    notes = srv.jobs_db.find_job_by_link(out["link"])["notes"]
    assert notes.startswith("1st-party recruiter (acme.com)")
    assert "Match Score: 40/100" in notes

def test_agency_sender_is_not_first_party(srv):
    out = _acme(srv, identity="raj@staffco.com", email="raj@staffco.com",
                agency="StaffCo")
    assert out["first_party"] is False and out["job_row_created"] is False
    assert _call(srv.recruiter_roles) == []

def test_undisclosed_employer_is_not_first_party(srv):
    out = _acme(srv, identity="raj@staffcollc.com", email="raj@staffcollc.com",
                company="StaffCo LLC", agency="StaffCo LLC")
    assert out["first_party"] is False

def test_linkedin_first_party_needs_the_flag(srv):
    li = dict(source="linkedin", identity="jane-doe",
              email="inmail-hit-reply@linkedin.com", account="alt")
    assert _acme(srv, **li)["first_party"] is False
    out = _acme(srv, **li, message_id="msg-2", first_party=True)
    assert out["first_party"] is True and out["job_row_created"] is True
    assert srv.jobs_db.find_job_by_link(out["link"])["notes"].startswith(
        "1st-party recruiter (LinkedIn)")

def test_first_party_reprocessing_is_idempotent(srv):
    out = _acme(srv); _acme(srv)
    assert len(_call(srv.recruiter_roles)) == 1
    assert len(srv.jobs_db.get_recruiters()) == 1
    notes = srv.jobs_db.find_job_by_link(out["link"])["notes"]
    assert notes.count("1st-party recruiter") == 1
```

- [ ] **Step 2: Fix one existing fixture.**

`test_sub_threshold_then_qualifying_role_creates_the_row_on_the_second_call` files `dana@agency.com` under company `"Agency"` with no `agency`. Under the new rule that is a 1st-party match. Real triage always passes `agency` for an agency recruiter (Task 4 makes it required), so add `agency="Agency"` to both of its calls. That is the whole change: no assertion moves.

- [ ] **Step 3: Run the tests and see them fail**

Run: `python3 -m pytest tests/test_recruiters.py -q -k "first_party or undisclosed or agency_sender"`
Expected: FAIL. The new tests get `KeyError: 'first_party'` or `TypeError: unexpected keyword argument 'first_party'`.

- [ ] **Step 4: Implement**

In `record_recruiter_outreach`, after the existing validation:
- Compute `domain_match = source == "email" and is_first_party(email or identity, company, agency)` and `first = first_party or domain_match`.
- When `first`:
  - set `create_job_row = True`;
  - prefix the job row's notes with `1st-party recruiter (<email_domain(email or identity)>)`, or `(LinkedIn)` for that source, then a newline and the caller's `notes`;
  - pass `first_party=True` to `upsert_recruiter`.
- Always put `"first_party": first` in the result.
- Add a docstring paragraph: the tool forces the row for a 1st-party recruiter whatever `create_job_row` says, and LinkedIn relies on the caller's flag.
- In `list_recruiters`, add `"first_party": bool(r.get("first_party"))`.
- Import with `from src.triage_rules import email_domain, is_first_party`.

- [ ] **Step 5: Run the whole suite and see it pass**

Run: `python3 -m pytest -q`
Expected: all pass, including `test_sub_threshold_role_records_recruiter_without_a_job_row`, which is unchanged.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add mcp_servers/job_tracker/server.py tests/test_recruiters.py
/usr/bin/git commit -m "record_recruiter_outreach: a 1st-party recruiter always gets a job row"
```

---

### Task 4: Triage puts them at the front of the line

**Files:**
- Modify: `.claude/skills/inbox-triage/SKILL.md`.

**Interfaces:**
- Consumes:
  - `is_first_party` and `email_domain` from Task 1;
  - the `first_party` argument and result key from Task 3;
  - `mcp__gtasks__move(taskListId, taskId)`. With no `previous`, it places the task first.

- [ ] **Step 1: Edit "The predicates".** Add `is_first_party` to the import line in the example snippet. Add one sentence: it answers "does this sender work at the hiring company?" and returns `False` whenever unsure.

- [ ] **Step 2: Edit Step 3, Classify.**
  - Add a short "1st-party senders" subsection. It defines 1st party and says to run `is_first_party(sender, company)` for every human message tied to a company.
  - Amend the `human_action` vs `recruiter_outreach` override: a 1st-party pitch for a role the user never applied to is captured with `record_recruiter_outreach` even when it names the user.
  - Add the LinkedIn rule: when the signature or headline places them at the hiring company, it's 1st party. Otherwise it isn't.

- [ ] **Step 3: Edit the Step 4 capture table.**
  - The `agency` row becomes: "the staffing firm, as signed. **Blank when the recruiter works for the hiring company.** Required for every agency, including when the employer is undisclosed: left blank there, the agency's own domain matches and it is marked 1st party."
  - Add a `first_party` row: "`true` for a LinkedIn recruiter whose signature places them at the hiring company; otherwise omit. The tool checks email domains itself."
  - Add to the `create_job_row` row: "the tool forces it to true for a 1st-party recruiter."

- [ ] **Step 4: Edit Step 5, the gate.**
  - Add a "1st-party pitches" paragraph. They skip the 60 bar and tests 2 and 3, and test 1 still applies. Every other message from someone at the hiring company takes the normal gate.
  - Under "Writing the task", any task whose sender is 1st party gets:
    - the title prefix `★ DIRECT · `, with an example;
    - due today, the day triage runs;
    - a notes line `direct: <domain> matches <company>`, or `direct: LinkedIn, signature names <company>`, plus `Match Score: X/100` for pitches.
  - Add a "Front of the line" paragraph. After all tasks are created, list the open tasks and `mcp__gtasks__move` each open `★ DIRECT` task with no `previous`, oldest first, so the newest ends on top. Moving is not completing or deleting, so "never destroy work" holds.

- [ ] **Step 5: Edit Step 8, Report.** Add the line `direct: <n> tasks, <n> recruiters flagged`.

- [ ] **Step 6: Verify the edits**

Run: `grep -c "★ DIRECT" .claude/skills/inbox-triage/SKILL.md; grep -n "is_first_party\|first_party" .claude/skills/inbox-triage/SKILL.md`
Expected: at least 3 `★ DIRECT` hits, plus hits in "The predicates", Step 3, Step 4 and Step 5. Read Step 5 top to bottom once. The 1st-party exception must not contradict "No category is exempt" (reword that line to name the exception).

- [ ] **Step 7: Commit**

```bash
/usr/bin/git add .claude/skills/inbox-triage/SKILL.md
/usr/bin/git commit -m "inbox-triage: 1st-party recruiters always get a ★ DIRECT task at the top"
```

---

### Task 5: Ship

- [ ] **Step 1: Run the full suite.** Run `python3 -m pytest -q`. Expected: all pass.
- [ ] **Step 2: Scan for real names.** Run `/usr/bin/git diff origin/main --stat` and `/usr/bin/git diff origin/main | grep -niE "@[a-z0-9-]+\.(com|io|ai|net)"`. Every hit must be a placeholder: acme, globex, staffco, gmail, gem, rippling, linkedin, or an existing fixture.
- [ ] **Step 3: Snapshot the live database.** Run `turso db shell job-tracker ".dump" > data/turso-snapshot-$(date +%Y%m%d-%H%M%S).sql` from the main checkout, where `data/` lives. Check that the file is non-empty and ends with `COMMIT;`.
- [ ] **Step 4: Push and open the PR** against `main`. The body is placeholders only and ends with the Claude Code attribution line.
- [ ] **Step 5: Hand Joel the merge.** Give Joel `! gh pr merge <n> -R JAbreu96/jobTrax --merge --admin`; Claude can't run the admin merge.
