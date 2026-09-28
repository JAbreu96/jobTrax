// The in-page capture's pure helpers. Fixtures are synthetic, as in
// detect.test.mjs: data/ is gitignored because it holds personal info, so a real
// capture never becomes test data. The envelope shape is copied from a real
// response with every value invented.

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  readPage, isAppliedPage, mergePages, missingPages, pickNext, timestamp,
} = require("./inpage.js");

const rec = (id, submitted = "2026-09-01T10:00:00.000Z") => ({
  _api_c2_match_id: id,
  _api_c2_company_name: `Company ${id}`,
  _api_c2_application_submitted_bool: true,
  _api_c2_application_submitted_date: submitted,
});

// What Bubble's API connector hands the page: the connector's body flattened
// into dotted keys on one object, beside Bubble's own bookkeeping.
const bubbleBody = (page, records, { totalPages = 3, totalRecords = 250 } = {}) => ({
  properties: { url_params_page: String(page) },
  ret: {
    "_api_c2_body.data": records,
    "_api_c2_body.page": page,
    "_api_c2_body.pageSize": 100,
    "_api_c2_body.remainingPages": totalPages - page,
    "_api_c2_body.totalPages": totalPages,
    "_api_c2_body.totalRecords": totalRecords,
    _api_c2_returned_an_error: false,
  },
});

test("reads records and page numbers out of a flattened Bubble envelope", () => {
  const page = readPage(bubbleBody(2, [rec(1), rec(2)]));
  assert.equal(page.records.length, 2);
  assert.equal(page.page, 2);
  assert.equal(page.pageSize, 100);
  assert.equal(page.totalPages, 3);
  assert.equal(page.totalRecords, 250);
});

test("reads un-flattened page numbers too", () => {
  // If Bubble ever stops flattening, the suffix match still finds bare keys.
  const page = readPage({ data: [rec(1)], page: 4, totalPages: 9 });
  assert.equal(page.page, 4);
  assert.equal(page.totalPages, 9);
});

test("a body without export records is not a page", () => {
  assert.equal(readPage({ ret: { "_api_c2_body.data": [] } }), null);
  assert.equal(readPage({ ret: { rows: [{ id: 1 }] } }), null);
  assert.equal(readPage(null), null);
  assert.equal(readPage("text"), null);
});

test("a page with any unsubmitted record is not from Job Applied", () => {
  // Job Matches answers from the same endpoint in the same shape; the first
  // live run captured it by mistake when a tab click was swallowed.
  assert.equal(isAppliedPage([rec(1), rec(2)]), true);
  assert.equal(isAppliedPage([rec(1), { ...rec(2), _api_c2_application_submitted_bool: false }]),
               false);
});

test("merging dedupes on match_id across pages", () => {
  // The list is live: a record submitted mid-run shifts every later page by
  // one, so the same record can arrive on two consecutive pages.
  const merged = mergePages({ 1: [rec(1), rec(2)], 2: [rec(2), rec(3)] });
  assert.deepEqual(merged.map((r) => r._api_c2_match_id), [1, 2, 3]);
});

test("reports which pages never arrived", () => {
  assert.deepEqual(missingPages({ 1: [], 3: [] }, 4), [2, 4]);
  assert.deepEqual(missingPages({ 1: [], 2: [] }, 2), []);
});

// Rectangles as the pager lays them out: prev arrow, page number, next arrow,
// and a card's like button further right on the same row (the pager floats
// over the job list, so card buttons do share its row).
const btn = (text, left, width = 30, top = 870) =>
  ({ text, left, right: left + width, top, bottom: top + 30 });

test("picks the arrow right of the page number, not the one left of it", () => {
  // The two arrows share a generated class. Choosing by class sent the first
  // real run backwards from page 7.
  const prev = btn("", 20), number = btn("7", 60), next = btn("", 100), like = btn("", 370);
  assert.equal(pickNext([prev, number, next, like], number), next);
});

test("on page 1 there is no previous arrow and next is still found", () => {
  const number = btn("1", 20), next = btn("", 70);
  assert.equal(pickNext([number, next], number), next);
});

test("ignores textless buttons on another row", () => {
  const number = btn("3", 20), elsewhere = btn("", 70, 30, 400);
  assert.equal(pickNext([number, elsewhere], number), null);
});

test("timestamps match the archive's filename convention", () => {
  assert.equal(timestamp(new Date(2026, 8, 28, 11, 5, 3)), "2026-09-28T11-05-03");
});
