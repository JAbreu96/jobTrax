/*
 * The jobs table, read-only.
 *
 * Rung 2 of the cutover: the same five columns as the Jinja table at `/`, the
 * same sort, the same windowed render. No filters, no search, no editing --
 * those are rungs 3 and 4, and putting them here would make this rung
 * unreviewable.
 *
 * Nothing here fetches. JobsPage owns the query; this renders what it is given,
 * the same convention as every other component in this tree.
 */
import { compareJobs, nextSortDirection, rowKey } from "../../lib/jobFields";
import type { SortColumn, SortDirection } from "../../lib/jobFields";
import { useIncrementalRender } from "../../hooks/useIncrementalRender";
import type { Job } from "../../api/types";
import styles from "./JobsTable.module.css";

const COLUMNS: { key: SortColumn; label: string }[] = [
  { key: "company", label: "Company" },
  { key: "title", label: "Title" },
  { key: "location", label: "Location" },
  { key: "date_added", label: "Date Added" },
  { key: "status", label: "Status" },
];

export interface JobsTableProps {
  jobs: Job[];
  /** More rows are still arriving. Distinct from "the list is short". */
  prefetching?: boolean;
  /** A page failed; `jobs` is a prefix of the real list. */
  truncated?: boolean;
  sort: { column: SortColumn; direction: SortDirection } | null;
  onSortChange: (sort: { column: SortColumn; direction: SortDirection } | null) => void;
  onOpenJob: (job: Job) => void;
}

const ARIA_SORT = { asc: "ascending", desc: "descending" } as const;

export function JobsTable({
  jobs, prefetching = false, truncated = false,
  sort, onSortChange, onOpenJob,
}: JobsTableProps) {
  // Sorted before windowing, never after: windowing the unsorted list and
  // sorting the window would reorder fifty arbitrary rows and call it a sort.
  const ordered = sort
    ? jobs.slice().sort(compareJobs(sort.column, sort.direction))
    : jobs;

  const { rendered, atEnd, setSentinel } = useIncrementalRender({
    available: ordered.length, prefetching,
  });
  const visible = ordered.slice(0, rendered);

  function toggleSort(column: SortColumn) {
    const current = sort?.column === column ? sort.direction : null;
    const direction = nextSortDirection(current);
    onSortChange(direction ? { column, direction } : null);
  }

  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            {COLUMNS.map(({ key, label }) => (
              <th
                key={key}
                aria-sort={sort?.column === key && sort.direction
                  ? ARIA_SORT[sort.direction]
                  : "none"}
              >
                <button type="button" className={styles.sortHeader}
                        onClick={() => toggleSort(key)}>
                  {label}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.map((job) => (
            <tr
              key={rowKey(job)}
              className={styles.row}
              tabIndex={0}
              onClick={() => onOpenJob(job)}
              // Rows are interactive, so they have to be reachable without a
              // mouse -- the Jinja table's rows are click-only, which is the
              // one thing about it not worth porting faithfully.
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onOpenJob(job);
                }
              }}
            >
              <td className={styles.company}>{job.company}</td>
              <td>{job.position_title}</td>
              <td className={styles.muted}>{job.location || "—"}</td>
              <td className={styles.muted}>{job.date_added}</td>
              <td>{job.status}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* The sentinel sits outside the table: a <div> inside <tbody> is
          invalid and the browser hoists it out, which puts it above the rows
          and makes it permanently visible. */}
      {!atEnd && <div ref={setSentinel} className={styles.sentinel}>Loading…</div>}

      <p className={styles.count}>
        {countLabel(visible.length, ordered.length, prefetching)}
        {truncated && (
          <span className={styles.truncated}>
            {" "}— the list stopped loading early, so some jobs are missing.
          </span>
        )}
      </p>
    </div>
  );
}

/**
 * Exported for tests. "of 1,088" while the prefetch is running would be a lie
 * -- that is how many have arrived, not how many there are -- so the count
 * says so rather than quoting a total it does not know yet.
 */
export function countLabel(shown: number, available: number, prefetching: boolean) {
  if (prefetching) return `${shown} of ${available} loaded so far…`;
  if (shown < available) return `${shown} of ${available}`;
  return `${available} job${available === 1 ? "" : "s"}`;
}
