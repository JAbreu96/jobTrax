/*
 * The prep checklist and the questions to ask.
 *
 * One list rendered as two sections. `done` means "finished" on a task and
 * "asked" on a question -- the second is the one that earns this its place on
 * the tab, because knowing which questions you have already used is a thing you
 * need mid-loop and cannot get from anywhere else.
 *
 * Ticked items stay where they are rather than sorting to the bottom. A list
 * that reshuffles as you tick loses your place at the exact moment you are
 * least able to afford it -- which is five minutes before a screen.
 */
import { useState } from "react";
import type { PrepItem, PrepKind } from "../../api/types";
import type { ConfirmFn } from "../../lib/dialogs";
import { defaultConfirm } from "../../lib/dialogs";
import styles from "./PrepChecklist.module.css";

export interface PrepChecklistProps {
  items: PrepItem[];
  onAdd: (fields: { kind: PrepKind; body: string }) => Promise<unknown>;
  onSetDone: (id: number, done: boolean) => Promise<unknown>;
  onEdit: (id: number, body: string) => Promise<unknown>;
  onDelete: (id: number) => Promise<unknown>;
  confirm?: ConfirmFn;
}

const SECTIONS: { kind: PrepKind; heading: string; empty: string; add: string }[] = [
  {
    kind: "task",
    heading: "Before the round",
    empty: "Nothing to do yet. Ask Claude to build a prep plan for this job, or add a task.",
    add: "Add a task",
  },
  {
    kind: "question",
    heading: "Questions to ask",
    empty: "No questions yet. Ask Claude for some, or write your own.",
    add: "Add a question",
  },
];

export function PrepChecklist({
  items, onAdd, onSetDone, onEdit, onDelete, confirm = defaultConfirm,
}: PrepChecklistProps) {
  return (
    <>
      {SECTIONS.map(({ kind, heading, empty, add }) => {
        const section = items.filter((i) => i.kind === kind);
        const done = section.filter((i) => i.done).length;
        return (
          <section key={kind} className={styles.section}>
            <div className={styles.sectionHead}>
              <h3 className={styles.heading}>{heading}</h3>
              {section.length > 0 && (
                <span className={styles.count}>{done}/{section.length}</span>
              )}
            </div>

            {section.length === 0
              ? <p className={styles.empty}>{empty}</p>
              : (
                <ul className={styles.list}>
                  {section.map((item) => (
                    <PrepRow key={item.id} item={item} onSetDone={onSetDone}
                             onEdit={onEdit} onDelete={onDelete} confirm={confirm} />
                  ))}
                </ul>
              )}

            <AddRow label={add} onAdd={(body) => onAdd({ kind, body })} />
          </section>
        );
      })}
    </>
  );
}

function PrepRow({ item, onSetDone, onEdit, onDelete, confirm }: {
  item: PrepItem;
  onSetDone: PrepChecklistProps["onSetDone"];
  onEdit: PrepChecklistProps["onEdit"];
  onDelete: PrepChecklistProps["onDelete"];
  confirm: ConfirmFn;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.body);

  function commit() {
    setEditing(false);
    const trimmed = draft.trim();
    // A blank body is refused by the API, so an empty edit would fail the save
    // and leave the row showing text the server never took. Restore instead.
    if (!trimmed) { setDraft(item.body); return; }
    if (trimmed !== item.body) void onEdit(item.id, trimmed);
  }

  return (
    <li className={styles.row}>
      <input
        type="checkbox"
        className={styles.check}
        checked={Boolean(item.done)}
        aria-label={item.body}
        onChange={(e) => { void onSetDone(item.id, e.target.checked); }}
      />
      {editing ? (
        <textarea
          className={styles.editor}
          value={draft}
          autoFocus
          rows={2}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
        />
      ) : (
        <button
          type="button"
          className={`${styles.body} ${item.done ? styles.bodyDone : ""}`}
          onClick={() => { setDraft(item.body); setEditing(true); }}
        >
          {item.body}
        </button>
      )}
      <button
        type="button"
        className={styles.remove}
        aria-label={`Remove: ${item.body}`}
        onClick={() => {
          // ConfirmFn is synchronous -- window.confirm blocks. Awaiting it
          // would typecheck as Promise<boolean> and be wrong about what it is.
          if (confirm(`Remove "${item.body}"?`)) void onDelete(item.id);
        }}
      >
        ×
      </button>
    </li>
  );
}

function AddRow({ label, onAdd }: { label: string; onAdd: (body: string) => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");

  async function submit() {
    const body = draft.trim();
    if (!body) { setOpen(false); setDraft(""); return; }
    await onAdd(body);
    // Stays open, cleared: adding one item is almost always adding three.
    setDraft("");
  }

  if (!open) {
    return (
      <button type="button" className={styles.addToggle} onClick={() => setOpen(true)}>
        + {label}
      </button>
    );
  }

  return (
    <div className={styles.addRow}>
      <textarea
        className={styles.editor}
        value={draft}
        autoFocus
        rows={2}
        placeholder={label}
        onChange={(e) => setDraft(e.target.value)}
        // Enter submits, Shift+Enter breaks a line: these are one-liners, and
        // reaching for the mouse after every item is what stops you writing
        // the fourth one.
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submit(); }
          if (e.key === "Escape") { setOpen(false); setDraft(""); }
        }}
        onBlur={() => { if (!draft.trim()) setOpen(false); }}
      />
      <button type="button" className={styles.addConfirm} onClick={() => void submit()}>
        Add
      </button>
    </div>
  );
}
