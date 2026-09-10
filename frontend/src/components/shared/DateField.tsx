/*
 * Ported from `makeDateField`/`renderDateInput` in src/static/job_fields.js
 * (lines ~447-491 as of Phase 2).
 *
 * `stopClicks`: dropped as a prop. The table passed `true` because a click
 * on the date input would otherwise bubble to the detail row's collapse
 * handler; the modal passed `false` because it has no such ancestor. This
 * component always stops propagation on its own interactive elements
 * instead of taking that as config -- it costs the modal nothing (nothing
 * up its tree listens for the click) and it is what the table needs. Making
 * it unconditional here means Phase 4 doesn't have to remember to opt in,
 * and Phase 5 doesn't have to remember it doesn't need to.
 *
 * `tagFields` (`data-field`): dropped entirely, not replaced. It existed so
 * the kanban modal could find this input again to rebuild it; React
 * re-renders from `value` instead, so there is nothing to find.
 *
 * The legacy non-ISO fallback (`outreach_date`/`date_applied` predating
 * validation, e.g. "emailed Tuesday") is preserved: such a value renders as
 * text with a "Replace with date" opt-in, rather than a date input silently
 * blanking it.
 */
import { useState } from "react";
import { isValidISODate } from "../../lib/jobFields";
import flash from "./savedFlash.module.css";
import styles from "./DateField.module.css";

export interface DateFieldProps {
  label: string;
  value: string;
  /** `cfg.fieldClass` from the original -- the wrapper class the caller owns. */
  fieldClass?: string;
  /** See MarkdownField/savedFlash.module.css: the flash's end colour. */
  flashEndColor?: string;
  onSave: (value: string) => Promise<void> | void;
}

export function DateField({ label, value, fieldClass = "", flashEndColor, onSave }: DateFieldProps) {
  const [flashing, setFlashing] = useState(false);
  // Once the user opts in to replacing a legacy non-date value, show the
  // real date input even though `value` itself is still the old text --
  // mirrors the original's `box.replaceWith(input)`.
  const [replacing, setReplacing] = useState(false);

  const legacy = value && !isValidISODate(value) && !replacing;

  async function commit(next: string) {
    await onSave(next);
    setFlashing(false);
    // Force a reflow-driven restart the way the original did with
    // `void cell.offsetWidth`: toggling the class off then on in the same
    // tick would be coalesced by React, so this needs a tick in between.
    requestAnimationFrame(() => setFlashing(true));
  }

  const wrapperStyle = flashEndColor
    ? ({ "--flash-end-color": flashEndColor } as React.CSSProperties)
    : undefined;

  return (
    <div className={fieldClass} style={wrapperStyle}>
      <label>{label}</label>
      {legacy ? (
        <div className={styles.nonDateValue} data-testid="date-legacy-value">
          <span className={styles.rawText}>{value}</span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setReplacing(true);
            }}
          >
            Replace with date
          </button>
        </div>
      ) : (
        <input
          type="date"
          data-testid="date-input"
          className={flashing ? flash.savedFlash : undefined}
          value={isValidISODate(value) ? value : ""}
          onClick={(e) => e.stopPropagation()}
          onAnimationEnd={() => setFlashing(false)}
          onChange={(e) => {
            e.stopPropagation();
            void commit(e.target.value);
          }}
        />
      )}
    </div>
  );
}
