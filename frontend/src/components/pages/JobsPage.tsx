/*
 * The jobs list page. Fetches; JobFilterBar and JobsTable render.
 *
 * Mounted at /app for now, not at "/" -- the Jinja table still owns that, and
 * this is still read-only. It takes over "/" in rung 4, once it can edit.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useConfig } from "../../api/queries";
import { useJobsProgressive } from "../../hooks/useJobsProgressive";
import { JobFilterBar } from "../shared/JobFilterBar";
import { JobsTable } from "../shared/JobsTable";
import { jobViewPath } from "./JobViewPage";
import { filterJobs, funnelFromSearch, searchFromQuery, wantsArchived } from "../../lib/jobFilters";
import type { JobFilters } from "../../lib/jobFilters";
import type { SortColumn, SortDirection } from "../../lib/jobFields";
import styles from "./JobsPage.module.css";

export default function JobsPage() {
  const navigate = useNavigate();

  /*
   * Read once, from the URL the page loaded with. The funnel filter and the
   * archived population are properties of *that* link, not of the current
   * filter state -- a keystroke in the search box must not re-read them and
   * shrink the list out from under the user mid-type.
   */
  const [initialSearch] = useState(() => window.location.search);
  const funnel = useMemo(() => funnelFromSearch(initialSearch), [initialSearch]);
  const includeArchived = useMemo(() => wantsArchived(initialSearch), [initialSearch]);

  const [filters, setFilters] = useState<JobFilters>(() => ({
    q: searchFromQuery(initialSearch),
  }));
  const [sort, setSort] =
    useState<{ column: SortColumn; direction: SortDirection } | null>(null);

  const config = useConfig();
  const list = useJobsProgressive({ includeArchived });
  const jobs = useMemo(() => list.data?.jobs ?? [], [list.data]);

  const matched = useMemo(
    () => filterJobs(jobs, { ...filters, funnel }),
    [jobs, filters, funnel],
  );

  /*
   * Keep ?q= in the address bar in step with the box, so a filtered view can
   * be linked or reloaded. replaceState, not push: a history entry per
   * keystroke would make Back walk letter by letter out of a search.
   */
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const term = (filters.q || "").trim();
    if (term) params.set("q", term);
    else params.delete("q");
    const qs = params.toString();
    window.history.replaceState(
      null, "", window.location.pathname + (qs ? `?${qs}` : ""));
  }, [filters.q]);

  if (list.isLoading) return <p className={styles.state}>Loading jobs…</p>;
  // Only the first page failing reaches here; a later page failing keeps its
  // rows and is reported inside the table as `truncated`.
  if (list.isError) return <p className={styles.state}>Could not load the jobs list.</p>;

  return (
    <main className={styles.page}>
      <JobFilterBar
        jobs={jobs}
        statuses={config.data?.status_values ?? []}
        filters={filters}
        onChange={setFilters}
        funnel={funnel}
        matched={matched.length}
        total={jobs.length}
      />

      {matched.length === 0
        ? (
          <p className={styles.empty}>
            {jobs.length === 0
              ? "No jobs tracked yet."
              : "No jobs match these filters."}
          </p>
        )
        : (
          <JobsTable
            jobs={matched}
            prefetching={list.data?.prefetching}
            truncated={list.data?.truncated}
            sort={sort}
            onSortChange={setSort}
            onOpenJob={(job) => navigate(jobViewPath(job))}
          />
        )}
    </main>
  );
}
