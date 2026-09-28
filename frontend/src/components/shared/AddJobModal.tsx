/*
 * Adding a job by hand, or by pasting a posting URL.
 *
 * Ports openAddJobModal / fetchJobUrl / submitAddJob from
 * src/templates/jobs.html. The fetch path is the interesting half: it asks the
 * server to read a Greenhouse or Lever posting and fills the form from it, so
 * the common case is paste, glance, save.
 *
 * Owns no query. JobsPage passes both callbacks, matching the convention of
 * every other component in this tree.
 */
import { useEffect, useRef, useState } from "react";
import type { Job } from "../../api/types";
import styles from "./AddJobModal.module.css";

export interface FetchedPosting {
  company?: string;
  position_title?: string;
  location?: string;
  link?: string;
  job_summary?: string;
  notes?: string;
}

export interface AddJobModalProps {
  statuses: string[];
  onFetchUrl: (url: string) => Promise<FetchedPosting>;
  onSubmit: (fields: Record<string, string>) => Promise<Job>;
  onClose: () => void;
}

const BLANK = {
  company: "", position_title: "", location: "", link: "",
  status: "Tracking", contacts: "", job_summary: "", notes: "",
};

export function AddJobModal({ statuses, onFetchUrl, onSubmit, onClose }: AddJobModalProps) {
  const [fields, setFields] = useState<Record<string, string>>(BLANK);
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const [saving, setSaving] = useState(false);
  const firstFieldRef = useRef<HTMLInputElement>(null);

  // Focus lands in the dialog on open, and Escape closes it. The Jinja modal
  // does neither -- it closes on a backdrop click only, so a keyboard user
  // could open it and not get out.
  useEffect(() => {
    firstFieldRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const set = (name: string) => (value: string) =>
    setFields((f) => ({ ...f, [name]: value }));

  async function fetchFromUrl() {
    const trimmed = url.trim();
    if (!trimmed) return;
    setError(null);
    setFetching(true);
    try {
      const posting = await onFetchUrl(trimmed);
      // Merged, not replaced: anything already typed stays, because the
      // fetch fills what it could parse and leaves the rest blank. LinkedIn
      // and Indeed are refused server-side and arrive here as an error.
      setFields((f) => ({
        ...f,
        company: posting.company || f.company,
        position_title: posting.position_title || f.position_title,
        location: posting.location || f.location,
        link: posting.link || trimmed,
        job_summary: posting.job_summary || f.job_summary,
        notes: posting.notes || f.notes,
      }));
    } catch (err) {
      setError(message(err, "Failed to fetch job posting."));
    } finally {
      setFetching(false);
    }
  }

  async function submit() {
    if (!fields.company.trim() || !fields.position_title.trim()) {
      setError("Company and Position Title are required.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      await onSubmit(fields);
      onClose();
    } catch (err) {
      // A duplicate link answers 409 with a message naming the existing row.
      // Keeping the dialog open with the text intact matters: the alternative
      // is retyping a posting you already pasted.
      setError(message(err, "Failed to add job."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div className={styles.dialog} role="dialog" aria-modal="true"
           aria-label="Add a job" onClick={(e) => e.stopPropagation()}>
        <header className={styles.header}>
          <h2 className={styles.title}>Add a job</h2>
          <button type="button" className={styles.close} aria-label="Close"
                  onClick={onClose}>×</button>
        </header>

        <div className={styles.fetchRow}>
          <input
            className={styles.input}
            placeholder="Paste a Greenhouse or Lever URL"
            aria-label="Posting URL"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void fetchFromUrl(); } }}
          />
          <button type="button" className={styles.secondary}
                  disabled={fetching || !url.trim()} onClick={() => void fetchFromUrl()}>
            {fetching ? "Fetching…" : "Fetch"}
          </button>
        </div>

        {error && <p className={styles.error} role="alert">{error}</p>}

        <div className={styles.grid}>
          <Field label="Company" required inputRef={firstFieldRef}
                 value={fields.company} onChange={set("company")} />
          <Field label="Position title" required
                 value={fields.position_title} onChange={set("position_title")} />
          <Field label="Location" value={fields.location} onChange={set("location")} />
          <Field label="Link" value={fields.link} onChange={set("link")} />

          <label className={styles.field}>
            <span>Status</span>
            <select value={fields.status} onChange={(e) => set("status")(e.target.value)}>
              {statuses.filter(Boolean).map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>

          <Field label="Contacts" value={fields.contacts} onChange={set("contacts")} />
        </div>

        <label className={styles.field}>
          <span>Job description</span>
          <textarea rows={6} value={fields.job_summary}
                    onChange={(e) => set("job_summary")(e.target.value)} />
        </label>

        <label className={styles.field}>
          <span>Notes</span>
          <textarea rows={3} value={fields.notes}
                    onChange={(e) => set("notes")(e.target.value)} />
        </label>

        <footer className={styles.footer}>
          <button type="button" className={styles.secondary} onClick={onClose}>
            Cancel
          </button>
          <button type="button" className={styles.primary} disabled={saving}
                  onClick={() => void submit()}>
            {saving ? "Adding…" : "Add job"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, required, inputRef }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  inputRef?: React.Ref<HTMLInputElement>;
}) {
  return (
    <label className={styles.field}>
      <span>{label}{required && <span aria-hidden="true"> *</span>}</span>
      <input ref={inputRef} value={value} required={required}
             onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

/** ApiError carries the server's own message; anything else gets the fallback. */
function message(err: unknown, fallback: string): string {
  if (err && typeof err === "object" && "message" in err) {
    const m = (err as { message?: unknown }).message;
    if (typeof m === "string" && m) return m;
  }
  return fallback;
}
