/*
 * Ported from `makeFollowupField`/`renderFollowupField` in
 * src/static/job_fields.js (lines ~493-552 as of Phase 2).
 *
 * `stopClicks` / `tagFields`: dropped, same reasoning as DateField -- clicks
 * on chips/inputs/buttons always stop propagation (harmless when nothing up
 * the tree listens, necessary when something does); nothing needs a
 * `data-field` hook to find this node again because React re-renders it.
 *
 * `parseFollowupLog`/`serializeFollowupLog` come from lib/jobFields.ts
 * (Phase 1) -- not reimplemented here, per the brief.
 */
import { useState } from "react";
import { isValidISODate, parseFollowupLog, serializeFollowupLog } from "../../lib/jobFields";
import flash from "./savedFlash.module.css";
import styles from "./FollowupField.module.css";

export interface FollowupFieldProps {
  label: string;
  /** Raw comma-joined follow-up log, as stored on the job row. */
  value: string;
  fieldClass?: string;
  flashEndColor?: string;
  onSave: (value: string) => Promise<void> | void;
}

// Two follow-ups is the cap; a third reads as pestering.
const MAX_FOLLOWUPS = 2;

export function FollowupField({ label, value, fieldClass = "", flashEndColor, onSave }: FollowupFieldProps) {
  const tokens = parseFollowupLog(value);
  const [draftDate, setDraftDate] = useState("");
  const [flashing, setFlashing] = useState(false);

  async function commit(updated: string[]) {
    await onSave(serializeFollowupLog(updated));
    setFlashing(false);
    requestAnimationFrame(() => setFlashing(true));
  }

  function removeToken(token: string) {
    void commit(tokens.filter((t) => t !== token));
  }

  function addToken() {
    if (!draftDate || tokens.includes(draftDate)) return;
    void commit([...tokens, draftDate]);
    setDraftDate("");
  }

  const wrapperStyle = flashEndColor
    ? ({ "--flash-end-color": flashEndColor } as React.CSSProperties)
    : undefined;

  return (
    <div className={fieldClass} style={wrapperStyle}>
      <label>{label}</label>
      <div className={[styles.followupField, flashing ? flash.savedFlash : ""].filter(Boolean).join(" ")}>
        {tokens.map((token) => (
          <span
            key={token}
            className={[styles.chip, !isValidISODate(token) ? styles.nonDate : ""].filter(Boolean).join(" ")}
          >
            <span>{token}</span>
            <button
              type="button"
              aria-label={`Remove ${token}`}
              onClick={(e) => {
                e.stopPropagation();
                removeToken(token);
              }}
            >
              &times;
            </button>
          </span>
        ))}
        <span className={styles.add}>
          <input
            type="date"
            aria-label={`${label} date`}
            value={draftDate}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => {
              e.stopPropagation();
              setDraftDate(e.target.value);
            }}
          />
          <button
            type="button"
            disabled={tokens.length >= MAX_FOLLOWUPS}
            onClick={(e) => {
              e.stopPropagation();
              addToken();
            }}
          >
            Add
          </button>
        </span>
      </div>
    </div>
  );
}
