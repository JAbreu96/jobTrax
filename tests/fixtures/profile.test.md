---
owner_name: Test Owner
notify_email: owner@example.test
outreach_email: outreach@example.test
owner_emails:
  - owner@example.test
  - outreach@example.test
linkedin_forward_email: outreach+linkedin@example.test
linkedin_url: linkedin.com/in/test-owner
spreadsheet_id: TESTSHEETID000000000000000000000000000000000
sheet_worksheet: Sheet1
resume_doc_id: TESTRESUMEDOCID0000000000000000000000000000
resume_folder_id: TESTFOLDERID000000000000000000000
ws5_record_start: "2026-01-04"
ws5_output_dir: /tmp/ws5-test
---

# Test profile

Pinned by `tests/conftest.py` so the suite asserts against fixed values rather
than whatever `config/profile.md` happens to hold on the machine running it.
Without this, `test_triage_rules` passes on the author's laptop and fails on a
fresh fork -- the exact class of bug the config extraction exists to remove.

Every address here is under `.test`, a reserved TLD that can never resolve, so a
test that accidentally sends mail has nowhere to send it.

## Sender background

**Current/recent role:** Software Engineer at Example Corp, 2024 - present

**Highlights (lead with these, in priority order):**

- Accomplished X, as measured by Y, by doing Z

## Candidate profile (for scoring)

- **Stack:** Python
- **Experience:** ~2 years; target roles asking for 0-3
- **Location:** Testville, TS
