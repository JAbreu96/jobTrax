/*
 * Ported from `makeRecruiterField` in src/static/job_fields.js
 * (lines ~670-819 as of Phase 2) -- the four-state machine: picker, locked,
 * create, and the post-save flash.
 *
 * The lock semantics are enforced in jobs_db, not here: a link carrying a
 * `message_id` belongs to inbox-triage, and `POST /api/jobs/recruiter`
 * answers 409 with `{error, blocked}` when a caller tries to replace one
 * without `override: true`. This component only *reflects* that -- it never
 * decides on its own that a link is locked.
 *
 * Local `fromTriage` state (rather than reading `job.recruiter_from_triage`
 * directly) exists because the original mutated `job.recruiter_from_triage`
 * itself for two purposes that are NOT the same as "what did the server
 * last tell us": (1) "Change anyway" sets it false *for this edit only*,
 * before anything is saved, purely to swap the view to the picker; (2) a
 * 409 on save sets it back true to re-lock, even though the cache was never
 * patched with a new value (the write didn't land). Both are transient UI
 * state, not server truth, so they live in local state that resyncs from
 * the prop whenever the prop actually changes (i.e. a save landed and
 * patched the cache).
 *
 * The 409 retry-vs-relock behaviour is NOT defensive boilerplate (see the
 * original's comment on it): if the blocked list comes back non-empty, a
 * triage run linked a message between this component's last paint and the
 * save landing, so the correct move is to show the (now correct) locked
 * state, not to retry the same write.
 */
import { useEffect, useState } from "react";
import { defaultConfirm, defaultNotify, type ConfirmFn, type NotifyFn } from "../../lib/dialogs";
import { recruiterLabel } from "../../lib/jobFields";
import flash from "./savedFlash.module.css";
import styles from "./RecruiterField.module.css";
import type { Recruiter } from "../../api/types";
import type { SetRecruiterResult, CreateRecruiterFields } from "../../hooks/useJobFieldEditing";

export interface RecruiterFieldJob {
  recruiter_id: number | null;
  recruiter_name: string | null;
  recruiter_agency: string | null;
  recruiter_from_triage: boolean;
}

export interface RecruiterFieldProps {
  job: RecruiterFieldJob;
  recruiters: Recruiter[];
  setRecruiter: (recruiterId: number | null, override: boolean) => Promise<SetRecruiterResult>;
  createRecruiter: (fields: CreateRecruiterFields) => Promise<Recruiter>;
  /** Fires after a change actually lands -- the cache patch already causes a
   *  re-render; this is for callers with extra non-cache work (parity with
   *  the original's `onChanged`, which both templates wired to `render()`). */
  onChanged?: () => void;
  fieldClass?: string;
  flashEndColor?: string;
  confirm?: ConfirmFn;
  notify?: NotifyFn;
}

export function RecruiterField({
  job,
  recruiters,
  setRecruiter,
  createRecruiter,
  onChanged,
  fieldClass = "",
  flashEndColor,
  confirm = defaultConfirm,
  notify = defaultNotify,
}: RecruiterFieldProps) {
  const [fromTriage, setFromTriage] = useState(job.recruiter_from_triage);
  const [overridden, setOverridden] = useState(false);
  const [creating, setCreating] = useState(false);
  const [flashing, setFlashing] = useState(false);
  const [saving, setSaving] = useState(false);

  // Resync from the prop only when the server's view of it actually changes
  // (a save landed and patched the cache) -- see the file header comment.
  useEffect(() => {
    setFromTriage(job.recruiter_from_triage);
  }, [job.recruiter_from_triage, job.recruiter_id]);

  const locked = !!job.recruiter_id && fromTriage;

  async function applyChoice(recruiterId: number | null) {
    setSaving(true);
    try {
      const result = await setRecruiter(recruiterId, overridden);
      if (!result.ok) {
        if (result.blocked.length) {
          // Raced with a triage run between paint and save -- re-lock
          // rather than retry.
          setFromTriage(true);
          setCreating(false);
        } else {
          notify(result.error || "Failed to set the recruiter.");
        }
        return;
      }
      setOverridden(false);
      setCreating(false);
      setFlashing(false);
      requestAnimationFrame(() => setFlashing(true));
      onChanged?.();
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to set the recruiter.");
    } finally {
      setSaving(false);
    }
  }

  function handleOverrideClick() {
    if (
      !confirm(
        "This link came from an email inbox-triage processed. Changing it " +
          "means the next run will not put it back, and the reason is noted " +
          "on the recruiter it replaces.\n\nChange it?",
      )
    ) {
      return;
    }
    setFromTriage(false); // unlocked for this edit only
    setOverridden(true);
  }

  async function handleCreateSubmit(fields: { name: string; agency: string; email: string }) {
    // Required because email is the recruiter's identity: without it a
    // later message from the same person arrives as a second recruiter
    // instead of this one.
    if (!fields.name.trim() || !fields.email.trim()) {
      notify("A name and an email address are both required.");
      return;
    }
    setSaving(true);
    try {
      const created = await createRecruiter({
        name: fields.name.trim(),
        agency: fields.agency.trim(),
        email: fields.email.trim(),
      });
      await applyChoice(created.id);
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to create the recruiter.");
      setSaving(false);
    }
  }

  const wrapperStyle = flashEndColor
    ? ({ "--flash-end-color": flashEndColor } as React.CSSProperties)
    : undefined;

  return (
    <div className={fieldClass} style={wrapperStyle}>
      <label>Recruiter</label>
      <div
        className={[styles.recruiterField, flashing ? flash.savedFlash : ""].filter(Boolean).join(" ")}
        onClick={(e) => e.stopPropagation()}
        onAnimationEnd={() => setFlashing(false)}
      >
        {locked ? (
          <>
            <span className={styles.recruiterCurrent} data-testid="recruiter-current">
              {recruiterLabel(job)}
            </span>
            <span className={styles.recruiterProvenance}>linked from a message</span>
            <button type="button" className={styles.linklike} onClick={handleOverrideClick}>
              Change anyway
            </button>
          </>
        ) : creating ? (
          <CreateForm
            disabled={saving}
            onSubmit={handleCreateSubmit}
            onCancel={() => setCreating(false)}
          />
        ) : (
          <select
            data-testid="recruiter-select"
            value={job.recruiter_id != null ? String(job.recruiter_id) : ""}
            disabled={saving}
            onChange={(e) => {
              if (e.target.value === "__new__") {
                setCreating(true);
                return;
              }
              const id = e.target.value ? Number(e.target.value) : null;
              void applyChoice(id);
            }}
          >
            <option value="">— none —</option>
            {recruiters.map((r) => (
              <option key={r.id} value={String(r.id)}>
                {recruiterLabel(r)}
              </option>
            ))}
            <option value="__new__">＋ Create new recruiter…</option>
          </select>
        )}
      </div>
    </div>
  );
}

function CreateForm({
  disabled,
  onSubmit,
  onCancel,
}: {
  disabled: boolean;
  onSubmit: (fields: { name: string; agency: string; email: string }) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [agency, setAgency] = useState("");
  const [email, setEmail] = useState("");

  return (
    <div className={styles.recruiterNew}>
      <input
        type="text"
        placeholder="Name (required)"
        aria-label="Recruiter name"
        value={name}
        disabled={disabled}
        onChange={(e) => setName(e.target.value)}
      />
      <input
        type="text"
        placeholder="Agency"
        aria-label="Recruiter agency"
        value={agency}
        disabled={disabled}
        onChange={(e) => setAgency(e.target.value)}
      />
      <input
        type="text"
        placeholder="Email (required)"
        aria-label="Recruiter email"
        value={email}
        disabled={disabled}
        onChange={(e) => setEmail(e.target.value)}
      />
      <button
        type="button"
        disabled={disabled}
        onClick={() => onSubmit({ name, agency, email })}
      >
        Add & assign
      </button>
      <button type="button" className={styles.linklike} disabled={disabled} onClick={onCancel}>
        Cancel
      </button>
    </div>
  );
}
