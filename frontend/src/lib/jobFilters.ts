/*
 * Which jobs a set of filters lets through.
 *
 * Pure, and separate from the controls that drive it, because the semantics
 * here are the part that is easy to get subtly wrong and impossible to see:
 * a filter that is slightly too generous just shows a few extra rows, and
 * nobody notices until a number on Insights disagrees with the list it links
 * to. Ports render()'s filter block and matchesFunnelFilter() from
 * src/templates/jobs.html.
 */
import { rowKey } from "./jobFields";
import type { Job } from "../api/types";

/** The sentinel both selects use for "the field is empty", since "" already
 *  means "no filter". */
export const BLANK = "__blank__";

// Lowercased, because a status is compared case-insensitively here and only
// here -- the funnel's `screen` stage is the one filter that groups several.
export const SCREEN_STATUSES = [
  "phone screen", "technical", "system design", "behavioral", "final round",
];

export type FunnelStage =
  | "applied" | "outreached" | "screen" | "rejected" | "interviewed";
export type FunnelSource = "all" | "hand" | "auto";

export interface FunnelFilter {
  stage: FunnelStage | string;
  source: FunnelSource | string;
  /**
   * Job keys that reached an interview. Only the `interviewed` stage needs it
   * and it arrives from a second request, so `null` means "still loading" and
   * lets everything through rather than briefly showing an empty table and
   * then filling it -- which reads as "no results" for as long as it lasts.
   */
  interviewedKeys?: Set<string> | null;
}

export interface JobFilters {
  q?: string;
  status?: string;
  recruiterId?: string;
  dateFrom?: string;
  dateTo?: string;
  funnel?: FunnelFilter | null;
}

/**
 * Whether a job was submitted by ApplyPass rather than by hand.
 *
 * Read out of free-text notes, which is not a good place for a fact this
 * load-bearing -- but it is where it lives, Insights counts it the same way,
 * and a second definition here would make the two disagree.
 */
export function isAutoApplied(job: Job): boolean {
  const notes = (job.notes || "").toLowerCase();
  return notes.includes("applypass") || notes.includes("auto-appl");
}

export function matchesFunnel(job: Job, funnel: FunnelFilter | null | undefined): boolean {
  if (!funnel) return true;
  if (funnel.source === "hand" && isAutoApplied(job)) return false;
  if (funnel.source === "auto" && !isAutoApplied(job)) return false;

  const status = (job.status || "").trim().toLowerCase();
  switch (funnel.stage) {
    case "applied":
      return Boolean((job.date_applied || "").trim());
    case "outreached":
      return Boolean((job.outreach_date || "").trim());
    case "screen":
      return SCREEN_STATUSES.includes(status);
    case "rejected":
      return status === "rejected";
    case "interviewed":
      // Undefined and null both mean "not fetched yet"; an empty Set is a real
      // answer meaning nothing qualified.
      return funnel.interviewedKeys
        ? funnel.interviewedKeys.has(rowKey(job))
        : true;
    default:
      return true;
  }
}

export function filterJobs(jobs: Job[], filters: JobFilters = {}): Job[] {
  const { status, recruiterId, dateFrom, dateTo, funnel } = filters;
  const q = (filters.q || "").trim().toLowerCase();

  return jobs.filter((job) => {
    if (status === BLANK && (job.status || "").trim() !== "") return false;
    if (status && status !== BLANK && job.status !== status) return false;

    if (recruiterId === BLANK && job.recruiter_id) return false;
    if (recruiterId && recruiterId !== BLANK
        && String(job.recruiter_id) !== recruiterId) return false;

    if (!matchesFunnel(job, funnel)) return false;

    // Dates are ISO-8601, so a string comparison is a date comparison. A job
    // with no date_added fails a bounded range rather than passing it: "added
    // since the 1st" should not include a row nobody dated.
    if (dateFrom && (job.date_added || "") < dateFrom) return false;
    if (dateTo && (job.date_added || "") > dateTo) return false;

    if (!q) return true;
    // notes is in the haystack and is not a visible column. That is on
    // purpose -- it is where "applypass", recruiter names and context end up,
    // and searching it is why /api/jobs carries notes at all.
    return [job.company, job.position_title, job.notes, job.location]
      .join(" ").toLowerCase().includes(q);
  });
}

/**
 * The funnel filter a URL asks for, or null.
 *
 * `source` defaults to "all" rather than being absent, so a stage link with no
 * source behaves like the funnel row it came from.
 */
export function funnelFromSearch(search: string): FunnelFilter | null {
  const params = new URLSearchParams(search || "");
  const stage = params.get("stage");
  if (!stage) return null;
  return { stage, source: params.get("source") || "all", interviewedKeys: null };
}

/**
 * Whether the URL asks for archived rows.
 *
 * A stage link matches the funnel, which counts archived rows. A ?q= link from
 * Insights says so explicitly instead, so a search the user *types* never
 * quietly widens the population underneath them.
 */
export function wantsArchived(search: string): boolean {
  const params = new URLSearchParams(search || "");
  return params.has("stage") || params.get("include_archived") === "1";
}

/** The search term a ?q= deeplink carries. */
export function searchFromQuery(search: string): string {
  return (new URLSearchParams(search || "").get("q") || "").trim();
}

const STAGE_LABELS: Record<string, string> = {
  applied: "applied",
  outreached: "outreached",
  screen: "at an interview stage",
  rejected: "rejected",
  interviewed: "interviewed",
};

const SOURCE_LABELS: Record<string, string> = {
  all: "all sources",
  hand: "hand-applied",
  auto: "auto-submitted (ApplyPass)",
};

/** Pure so the banner's wording is testable without a DOM. */
export function funnelBannerText(funnel: FunnelFilter | null): string | null {
  if (!funnel) return null;
  const stage = STAGE_LABELS[funnel.stage] || funnel.stage;
  const source = SOURCE_LABELS[funnel.source] || funnel.source;
  return `${stage} · ${source}`;
}

/**
 * Given the *current* query, not the one the page loaded with, so a caller
 * that re-runs it on every keystroke keeps the banner honest about what the
 * table is actually filtered to. Null rather than "" when there is nothing to
 * say, so "no banner" is distinguishable from "banner with empty text".
 */
export function searchBannerText(q: string): string | null {
  const term = (q || "").trim();
  return term ? `Searching for “${term}”` : null;
}
