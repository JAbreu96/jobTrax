// Fixtures here are synthetic on purpose. .gitignore excludes data/ wholesale
// because it "contains personal/contact info", so a real capture must never be
// committed as test data. Invented companies only.

import { test } from "node:test";
import assert from "node:assert/strict";
import { findExportRecords, recordId } from "./detect.mjs";

const rec = (id, company) => ({
  _api_c2_match_id: id,
  _api_c2_company_name: company,
  _api_c2_job_url: `https://example.invalid/jobs/${id}`,
});

test("finds records wrapped in an envelope", () => {
  // The shape parse_applied_jobs.py already unwraps, and the reason the walk
  // exists at all.
  const found = findExportRecords({ data: [rec(1, "Acme"), rec(2, "Globex")] });
  assert.equal(found.length, 2);
  assert.equal(found[0]._api_c2_company_name, "Acme");
});

test("finds the Next.js app's bare-key records", () => {
  // ApplyPass dropped the `_api_c2_` prefix when it left Bubble.
  const found = findExportRecords({ page: 1, data: [{ match_id: 9, company_name: "Acme" }] });
  assert.equal(found.length, 1);
  assert.equal(recordId(found[0]), 9);
  assert.equal(recordId(rec(3, "Globex")), 3);
});

test("finds records in an envelope the Python parser does not know", () => {
  // The whole point of walking rather than checking known keys: ApplyPass can
  // rename this and the panel keeps working.
  const found = findExportRecords({ payload: { items: [rec(1, "Initech")] } });
  assert.equal(found.length, 1);
});

test("finds a bare array", () => {
  const found = findExportRecords([rec(1, "Acme"), rec(2, "Globex")]);
  assert.equal(found.length, 2);
});

test("finds a single record that is not in an array", () => {
  const found = findExportRecords(rec(7, "Hooli"));
  assert.deepEqual(found, [rec(7, "Hooli")]);
});

test("an empty array is not an export", () => {
  // Must not report a match, or the panel would list a row holding nothing.
  assert.equal(findExportRecords([]), null);
  assert.equal(findExportRecords({ data: [] }), null);
});

test("an array of unrelated objects is not an export", () => {
  assert.equal(findExportRecords([{ id: 1 }, { id: 2 }]), null);
});

test("non-objects are not exports", () => {
  for (const body of [null, 0, "", "a string", true]) {
    assert.equal(findExportRecords(body), null);
  }
});

test("keeps the records out of a mixed array", () => {
  // A page carrying a trailing summary object should still be captured.
  const found = findExportRecords([rec(1, "Acme"), { total: 389 }]);
  assert.equal(found.length, 1);
  assert.equal(found[0]._api_c2_match_id, 1);
});

test("stops at maxDepth instead of recursing forever", () => {
  let body = rec(1, "Acme");
  for (let i = 0; i < 20; i++) body = { nested: body };
  assert.equal(findExportRecords(body, 3), null);
});
