/*
 * Ported from `makeDetailField` in src/static/job_fields.js (lines ~554-575
 * as of Phase 2) -- the plain-text/notes contentEditable field. (The
 * markdown variant is MarkdownField.tsx, from Phase 2; this is its
 * non-markdown sibling: company notes, contacts, location, etc.)
 *
 * contentEditable stays uncontrolled on purpose, same as the original DOM
 * builder: `value` seeds the element's initial text and is otherwise left
 * alone by React while the user is editing, exactly like the vanilla
 * version left `editable.textContent` alone between paints. The tradeoff
 * (an external cache update to `value` while this node is mounted won't be
 * reflected until it remounts) is the same one the original had -- nothing
 * ever re-painted a field out from under an in-progress edit there either.
 *
 * On a failed save the original resets `cell.textContent` back to the job's
 * last-known value; this does the same via the ref, and surfaces the
 * server's error through the injectable `notify` seam (see lib/dialogs.ts)
 * instead of a bare `alert()`.
 *
 * `stopClicks`/`tagFields`: dropped, same reasoning as DateField/FollowupField.
 */
import { useRef, useState } from "react";
import { defaultNotify, type NotifyFn } from "../../lib/dialogs";
import flash from "./savedFlash.module.css";
import styles from "./DetailField.module.css";

export interface DetailFieldProps {
  label: string;
  value: string;
  fieldClass?: string;
  /** `cfg.notesClass` -- extra class for the roomy text fields. */
  notesClass?: string;
  flashEndColor?: string;
  onSave: (value: string) => Promise<void> | void;
  notify?: NotifyFn;
}

export function DetailField({
  label,
  value,
  fieldClass = "",
  notesClass = "",
  flashEndColor,
  onSave,
  notify = defaultNotify,
}: DetailFieldProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [flashing, setFlashing] = useState(false);

  async function handleBlur() {
    const el = ref.current;
    if (!el) return;
    const next = (el.textContent || "").trim();
    if (next === (value || "")) return;
    try {
      await onSave(next);
      setFlashing(false);
      requestAnimationFrame(() => setFlashing(true));
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to save change.");
      // Revert -- the write didn't land, so the field shouldn't keep showing
      // the unsaved value (mirrors the original's `cell.textContent = ...`).
      el.textContent = value || "";
    }
  }

  const wrapperClassName = [fieldClass, notesClass].filter(Boolean).join(" ");
  const wrapperStyle = flashEndColor
    ? ({ "--flash-end-color": flashEndColor } as React.CSSProperties)
    : undefined;

  return (
    <div className={wrapperClassName} style={wrapperStyle}>
      <label>{label}</label>
      <div
        ref={ref}
        data-testid="detail-editable"
        className={[styles.editable, flashing ? flash.savedFlash : ""].filter(Boolean).join(" ")}
        contentEditable
        suppressContentEditableWarning
        onClick={(e) => e.stopPropagation()}
        onBlur={() => void handleBlur()}
        onAnimationEnd={() => setFlashing(false)}
      >
        {value}
      </div>
    </div>
  );
}
