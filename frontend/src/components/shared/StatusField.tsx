/*
 * The status <select>, replacing `makeStatusCell` in src/static/job_fields.js
 * (referenced from jobs.html's table row, not its detail grid). No React
 * port of that function existed before this component.
 *
 * `value`/`onSave` follow DateField's small-field pattern. `options` is a
 * prop rather than something this component fetches itself -- consistent
 * with RecruiterField taking `recruiters` as a prop -- so this stays a
 * plain, hook-free function of its inputs.
 */
import { useState } from "react";
import type { CSSProperties } from "react";
import type { JobStatus } from "../../api/types";
import flash from "./savedFlash.module.css";

export interface StatusFieldProps {
  label?: string;
  /** Job.status on the wire is a plain string, not JobStatus -- see api/types.ts. */
  value: string;
  options: JobStatus[];
  fieldClass?: string;
  flashEndColor?: string;
  onSave: (value: string) => Promise<void> | void;
}

export function StatusField({
  label = "Status",
  value,
  options,
  fieldClass = "",
  flashEndColor,
  onSave,
}: StatusFieldProps) {
  const [flashing, setFlashing] = useState(false);

  async function commit(next: string) {
    if (next === (value || "")) return;
    await onSave(next);
    setFlashing(false);
    requestAnimationFrame(() => setFlashing(true));
  }

  const wrapperStyle = flashEndColor
    ? ({ "--flash-end-color": flashEndColor } as CSSProperties)
    : undefined;

  return (
    <div className={fieldClass} style={wrapperStyle}>
      <label>{label}</label>
      <select
        data-testid="status-select"
        className={flashing ? flash.savedFlash : undefined}
        value={value || ""}
        onClick={(e) => e.stopPropagation()}
        onAnimationEnd={() => setFlashing(false)}
        onChange={(e) => {
          e.stopPropagation();
          void commit(e.target.value);
        }}
      >
        {options.map((opt) => (
          <option key={opt || "__blank__"} value={opt}>
            {opt || "— none —"}
          </option>
        ))}
      </select>
    </div>
  );
}
