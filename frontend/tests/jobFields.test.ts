/*
 * Port of tests/js/job_fields_checks.js's pure-helper checks, for
 * frontend/src/lib/jobFields.ts.
 *
 * Check names are kept as the `it` text so the two suites can be diffed by
 * eye while both exist -- that matters because job_fields_checks.js is
 * deleted in Phase 5, once the code it covers is gone, and the only evidence
 * the coverage survived the port is this name-for-name correspondence.
 *
 * Only the checks that cover a helper ported to jobFields.ts are here. The
 * DOM/behaviour checks in the original (recruiterBadge, the builders, table:/
 * modal:, stopClicks) cover code that ships in Phases 2, 3 and 5.
 */
import { describe, it, expect } from "vitest";
import type { Job } from "../src/api/types";
import * as jobFields from "../src/lib/jobFields";
import {
  rowKey,
  localISODate,
  startOfWeekISO,
  isValidISODate,
  parseFollowupLog,
  serializeFollowupLog,
  jobKeyFields,
  recruiterLabel,
  SORT_COLUMNS,
  compareJobs,
  nextSortDirection,
  type SortColumn,
} from "../src/lib/jobFields";

// Builds minimal jobs for the sort checks, matching the original's `jobs()`
// helper: only the three fields any given check varies are meaningful.
function jobs(
  ...specs: Array<[string, string, string]>
): Job[] {
  return specs.map(([company, date_added, status]) => ({
    company,
    date_added,
    status,
    position_title: "",
    location: "",
    link: "",
    contacts: "",
    notes: "",
    outreach_date: "",
    date_applied: "",
    followup_log: "",
    recruiter_id: null,
    recruiter_name: null,
    recruiter_agency: null,
    recruiter_from_triage: false,
  }));
}

function sampleJob(): Job {
  return {
    company: "Acme",
    date_added: "2026-01-02",
    position_title: "Developer",
    location: "Remote",
    link: "https://example.invalid/jobs/1",
    status: "Applied",
    contacts: "",
    notes: "A note with **bold** in it.",
    outreach_date: "",
    date_applied: "",
    followup_log: "2026-01-02",
    recruiter_id: null,
    recruiter_name: null,
    recruiter_agency: null,
    recruiter_from_triage: false,
  };
}

describe("jobFields", () => {
  /*
   * The original check asserted against a declared manifest (EXPORTS in
   * job_fields_checks.js), not against a list of things already imported --
   * which would be tautological, since a missing named import fails the
   * typecheck before this test ever runs. Kept as a manifest for the same
   * reason: it catches a helper quietly dropped from BOTH the module and the
   * rest of this file, which an import list cannot.
   */
  const PURE_HELPER_SURFACE = [
    "rowKey",
    "localISODate",
    "startOfWeekISO",
    "isValidISODate",
    "parseFollowupLog",
    "serializeFollowupLog",
    "jobKeyFields",
    "recruiterLabel",
    "compareJobs",
    "nextSortDirection",
  ] as const;

  it("module loads and exports its public surface", () => {
    const mod = jobFields as unknown as Record<string, unknown>;
    for (const name of PURE_HELPER_SURFACE) {
      expect(typeof mod[name], `missing export ${name}`).toBe("function");
    }
    expect(typeof SORT_COLUMNS).toBe("object");
  });

  /*
   * job_fields.js's EXPORTS list is the full inventory of what this rewrite
   * owes, and it is deleted along with that file in Phase 5. Recorded here so
   * the checklist outlives it:
   *
   *   Phase 1 (this file): rowKey, localISODate, startOfWeekISO,
   *     isValidISODate, parseFollowupLog, serializeFollowupLog, jobKeyFields,
   *     recruiterLabel
   *   Phase 2 (lib/markdown.ts + <MarkdownField>): renderMarkdownInto,
   *     appendInlineMarkdown, checkMarkdownOverflow, refreshMarkdownFields
   *   Phase 3 (useJobFieldEditing + <RecruiterField>): saveField, deleteJob,
   *     loadRecruiters, recruiterBadge, saveJobRecruiter, createRecruiter,
   *     create
   *   Phase 0 (already ported, as api/client.ts): postJSON
   */

  it("rowKey joins the four-part composite key", () => {
    expect(
      rowKey({ company: "Acme", date_added: "2026-01-02", position_title: "Dev", link: "https://x" }),
    ).toBe("Acme::2026-01-02::Dev::https://x");
  });

  it("rowKey leaves the optional halves blank rather than undefined", () => {
    expect(rowKey({ company: "Acme", date_added: "2026-01-02" })).toBe("Acme::2026-01-02::::");
  });

  it("localISODate pads month and day", () => {
    expect(localISODate(new Date(2026, 0, 5))).toBe("2026-01-05");
  });

  it("localISODate reads local time, not UTC", () => {
    // 23:30 local on the 5th is the 6th in UTC for a good part of the world;
    // the follow-up chips date against the user's day, so this must not shift.
    expect(localISODate(new Date(2026, 0, 5, 23, 30))).toBe("2026-01-05");
  });

  it("startOfWeekISO winds back to Sunday", () => {
    // 2026-01-08 is a Thursday.
    expect(startOfWeekISO(new Date(2026, 0, 8))).toBe("2026-01-04");
    // A Sunday is already the start of its week.
    expect(startOfWeekISO(new Date(2026, 0, 4))).toBe("2026-01-04");
  });

  it("isValidISODate accepts a real date and rejects the rest", () => {
    expect(isValidISODate("2026-01-05")).toBe(true);
    expect(isValidISODate("")).toBe(false);
    expect(isValidISODate(null)).toBe(false);
    expect(isValidISODate("05/01/2026")).toBe(false);
    expect(isValidISODate("2026-1-5")).toBe(false);
    expect(isValidISODate("2026-13-01")).toBe(false);
  });

  it("follow-up log round-trips through parse and serialize", () => {
    const raw = "2026-01-02, 2026-01-09";
    expect(serializeFollowupLog(parseFollowupLog(raw))).toBe(raw);
  });

  it("parseFollowupLog drops blanks and surrounding space", () => {
    const tokens = parseFollowupLog(" 2026-01-02 ,, 2026-01-09,");
    expect(tokens.length).toBe(2);
    expect(tokens[0]).toBe("2026-01-02");
    expect(tokens[1]).toBe("2026-01-09");
  });

  it("parseFollowupLog treats a missing log as empty", () => {
    expect(parseFollowupLog(null).length).toBe(0);
    expect(parseFollowupLog(undefined).length).toBe(0);
  });

  it("jobKeyFields blanks every missing half of the key", () => {
    const key = jobKeyFields({ company: "Acme" });
    expect(key).toEqual({ company: "Acme", date_added: "", position_title: "", link: "" });
  });

  it("recruiterLabel pairs the name with the agency", () => {
    expect(recruiterLabel({ name: "Dhruv", agency: "AceStack" })).toBe("Dhruv — AceStack");
    expect(recruiterLabel({ recruiter_name: "Dhruv", recruiter_agency: "AceStack" })).toBe("Dhruv — AceStack");
  });

  it("recruiterLabel falls back when half the pair is missing", () => {
    expect(recruiterLabel({ name: "Dhruv" })).toBe("Dhruv");
    expect(recruiterLabel({ agency: "AceStack" })).toBe("(unnamed) — AceStack");
    expect(recruiterLabel(null)).toBe("");
  });

  it("SORT_COLUMNS names a job field for every sortable column", () => {
    const sample = sampleJob() as unknown as Record<string, unknown>;
    for (const field of Object.values(SORT_COLUMNS)) {
      expect(field in sample).toBe(true);
    }
  });

  it("compareJobs orders ascending and descending", () => {
    const rows = jobs(["Beta", "2026-01-02", "Applied"], ["Alpha", "2026-01-03", "Rejected"]);
    const asc = rows.slice().sort(compareJobs("company", "asc")).map((j) => j.company);
    const desc = rows.slice().sort(compareJobs("company", "desc")).map((j) => j.company);
    expect(asc.join(",")).toBe("Alpha,Beta");
    expect(desc.join(",")).toBe("Beta,Alpha");
  });

  it("compareJobs sorts dates chronologically, not by digit", () => {
    const rows = jobs(["A", "2026-01-09", ""], ["B", "2026-01-10", ""], ["C", "2025-12-31", ""]);
    const asc = rows.slice().sort(compareJobs("date_added", "asc")).map((j) => j.company);
    expect(asc.join(",")).toBe("C,A,B");
  });

  it("a blank sorts last in both directions", () => {
    // A job with no date is not the oldest one; it is the one nobody
    // recorded a date for, and it belongs at the end either way.
    const rows = jobs(["A", "2026-01-02", ""], ["B", "", ""], ["C", "2026-01-01", ""]);
    const asc = rows.slice().sort(compareJobs("date_added", "asc")).map((j) => j.company);
    const desc = rows.slice().sort(compareJobs("date_added", "desc")).map((j) => j.company);
    expect(asc.join(",")).toBe("C,A,B");
    expect(desc.join(",")).toBe("A,C,B");
  });

  it("whitespace counts as blank", () => {
    const rows = jobs(["A", "   ", ""], ["B", "2026-01-01", ""]);
    const asc = rows.slice().sort(compareJobs("date_added", "asc")).map((j) => j.company);
    expect(asc.join(",")).toBe("B,A");
  });

  it("compareJobs ignores case and reads embedded numbers as numbers", () => {
    const rows = jobs(["series 10", "", ""], ["Series 2", "", ""], ["SERIES 1", "", ""]);
    const asc = rows.slice().sort(compareJobs("company", "asc")).map((j) => j.company);
    expect(asc.join(",")).toBe("SERIES 1,Series 2,series 10");
  });

  it("an unknown column leaves the order untouched", () => {
    const rows = jobs(["B", "", ""], ["A", "", ""], ["C", "", ""]);
    // Cast simulates a column read from an untyped source (e.g. a DOM
    // attribute) that turns out not to be one of SORT_COLUMNS's keys.
    const same = rows
      .slice()
      .sort(compareJobs("nonsense" as SortColumn, "asc"))
      .map((j) => j.company);
    expect(same.join(",")).toBe("B,A,C");
  });

  it("sorting is stable, so a tie keeps the order the API sent", () => {
    const rows = jobs(["B", "2026-01-01", ""], ["A", "2026-01-01", ""], ["C", "2026-01-01", ""]);
    const asc = rows.slice().sort(compareJobs("date_added", "asc")).map((j) => j.company);
    expect(asc.join(",")).toBe("B,A,C");
  });

  it("nextSortDirection cycles asc, desc, then off", () => {
    expect(nextSortDirection(null)).toBe("asc");
    expect(nextSortDirection("asc")).toBe("desc");
    expect(nextSortDirection("desc")).toBe(null);
  });
});
