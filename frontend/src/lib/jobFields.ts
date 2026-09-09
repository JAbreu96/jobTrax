/*
 * Pure job-field helpers, ported from src/static/job_fields.js (the table and
 * kanban modal's shared helper module).
 *
 * That file's header explains why it exists: the table (jobs.html) and the
 * kanban modal (kanban.html) edit the same job rows through the same
 * endpoint, and had grown two copies of every builder that drifted apart
 * field by field. The DOM-building half of that file (`create(ctx)` and its
 * builders) is not ported here -- it belongs with the React components that
 * replace it, in later phases. This module carries only the helpers that were
 * already pure: no DOM, no fetch, just data in and data out. That is also why
 * `recruiterBadge` (which builds a DOM node) is not here but `recruiterLabel`
 * (which returns a string) is.
 *
 * Preserved from the original: the comments recording *why* a given
 * behaviour is what it is, not just what it does.
 */

import type { Job, JobKey } from "../api/types";

/** A job may be missing any half of its composite key while still identifiable. */
export type JobKeyInput = Partial<JobKey>;

export function rowKey(job: JobKeyInput): string {
  return `${job.company}::${job.date_added}::${job.position_title || ""}::${job.link || ""}`;
}

// Reads the LOCAL calendar date, not UTC -- deliberately. `toISOString()`
// would report the date in UTC, which can be a day off from what the user's
// wall clock says (e.g. 11:30pm local is already "tomorrow" in UTC for a good
// part of the world). The follow-up chips date against the user's day, so
// this must stay local. Do not "fix" this to `toISOString()`.
export function localISODate(d: Date): string {
  const yr = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const da = String(d.getDate()).padStart(2, "0");
  return `${yr}-${mo}-${da}`;
}

export function startOfWeekISO(d: Date): string {
  const copy = new Date(d);
  copy.setDate(copy.getDate() - copy.getDay());
  return localISODate(copy);
}

export function isValidISODate(str: string | null | undefined): boolean {
  if (!str) return false;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(str)) return false;
  return !isNaN(Date.parse(str));
}

export function parseFollowupLog(raw: string | null | undefined): string[] {
  return (raw || "").split(",").map((s) => s.trim()).filter(Boolean);
}

export function serializeFollowupLog(tokens: string[]): string {
  return tokens.join(", ");
}

/* The composite key that addresses a job, since `jobs` has no surrogate id. */
export function jobKeyFields(job: JobKeyInput): JobKey {
  return {
    company: job.company || "",
    date_added: job.date_added || "",
    position_title: job.position_title || "",
    link: job.link || "",
  };
}

/*
 * The columns the table can be sorted by, and the job field each reads.
 *
 * Lives here rather than in a component so the comparison is testable: a
 * template's inline script was never loaded by any test, and this module is.
 */
export const SORT_COLUMNS = {
  company: "company",
  title: "position_title",
  location: "location",
  date_added: "date_added",
  status: "status",
} as const;

export type SortColumn = keyof typeof SORT_COLUMNS;
export type SortDirection = "asc" | "desc" | null;

/*
 * Compares two jobs by one column, for Array.prototype.sort.
 *
 * A blank sorts last in both directions. Descending by date should answer
 * "the most recent first", and a job with no date is not the oldest one --
 * it is the one nobody recorded a date for, which belongs at the end either
 * way. The same reading applies to a missing status or location.
 *
 * Dates are ISO-8601, so a plain string comparison already orders them.
 * Everything else compares numerically-aware and case-insensitively, so
 * "Series B" sorts after "Series A" and before "Series 10".
 */
export function compareJobs(
  column: SortColumn,
  direction: SortDirection,
): (a: Job, b: Job) => number {
  // `column` is typed as SortColumn, but the value driving it at a real call
  // site comes from a click on a table header (a DOM attribute), not from
  // the type system -- so this guards against a column TypeScript can't see
  // is invalid, the same way the original untyped helper did.
  const field = SORT_COLUMNS[column];
  if (!field) return () => 0;
  const sign = direction === "desc" ? -1 : 1;
  return (a, b) => {
    const x = ((a[field as keyof Job] as string | undefined) || "").trim();
    const y = ((b[field as keyof Job] as string | undefined) || "").trim();
    if (!x && !y) return 0;
    if (!x) return 1;
    if (!y) return -1;
    return sign * x.localeCompare(y, undefined, { numeric: true, sensitivity: "base" });
  };
}

/* asc -> desc -> off, so a click can always undo itself. */
export function nextSortDirection(current: SortDirection): SortDirection {
  if (current === "asc") return "desc";
  if (current === "desc") return null;
  return "asc";
}

/** A recruiter, or a job carrying a recruiter's fields, loose enough for both. */
export interface RecruiterLabelInput {
  name?: string | null;
  recruiter_name?: string | null;
  agency?: string | null;
  recruiter_agency?: string | null;
}

export function recruiterLabel(r: RecruiterLabelInput | null | undefined): string {
  if (!r) return "";
  const name = r.recruiter_name || r.name || "(unnamed)";
  const agency = r.recruiter_agency || r.agency;
  return agency ? `${name} — ${agency}` : name;
}
