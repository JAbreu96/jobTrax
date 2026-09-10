/*
 * Ported from `makeMarkdownField` in src/static/job_fields.js (lines
 * ~587-653 as of Phase 2). That function built a DOM subtree imperatively:
 * a rendered `<div>` clamped by CSS, an "Edit" button that swapped it for a
 * `<textarea>` of the raw source, and a `wrap._checkOverflow()` hook that the
 * table/kanban callers invoked after re-rendering or opening a panel, because
 * only then did the browser have real layout to measure.
 *
 * React removes the need for that hook. `_checkOverflow` existed to
 * re-measure after two things: the surrounding content changed, and the
 * kanban panel became visible. A `ResizeObserver` on the rendered node
 * covers both -- the panel becoming visible resizes the node from 0 to its
 * real height, which fires the observer just as reliably as an explicit call
 * would have. The `[value, isExpanded]` effect dependency covers the
 * table's re-render case directly. So there is no React equivalent of
 * `_checkOverflow`: nothing calls this component to tell it "re-measure now"
 * because it re-measures itself whenever there's a reason to.
 *
 * Persistence (`saveField`) is NOT this phase's concern -- Phase 3 owns the
 * hook that calls the `/api/jobs/update` endpoint. This component only
 * calls `onSave` with the new value, and only when the value actually
 * changed (mirroring the original's `if (value !== (job[field] || ''))`
 * guard, which is what keeps a click-to-edit-then-change-your-mind blur from
 * writing anything).
 */
import {
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { parseMarkdown } from "../../lib/markdown";
import styles from "./MarkdownField.module.css";

export interface MarkdownFieldProps {
  label: string;
  value: string;
  /**
   * Class the consuming view (table row / kanban modal) puts on every field
   * wrapper -- `.detail-field` in jobs.html, `.modal-field` in kanban.html.
   * Mirrors `cfg.fieldClass` from job_fields.js's `create(ctx)`.
   */
  fieldClass?: string;
  /**
   * Class the consuming view puts on its roomier text fields -- `.notes-field`
   * in jobs.html, absent (empty string) in kanban.html. Mirrors
   * `cfg.notesClass`.
   */
  notesClass?: string;
  /**
   * The colour the bottom fade-out gradient blends into when the field is
   * clamped. jobs.html fades to `var(--card)` (the default); kanban.html
   * fades to `var(--bg)`. See MarkdownField.module.css for why this is a CSS
   * custom property instead of two stylesheet copies.
   */
  fadeColor?: string;
  /**
   * Called on blur, only when the edited value differs from `value`. Phase 2
   * does not persist anything itself -- Phase 3's save hook wires this up.
   */
  onSave?: (value: string) => void | Promise<void>;
}

export function MarkdownField({
  label,
  value,
  fieldClass = "",
  notesClass = "",
  fadeColor,
  onSave,
}: MarkdownFieldProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  const [draft, setDraft] = useState(value);
  const renderedRef = useRef<HTMLDivElement>(null);

  // Re-measure whenever the rendered content or the expanded state changes.
  // useLayoutEffect (not useEffect) so the "Show more" button never flashes
  // in after the first paint -- it's either there or not by the time the
  // browser shows anything.
  useLayoutEffect(() => {
    if (isExpanded) return;
    const el = renderedRef.current;
    if (!el) return;
    setOverflowing(el.scrollHeight > el.clientHeight + 1);
    // isEditing is a dependency (not just value/isExpanded) because the
    // rendered <div> unmounts while editing and remounts on blur -- a fresh
    // DOM node needs a fresh measurement even when `value` itself didn't
    // change (e.g. the edit was cancelled by re-typing the same text).
  }, [value, isExpanded, isEditing]);

  // Re-measure on resize too -- e.g. the kanban modal going from display:none
  // to visible, or the window/column width changing. jsdom has no
  // ResizeObserver (see MarkdownField.test.tsx / setupTests.ts for the
  // stub), so this is guarded to no-op rather than throw when it's absent;
  // production browsers all have it.
  useLayoutEffect(() => {
    const el = renderedRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (isExpanded) return;
      setOverflowing(el.scrollHeight > el.clientHeight + 1);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [isExpanded]);

  const wrapperClassName = [fieldClass, notesClass, "markdown-field"].filter(Boolean).join(" ");
  const wrapperStyle: CSSProperties | undefined = fadeColor
    ? ({ "--markdown-fade-color": fadeColor } as CSSProperties)
    : undefined;

  function startEditing() {
    setDraft(value);
    setIsEditing(true);
  }

  function handleBlur() {
    const trimmed = draft.trim();
    setIsEditing(false);
    if (trimmed !== (value || "")) {
      void onSave?.(trimmed);
    }
  }

  const showToggle = overflowing || isExpanded;

  return (
    <div className={wrapperClassName} style={wrapperStyle}>
      <div className={styles.header}>
        <label>{label}</label>
        {!isEditing && (
          <button type="button" className={styles.editBtn} onClick={startEditing}>
            Edit
          </button>
        )}
      </div>

      {isEditing ? (
        <textarea
          data-testid="markdown-textarea"
          className={styles.textarea}
          value={draft}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onBlur={handleBlur}
        />
      ) : (
        <div
          ref={renderedRef}
          data-testid="markdown-rendered"
          className={[styles.rendered, isExpanded ? styles.expanded : ""].filter(Boolean).join(" ")}
        >
          {parseMarkdown(value)}
        </div>
      )}

      {!isEditing && showToggle && (
        <button
          type="button"
          className={styles.expandBtn}
          onClick={() => setIsExpanded((e) => !e)}
        >
          {isExpanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}
