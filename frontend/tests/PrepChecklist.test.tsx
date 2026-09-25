/*
 * The prep checklist.
 *
 * Two of these pin behaviour that is easy to "improve" into a bug: a ticked
 * item must not move, and Enter must add without closing the box. Both exist
 * because the list is used in the ten minutes before a screen, where losing
 * your place or having to re-open a box for every line is the whole cost.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PrepChecklist } from "../src/components/shared/PrepChecklist";
import type { PrepItem, PrepKind } from "../src/api/types";

let nextId = 1;
function item(kind: PrepKind, body: string, done = 0): PrepItem {
  return {
    id: nextId++, company: "Fin", date_added: "2026-09-12",
    position_title: "FDE", link: "", kind, body, done,
    sort_order: 0, source: "hand", created_at: "2026-09-25",
  };
}

function renderList(items: PrepItem[] = []) {
  const onAdd = vi.fn().mockResolvedValue({});
  const onSetDone = vi.fn().mockResolvedValue({});
  const onEdit = vi.fn().mockResolvedValue({});
  const onDelete = vi.fn().mockResolvedValue({});
  render(
    <PrepChecklist items={items} onAdd={onAdd} onSetDone={onSetDone}
                   onEdit={onEdit} onDelete={onDelete}
                   confirm={() => true} />,
  );
  return { onAdd, onSetDone, onEdit, onDelete };
}

describe("PrepChecklist", () => {
  it("renders both sections even with nothing in either", () => {
    renderList();

    expect(screen.getByRole("heading", { name: "Before the round" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Questions to ask" })).toBeInTheDocument();
  });

  it("points at Claude when a section is empty", () => {
    renderList();

    expect(screen.getByText(/Ask Claude to build a prep plan/)).toBeInTheDocument();
  });

  it("splits tasks from questions", () => {
    renderList([item("task", "Read the whitepaper"),
                item("question", "What does success look like?")]);

    expect(screen.getByRole("checkbox", { name: "Read the whitepaper" }))
      .toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "What does success look like?" }))
      .toBeInTheDocument();
  });

  it("counts what is done against the section total", () => {
    renderList([item("task", "a", 1), item("task", "b"), item("task", "c")]);

    expect(screen.getByText("1/3")).toBeInTheDocument();
  });

  it("keeps a ticked item where it was", async () => {
    // Sorting done items to the bottom would reshuffle the list under your
    // hand in the ten minutes before a screen.
    renderList([item("task", "first", 1), item("task", "second")]);

    // Anchored: an unanchored /first|second/ also matches each row's
    // "Remove: first" control, which interleaves with the bodies.
    const bodies = screen.getAllByRole("button", { name: /^(first|second)$/ })
      .map((b) => b.textContent);
    expect(bodies).toEqual(["first", "second"]);
  });

  it("ticks an item through the callback", async () => {
    const items = [item("task", "Read the whitepaper")];
    const { onSetDone } = renderList(items);

    await userEvent.click(screen.getByRole("checkbox", { name: "Read the whitepaper" }));

    expect(onSetDone).toHaveBeenCalledWith(items[0].id, true);
  });

  it("unticks an item that was done", async () => {
    const items = [item("task", "Read the whitepaper", 1)];
    const { onSetDone } = renderList(items);

    await userEvent.click(screen.getByRole("checkbox", { name: "Read the whitepaper" }));

    expect(onSetDone).toHaveBeenCalledWith(items[0].id, false);
  });

  it("opens an editor when the body is clicked, and saves on blur", async () => {
    const items = [item("task", "Old text")];
    const { onEdit } = renderList(items);

    await userEvent.click(screen.getByRole("button", { name: "Old text" }));
    const box = screen.getByRole("textbox");
    await userEvent.clear(box);
    await userEvent.type(box, "New text");
    await userEvent.tab();

    expect(onEdit).toHaveBeenCalledWith(items[0].id, "New text");
  });

  it("restores the original when an edit is blanked", async () => {
    // The API refuses a blank body, so saving would fail and leave the row
    // showing text the server never accepted.
    const items = [item("task", "Old text")];
    const { onEdit } = renderList(items);

    await userEvent.click(screen.getByRole("button", { name: "Old text" }));
    await userEvent.clear(screen.getByRole("textbox"));
    await userEvent.tab();

    expect(onEdit).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Old text" })).toBeInTheDocument();
  });

  it("does not save an edit that changed nothing", async () => {
    const { onEdit } = renderList([item("task", "Same text")]);

    await userEvent.click(screen.getByRole("button", { name: "Same text" }));
    await userEvent.tab();

    expect(onEdit).not.toHaveBeenCalled();
  });

  it("adds on Enter and stays open for the next one", async () => {
    // Adding one item is almost always adding three; re-opening the box each
    // time is what stops you writing the fourth.
    const { onAdd } = renderList();

    await userEvent.click(screen.getByRole("button", { name: /Add a task/ }));
    await userEvent.type(screen.getByRole("textbox"), "Read the whitepaper{Enter}");

    expect(onAdd).toHaveBeenCalledWith({ kind: "task", body: "Read the whitepaper" });
    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("adds a question as a question, not a task", async () => {
    const { onAdd } = renderList();

    await userEvent.click(screen.getByRole("button", { name: /Add a question/ }));
    await userEvent.type(screen.getByRole("textbox"), "Why this role?{Enter}");

    expect(onAdd).toHaveBeenCalledWith({ kind: "question", body: "Why this role?" });
  });

  it("does not add a blank item", async () => {
    const { onAdd } = renderList();

    await userEvent.click(screen.getByRole("button", { name: /Add a task/ }));
    await userEvent.type(screen.getByRole("textbox"), "   {Enter}");

    expect(onAdd).not.toHaveBeenCalled();
  });

  it("deletes an item once confirmed", async () => {
    const items = [item("task", "Read the whitepaper")];
    const { onDelete } = renderList(items);

    await userEvent.click(
      screen.getByRole("button", { name: "Remove: Read the whitepaper" }));

    expect(onDelete).toHaveBeenCalledWith(items[0].id);
  });

  it("keeps a delete behind a confirmation", async () => {
    const items = [item("task", "Read the whitepaper")];
    const onDelete = vi.fn().mockResolvedValue({});
    render(
      <PrepChecklist items={items} onAdd={vi.fn()} onSetDone={vi.fn()}
                     onEdit={vi.fn()} onDelete={onDelete}
                     confirm={() => false} />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Remove: Read the whitepaper" }));

    expect(onDelete).not.toHaveBeenCalled();
  });

  it("does not offer a count for a section with nothing in it", () => {
    renderList([item("task", "only a task")]);

    const questions = screen.getByRole("heading", { name: "Questions to ask" })
      .parentElement!;
    expect(within(questions).queryByText("0/0")).toBeNull();
  });
});
