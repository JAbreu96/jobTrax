/*
 * The filter controls above the table.
 *
 * Owns no filtering -- lib/jobFilters does that, and is tested without a DOM.
 * This is the controls and the two banners, and the one piece of real logic
 * it does keep is which recruiters to offer, because that is derived from the
 * rows rather than fetched: /api/recruiters costs ~2s and lists 107 people,
 * most of whom are attached to no tracked job.
 */
import { localISODate, recruiterLabel, startOfWeekISO } from "../../lib/jobFields";
import {
  BLANK, funnelBannerText, searchBannerText,
  type FunnelFilter, type JobFilters,
} from "../../lib/jobFilters";
import type { Job } from "../../api/types";
import styles from "./JobFilterBar.module.css";

export interface JobFilterBarProps {
  jobs: Job[];
  statuses: string[];
  filters: JobFilters;
  onChange: (next: JobFilters) => void;
  funnel: FunnelFilter | null;
  /** Rows matching / rows loaded, for the count beside the controls. */
  matched: number;
  total: number;
}

export function JobFilterBar({
  jobs, statuses, filters, onChange, funnel, matched, total,
}: JobFilterBarProps) {
  const set = (patch: Partial<JobFilters>) => onChange({ ...filters, ...patch });
  const recruiters = recruiterOptions(jobs);

  const funnelText = funnelBannerText(funnel);
  const searchText = searchBannerText(filters.q || "");

  return (
    <div className={styles.bar}>
      {funnelText && (
        <div className={styles.funnelBanner}>
          <span>
            Filtered from <strong>Insights</strong>: {funnelText}
            {" "}· <span className={styles.subtle}>archived included, to match the funnel</span>
          </span>
          {/* A link out rather than a button: the funnel filter comes from the
              URL, so clearing it means leaving that URL. */}
          <a href="/app/">clear</a>
        </div>
      )}

      <div className={styles.controls}>
        <input
          type="search"
          className={styles.search}
          placeholder="Search company, title, notes, location"
          aria-label="Search jobs"
          value={filters.q || ""}
          onChange={(e) => set({ q: e.target.value })}
        />

        <select aria-label="Filter by status" value={filters.status || ""}
                onChange={(e) => set({ status: e.target.value })}>
          <option value="">All statuses</option>
          {statuses.filter(Boolean).map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
          <option value={BLANK}>(no status)</option>
        </select>

        <select aria-label="Filter by recruiter" value={filters.recruiterId || ""}
                onChange={(e) => set({ recruiterId: e.target.value })}>
          <option value="">All recruiters</option>
          <option value={BLANK}>(no recruiter)</option>
          {recruiters.map(([id, label]) => (
            <option key={id} value={String(id)}>{label}</option>
          ))}
        </select>

        <input type="date" aria-label="Added from" value={filters.dateFrom || ""}
               onChange={(e) => set({ dateFrom: e.target.value })} />
        <input type="date" aria-label="Added to" value={filters.dateTo || ""}
               onChange={(e) => set({ dateTo: e.target.value })} />

        <button type="button" className={styles.chip}
                onClick={() => {
                  const today = localISODate(new Date());
                  set({ dateFrom: today, dateTo: today });
                }}>
          Today
        </button>
        <button type="button" className={styles.chip}
                onClick={() => set({ dateFrom: startOfWeekISO(new Date()),
                                     dateTo: localISODate(new Date()) })}>
          This week
        </button>
        <button type="button" className={styles.chip}
                onClick={() => set({ dateFrom: "", dateTo: "" })}>
          Clear dates
        </button>

        <span className={styles.count}>
          {matched === total ? `${total} jobs` : `${matched} of ${total} jobs`}
        </span>
      </div>

      {searchText && <p className={styles.searchBanner}>{searchText}</p>}
    </div>
  );
}

/**
 * The recruiters actually attached to a loaded row, labelled by name and
 * agency together and sorted by that label.
 *
 * Exported for tests. Agency alone collides: two AceStack recruiters would
 * give two options both reading "AceStack LLC" with no way to tell them apart.
 */
export function recruiterOptions(jobs: Job[]): [number, string][] {
  const seen = new Map<number, string>();
  for (const job of jobs) {
    if (job.recruiter_id && !seen.has(job.recruiter_id)) {
      seen.set(job.recruiter_id, recruiterLabel(job) || "Recruiter");
    }
  }
  return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
}
