// The in-page capture's helpers. Fixtures are synthetic, as in detect.test.mjs:
// data/ is gitignored because it holds personal info, so a real capture never
// becomes test data. The record and envelope shapes are copied from a real
// /api/jobListingMatches response with every value invented.

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  pageUrl, isAppliedPage, reachedCutoff, slim, mergePages, missingPages, timestamp, capture,
} = require("./inpage.js");

const ORIGIN = "https://app.example.invalid";

const rec = (id, submitted = "2026-09-01T10:00:00.000Z", extra = {}) => ({
  match_id: id,
  company_name: `Company ${id}`,
  application_submitted_bool: true,
  application_submitted_date: submitted,
  current_stage_type_key: "job_applied",
  ...extra,
});

test("asks for the Application column, newest submission first", () => {
  const url = new URL(pageUrl(ORIGIN, 42, 3, 500));
  assert.equal(url.pathname, "/api/jobListingMatches");
  const p = Object.fromEntries(url.searchParams);
  assert.equal(p.jsp_id, "42");
  assert.equal(p.current_stage_type_key, "job_applied");
  assert.equal(p.page, "3");
  assert.equal(p.pageSize, "500");
  assert.equal(p.sortBy, "application_submitted_date");
  assert.equal(p.sortOrder, "desc");
  // Left true, the server sorts by match score first and the date order --
  // which the cutoff depends on -- is gone.
  assert.equal(p.sortFirstByMatchScoreDesc, "false");
});

test("a page holding a Job Matches record is not from the Application column", () => {
  // Job Matches answers from the same endpoint in the same shape.
  assert.equal(isAppliedPage([rec(1), rec(2)]), true);
  assert.equal(isAppliedPage([rec(1), rec(2, undefined, { current_stage_type_key: "job_matched" })]),
               false);
  assert.equal(isAppliedPage([rec(1), rec(2, undefined, { application_submitted_bool: false })]),
               false);
});

test("a page reaches the cutoff once any record was submitted before it", () => {
  const page = [rec(1, "2026-09-27T09:00:00.000Z"), rec(2, "2026-09-25T23:59:00.000Z")];
  assert.equal(reachedCutoff(page, "2026-09-26"), true);
  assert.equal(reachedCutoff(page, "2026-09-25"), false);
});

test("no cutoff means page everything", () => {
  assert.equal(reachedCutoff([rec(1, "2020-01-01T00:00:00.000Z")], ""), false);
  assert.equal(reachedCutoff([rec(1, "2020-01-01T00:00:00.000Z")], undefined), false);
});

test("a record with no submission date never trips the cutoff", () => {
  assert.equal(reachedCutoff([rec(1, null)], "2026-09-26"), false);
});

test("slimming drops every description field and leaves the record alone", () => {
  const full = rec(1, undefined, {
    job_description: "<p>long</p>", job_description_raw_html: "<p>raw</p>",
    job_description_truncated: "long", job_title: "Engineer",
  });
  const out = slim(full);
  assert.equal("job_description" in out, false);
  assert.equal("job_description_raw_html" in out, false);
  assert.equal("job_description_truncated" in out, false);
  assert.equal(out.job_title, "Engineer");
  assert.equal(full.job_description, "<p>long</p>");
});

test("merging dedupes on match_id across pages", () => {
  // The list is live: a record submitted mid-run shifts every later page by
  // one, so the same record can arrive on two consecutive pages.
  const merged = mergePages({ 1: [rec(1), rec(2)], 2: [rec(2), rec(3)] });
  assert.deepEqual(merged.map((r) => r.match_id), [1, 2, 3]);
});

test("reports which pages never arrived", () => {
  assert.deepEqual(missingPages({ 1: [], 3: [] }, 4), [2, 4]);
  assert.deepEqual(missingPages({ 1: [], 2: [] }, 2), []);
});

test("timestamps match the archive's filename convention", () => {
  assert.equal(timestamp(new Date(2026, 8, 28, 11, 5, 3)), "2026-09-28T11-05-03");
});

// --- capture, against a fake ApplyPass ---------------------------------------

/**
 * Serves `records` (newest first) the way /api/jobListingMatches does.
 * `beforePage(n, records)` runs before page n is served, so a test can land a
 * new application mid-run. Records whatever was requested in `calls`.
 */
function fakeApplyPass(records, { beforePage = () => {}, me = { jsp_id: 7 } } = {}) {
  const calls = [];
  const getJson = async (url) => {
    const u = new URL(url);
    calls.push(u.pathname + (u.searchParams.get("page") ? `#${u.searchParams.get("page")}` : ""));
    if (u.pathname === "/api/me") return me;
    const page = Number(u.searchParams.get("page"));
    const size = Number(u.searchParams.get("pageSize"));
    beforePage(page, records);
    return {
      page, pageSize: size,
      totalPages: Math.ceil(records.length / size),
      totalRecords: records.length,
      data: records.slice((page - 1) * size, page * size),
    };
  };
  return { getJson, calls };
}

const day = (d) => `2026-10-${String(d).padStart(2, "0")}T12:00:00.000Z`;
// Ten records, one a day, Oct 10 down to Oct 1.
const tenDays = () => Array.from({ length: 10 }, (_, i) => rec(`m${10 - i}`, day(10 - i)));

test("a full capture reads every page", async () => {
  const { getJson } = fakeApplyPass(tenDays());
  const out = await capture(getJson, ORIGIN, { pageSize: 3 });
  assert.equal(out.totalPages, 4);
  assert.deepEqual(missingPages(out.pages, out.totalPages), []);
  assert.equal(mergePages(out.pages).length, 10);
  assert.equal(out.stoppedAt, null);
});

test("an incremental capture stops at the first page reaching the cutoff", async () => {
  const { getJson, calls } = fakeApplyPass(tenDays());
  // Page 1: Oct 10-8, page 2: Oct 7-5 -- Oct 5 is before the cutoff.
  const out = await capture(getJson, ORIGIN, { pageSize: 3, stopBefore: "2026-10-06" });
  assert.equal(out.stoppedAt, 2);
  assert.deepEqual(calls, ["/api/me", "/api/jobListingMatches#1", "/api/jobListingMatches#2"]);
});

test("an application landing mid-run is caught by re-reading page 1", async () => {
  const { getJson } = fakeApplyPass(tenDays(), {
    beforePage: (n, records) => { if (n === 2 && records.length === 10) records.unshift(rec("new", day(11))); },
  });
  const out = await capture(getJson, ORIGIN, { pageSize: 3 });
  const ids = mergePages(out.pages).map((r) => r.match_id);
  assert.ok(ids.includes("new"));
  assert.equal(ids.length, 11);
});

test("descriptions are dropped as pages arrive", async () => {
  const { getJson } = fakeApplyPass([rec(1, day(1), { job_description: "<p>x</p>" })]);
  const out = await capture(getJson, ORIGIN);
  assert.equal("job_description" in out.pages[1][0], false);
});

test("a page from outside the Application column fails the run", async () => {
  const { getJson } = fakeApplyPass([rec(1), rec(2, undefined, { current_stage_type_key: "job_matched" })]);
  await assert.rejects(capture(getJson, ORIGIN), /outside the Application column/);
});

test("an account with no applications captures nothing, without paging forever", async () => {
  const { getJson, calls } = fakeApplyPass([]);
  const out = await capture(getJson, ORIGIN);
  assert.equal(mergePages(out.pages).length, 0);
  assert.equal(calls.length, 2);
});

test("a missing jsp_id fails before any page is requested", async () => {
  const { getJson, calls } = fakeApplyPass(tenDays(), { me: {} });
  await assert.rejects(capture(getJson, ORIGIN), /no jsp_id/);
  assert.deepEqual(calls, ["/api/me"]);
});
