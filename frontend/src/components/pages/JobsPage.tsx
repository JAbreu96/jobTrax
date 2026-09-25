/*
 * The jobs list page. Fetches; JobsTable renders.
 *
 * Mounted at /app for now, not at "/" -- the Jinja table still owns that, and
 * this rung is read-only. It takes over "/" in rung 4, once it can edit.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useJobsProgressive } from "../../hooks/useJobsProgressive";
import { JobsTable } from "../shared/JobsTable";
import { jobViewPath } from "./JobViewPage";
import type { SortColumn, SortDirection } from "../../lib/jobFields";
import styles from "./JobsPage.module.css";

export default function JobsPage() {
  const navigate = useNavigate();
  const [sort, setSort] =
    useState<{ column: SortColumn; direction: SortDirection } | null>(null);

  const list = useJobsProgressive();

  if (list.isLoading) return <p className={styles.state}>Loading jobs…</p>;
  // Only the first page failing gets here -- a later page failing keeps its
  // rows and is reported inside the table as `truncated`.
  if (list.isError) return <p className={styles.state}>Could not load the jobs list.</p>;

  const jobs = list.data?.jobs ?? [];
  if (jobs.length === 0) return <p className={styles.state}>No jobs tracked yet.</p>;

  return (
    <main className={styles.page}>
      <JobsTable
        jobs={jobs}
        prefetching={list.data?.prefetching}
        truncated={list.data?.truncated}
        sort={sort}
        onSortChange={setSort}
        onOpenJob={(job) => navigate(jobViewPath(job))}
      />
    </main>
  );
}
