/*
 * The jobs table.
 *
 * The same five columns as the Jinja table at `/`, the same sort, the same
 * windowed render, and the same two things editable in place: the company name
 * and the status.
 *
 * Nothing here fetches or saves. JobsPage owns the query and the mutation; this
 * renders what it is given and calls back, the same convention as every other
 * component in this tree.
 */
import { useRef, useState } from "react";
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
  /** Every status the server will accept, for the in-row picker. */
  statuses: string[];
  /** Resolves false when the save was refused, so the cell can put back what
   *  was there -- a renamed company can collide with an existing row. */
  onSaveField: (job: Job, field: "company" | "status", value: string) => Promise<boolean>;
}

const ARIA_SORT = { asc: "ascending", desc: "descending" } as const;

export function JobsTable({
  jobs, prefetching = false, truncated = false,
  sort, onSortChange, onOpenJob, statuses, onSaveField,
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
              <td className={styles.company}>
                <CompanyCell job={job} onSave={onSaveField} />
              </td>
              <td>{job.position_title}</td>
              <td className={styles.muted}>{job.location || "—"}</td>
              <td className={styles.muted}>{job.date_added}</td>
              <td>
                <StatusCell job={job} statuses={statuses} onSave={onSaveField} />
              </td>
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

/*
 * The company name, editable in place.
 *
 * An <input> rather than the original's contentEditable span. contentEditable
 * accepts pasted markup and reads back as innerHTML, which is a whole class of
 * problem for a field that goes straight into a primary key; an input can only
 * ever hold text.
 *
 * Clicks are stopped from reaching the row, which would otherwise navigate away
 * the moment you tried to place a cursor.
 */
function CompanyCell({ job, onSave }: {
  job: Job;
  onSave: JobsTableProps["onSaveField"];
}) {
  const [draft, setDraft] = useState(job.company);
  const [saving, setSaving] = useState(false);
  /*
   * Escape reverts, and it has to say so through a ref rather than by setting
   * the draft back: setDraft is asynchronous and blur() is not, so commit()
   * would read the pre-revert draft and save the very text Escape was pressed
   * to discard. Found by a test that asserted Escape saves nothing.
   */
  const cancelled = useRef(false);

  /*
   * Takes the value from the DOM rather than from `draft`. setDraft is
   * asynchronous and blur is not, so a blur landing in the same tick as the
   * last keystroke would read the pre-keystroke draft, see no change, and skip
   * the save -- silently, with the new text still on screen.
   */
  async function commit(current: string) {
    if (cancelled.current) { cancelled.current = false; setDraft(job.company); return; }
    const value = current.trim();
    if (!value) { setDraft(job.company); return; }   // blank is refused server-side
    if (value === job.company) return;
    setSaving(true);
    const ok = await onSave(job, "company", value);
    setSaving(false);
    // A rename moves the row to a new primary key, which can collide with a
    // job already at that key. The server answers 409; putting the old name
    // back is the only honest thing to show, since nothing was written.
    if (!ok) setDraft(job.company);
  }

  return (
    <input
      className={styles.cellInput}
      value={draft}
      disabled={saving}
      aria-label={`Company for ${job.position_title}`}
      data-key={rowKey(job)}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={(e) => { void commit(e.currentTarget.value); }}
      onKeyDown={(e) => {
        e.stopPropagation();          // Enter here must not open the row
        if (e.key === "Enter") e.currentTarget.blur();
        if (e.key === "Escape") { cancelled.current = true; e.currentTarget.blur(); }
      }}
    />
  );
}

/* The status picker. Changing it can also stamp date_applied server-side --
 * that is update_status's job, and the patched cache brings the new date back
 * without this needing to know the rule. */
function StatusCell({ job, statuses, onSave }: {
  job: Job;
  statuses: string[];
  onSave: JobsTableProps["onSaveField"];
}) {
  const [saving, setSaving] = useState(false);

  return (
    <select
      className={styles.cellSelect}
      value={job.status || ""}
      disabled={saving}
      aria-label={`Status for ${job.company}`}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      onChange={async (e) => {
        setSaving(true);
        await onSave(job, "status", e.target.value);
        setSaving(false);
      }}
    >
      {statuses.map((s) => (
        <option key={s} value={s}>{s || "(none)"}</option>
      ))}
    </select>
  );
}
