/*
 * The right rail: where the job is, and your notes on it.
 *
 * The timeline is the status control rather than a picture of it. The legacy
 * panel had a <select> for status and nothing showing progression; putting
 * both in the rail would be two controls for one piece of state sitting inches
 * apart, so clicking a node sets the status instead.
 *
 * Statuses that are not positions on the path -- Rejected and Accepted -- are
 * not nodes and cannot be reached by clicking one. They get a separate control,
 * because they are outcomes: see the PATH comment in lib/timeline.ts.
 */
import { useState } from "react";
import type { Interview, JobStatus } from "../../api/types";
import { timelineNodes, TERMINAL, type TimelineJob } from "../../lib/timeline";
import { MarkdownField } from "./MarkdownField";
import styles from "./StatusRail.module.css";

export interface StatusRailProps {
  job: TimelineJob & { notes?: string | null };
  rounds: Interview[];
  onSetStatus: (status: string) => Promise<unknown> | void;
  onSaveNotes: (value: string) => Promise<void> | void;
}

function formatDate(raw: string): string {
  // Only reformat what is unambiguously an ISO date. These columns predate
  // validation and hold values like "emailed Tuesday"; anything else is shown
  // exactly as stored rather than run through a parser that would render
  // "Invalid Date" over the top of real information.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (!m) return raw;
  return `${Number(m[2])}/${Number(m[3])}/${m[1].slice(2)}`;
}

export function StatusRail({ job, rounds, onSetStatus, onSaveNotes }: StatusRailProps) {
  const timeline = timelineNodes(job, rounds);
  const [busy, setBusy] = useState<string | null>(null);

  async function choose(status: JobStatus) {
    setBusy(status);
    try {
      await onSetStatus(status);
    } finally {
      setBusy(null);
    }
  }

  return (
    <aside className={styles.rail} aria-label="Application status">
      <h2 className={styles.heading}>Application status</h2>

      {timeline.unplaceable && (
        // The status is set to something STATUS_ORDER does not contain, so the
        // nodes below were derived from evidence rather than from it. Saying so
        // beats a rail that quietly disagrees with the status field.
        <p className={styles.unplaceable}>
          Status <strong>{job.status}</strong> isn&rsquo;t one of the tracked
          stages — the path below is inferred from dates and rounds.
        </p>
      )}

      <ol className={styles.timeline}>
        {timeline.nodes.map((n) => (
          <li
            key={n.status}
            className={[
              styles.node,
              n.reached ? styles.reached : "",
              n.current ? styles.current : "",
            ].join(" ")}
          >
            <button
              type="button"
              className={styles.nodeButton}
              aria-current={n.current ? "step" : undefined}
              disabled={busy !== null}
              onClick={() => choose(n.status)}
              title={n.current ? `Currently ${n.status}` : `Set status to ${n.status}`}
            >
              <span className={styles.dot} aria-hidden="true" />
              <span className={styles.nodeLabel}>{n.status}</span>
              <span className={styles.nodeDate}>
                {n.date ? formatDate(n.date) : n.reached ? "date unknown" : ""}
              </span>
            </button>
            {n.rounds.length > 0 && (
              <ul className={styles.rounds}>
                {n.rounds.map((r) => (
                  <li key={r.id}>
                    {r.type_label || r.interview_type.replace(/_/g, " ")}
                    {r.scheduled_date ? ` · ${formatDate(r.scheduled_date)}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>

      {timeline.upcoming.length > 0 && (
        <p className={styles.upcoming}>then {timeline.upcoming.join(" · ")}</p>
      )}

      {timeline.terminal ? (
        <p className={styles.terminal} data-outcome={timeline.terminal.toLowerCase()}>
          {timeline.terminal}
          <button type="button" className={styles.undo} disabled={busy !== null}
                  onClick={() => choose("" as JobStatus)}>
            clear
          </button>
        </p>
      ) : (
        <div className={styles.outcomes}>
          {TERMINAL.map((t) => (
            <button key={t} type="button" className={styles.outcomeButton}
                    disabled={busy !== null} onClick={() => choose(t)}>
              Mark {t.toLowerCase()}
            </button>
          ))}
        </div>
      )}

      <div className={styles.notes}>
        <MarkdownField
          label="Notes"
          value={job.notes || ""}
          expandable
          fieldClass={styles.notesField}
          onSave={onSaveNotes}
        />
      </div>
    </aside>
  );
}
