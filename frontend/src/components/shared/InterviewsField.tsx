/*
 * Interview rounds for one job: what is booked, what already happened, and a
 * form to record another.
 *
 * The branch this view is built from left this as a TODO, so it is a port of
 * makeInterviewsField in src/static/job_fields.js rather than a rewrite of a
 * React component -- with one behavioural change that came from the API
 * beneath it: the legacy field had a "happened on / booked for" <select>
 * because rows carried two dates. `occurred_date` is gone and
 * /api/interviews/add rejects it, so the single scheduled date decides which
 * a round is, by comparing it to today. The control that asked is gone too.
 */
import { useState } from "react";
import type { Interview, InterviewType } from "../../api/types";
import type { ConfirmFn } from "../../lib/dialogs";
import { defaultConfirm } from "../../lib/dialogs";
import styles from "./InterviewsField.module.css";

export interface InterviewsFieldProps {
  rounds: Interview[];
  interviewTypes: InterviewType[];
  onAdd: (fields: {
    interview_type: InterviewType;
    scheduled_date: string;
    type_label?: string;
    self_rating?: string;
    notes?: string;
  }) => Promise<unknown>;
  onDelete: (id: number) => Promise<unknown>;
  confirm?: ConfirmFn;
  /** Today as YYYY-MM-DD. Injected so the booked/happened split is testable. */
  today?: string;
}

function label(round: Interview): string {
  return round.type_label || round.interview_type.replace(/_/g, " ");
}

export function InterviewsField({
  rounds, interviewTypes, onAdd, onDelete,
  confirm = defaultConfirm,
  today = new Date().toISOString().slice(0, 10),
}: InterviewsFieldProps) {
  const [type, setType] = useState<InterviewType | "">("");
  const [date, setDate] = useState("");
  const [typeLabel, setTypeLabel] = useState("");
  const [rating, setRating] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // No date means it cannot be placed on either side of today. The legacy
  // field allowed that and the rows it produced are the ones the Insights
  // "missing rounds" card reports, so it is refused here.
  const sorted = [...rounds].sort((a, b) =>
    (a.scheduled_date || "").localeCompare(b.scheduled_date || ""));
  const upcoming = sorted.filter((r) => (r.scheduled_date || "") > today);
  const past = sorted.filter((r) => (r.scheduled_date || "") <= today).reverse();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!type) return setError("Pick a round type.");
    if (!date) return setError("A round needs a date — it is what says whether it has happened.");
    if (type === "other" && !typeLabel.trim()) {
      return setError("“Other” needs a label, or the round is unreadable later.");
    }
    setError("");
    setBusy(true);
    try {
      await onAdd({
        interview_type: type,
        scheduled_date: date,
        type_label: typeLabel.trim() || undefined,
        self_rating: rating || undefined,
        notes: notes.trim() || undefined,
      });
      setType(""); setDate(""); setTypeLabel(""); setRating(""); setNotes("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save that round.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(round: Interview) {
    if (!confirm(`Delete the ${label(round)} round?`)) return;
    await onDelete(round.id);
  }

  function list(items: Interview[], heading: string) {
    if (!items.length) return null;
    return (
      <section className={styles.group}>
        <h4 className={styles.groupHeading}>{heading}</h4>
        <ul className={styles.rounds}>
          {items.map((r) => (
            <li key={r.id} className={styles.round}>
              <div className={styles.roundHead}>
                <span className={styles.roundType}>{label(r)}</span>
                <span className={styles.roundDate}>{r.scheduled_date || "no date"}</span>
                <button type="button" className={styles.remove}
                        onClick={() => remove(r)} aria-label={`Delete ${label(r)} round`}>
                  ×
                </button>
              </div>
              {(r.self_rating !== null || r.loop_id || r.notes) && (
                <div className={styles.roundMeta}>
                  {r.self_rating !== null && <span>felt {r.self_rating}/5</span>}
                  {r.loop_id && <span>loop {r.loop_id}</span>}
                  {r.notes && <span className={styles.roundNotes}>{r.notes}</span>}
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>
    );
  }

  return (
    <div className={styles.wrap}>
      {!rounds.length && (
        <p className={styles.empty}>
          No rounds recorded yet. Adding one here also feeds the Insights funnel.
        </p>
      )}
      {list(upcoming, "Upcoming")}
      {list(past, "Happened")}

      <form className={styles.form} onSubmit={submit}>
        <h4 className={styles.groupHeading}>Add a round</h4>
        <div className={styles.formRow}>
          <select value={type} aria-label="Round type"
                  onChange={(e) => setType(e.target.value as InterviewType)}>
            <option value="">Round type…</option>
            {interviewTypes.map((t) => (
              <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
            ))}
          </select>
          <input type="date" value={date} aria-label="Date"
                 onChange={(e) => setDate(e.target.value)} />
          <select value={rating} aria-label="How it felt"
                  onChange={(e) => setRating(e.target.value)}>
            <option value="">How it felt…</option>
            {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}/5</option>)}
          </select>
        </div>
        {type === "other" && (
          <input type="text" value={typeLabel} placeholder="What kind of round?"
                 aria-label="Round label"
                 onChange={(e) => setTypeLabel(e.target.value)} />
        )}
        <textarea value={notes} rows={2} placeholder="Notes on this round (optional)"
                  aria-label="Round notes"
                  onChange={(e) => setNotes(e.target.value)} />
        {error && <p className={styles.error} role="alert">{error}</p>}
        <button type="submit" className={styles.submit} disabled={busy}>
          {busy ? "Saving…" : (date && date > today ? "Book round" : "Log round")}
        </button>
      </form>
    </div>
  );
}
