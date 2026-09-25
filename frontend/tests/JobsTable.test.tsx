/*
 * The jobs table.
 *
 * The cases worth pinning are the ones the vanilla table got right for
 * non-obvious reasons: sorting happens before windowing, "rendered everything
 * that has arrived" is not "rendered the whole list", and an editable cell has
 * to swallow the click that would otherwise navigate away from the row you are
 * trying to edit.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { JobsTable, countLabel } from "../src/components/shared/JobsTable";
import { RENDER_CHUNK } from "../src/hooks/useIncrementalRender";
import type { Job } from "../src/api/types";

function job(overrides: Partial<Job> = {}): Job {
  return {
    company: "Acme", date_added: "2026-09-12", position_title: "Engineer",
    link: "", location: "New York, NY", contacts: "", notes: "",
    outreach_date: "", date_applied: "", status: "Tracking", followup_log: "",
    recruiter_id: null, recruiter_name: null, recruiter_agency: null,
    recruiter_from_triage: false,
    ...overrides,
  };
}

function many(n: number): Job[] {
  return Array.from({ length: n }, (_, i) =>
    job({ company: `Co ${String(i).padStart(4, "0")}`, link: `l${i}` }));
}

const STATUSES = ["", "Tracking", "Applied", "Phone Screen", "Rejected"];

function renderTable(props: Partial<React.ComponentProps<typeof JobsTable>> = {}) {
  const onOpenJob = vi.fn();
  const onSortChange = vi.fn();
  const onSaveField = vi.fn().mockResolvedValue(true);
  const result = render(
    <JobsTable jobs={[job()]} sort={null} statuses={STATUSES}
               onSortChange={onSortChange} onOpenJob={onOpenJob}
               onSaveField={onSaveField} {...props} />,
  );
  return { onOpenJob, onSortChange, onSaveField, ...result };
}

function bodyRows() {
  return within(document.querySelector("tbody")!).queryAllByRole("row");
}

describe("JobsTable", () => {
  it("renders the five columns the Jinja table has", () => {
    renderTable();

    for (const name of ["Company", "Title", "Location", "Date Added", "Status"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("opens a job when its row is clicked", async () => {
    const rows = [job({ company: "Globex", position_title: "Engineer" })];
    const { onOpenJob } = renderTable({ jobs: rows });

    await userEvent.click(screen.getByText("Engineer"));

    expect(onOpenJob).toHaveBeenCalledWith(rows[0]);
  });

  it("opens a job from the keyboard", async () => {
    // The Jinja rows are click-only. That is the one thing about the original
    // not worth porting faithfully.
    const rows = [job({ company: "Globex" })];
    const { onOpenJob } = renderTable({ jobs: rows });

    bodyRows()[0].focus();
    await userEvent.keyboard("{Enter}");

    expect(onOpenJob).toHaveBeenCalledWith(rows[0]);
  });

  it("cycles a header asc, desc, then off so a click can undo itself", async () => {
    const { onSortChange, rerender } = renderTable();

    await userEvent.click(screen.getByRole("button", { name: "Company" }));
    expect(onSortChange).toHaveBeenLastCalledWith(
      { column: "company", direction: "asc" });

    rerender(<JobsTable jobs={[job()]} sort={{ column: "company", direction: "asc" }}
                        statuses={STATUSES} onSaveField={vi.fn().mockResolvedValue(true)}
                        onSortChange={onSortChange} onOpenJob={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Company" }));
    expect(onSortChange).toHaveBeenLastCalledWith(
      { column: "company", direction: "desc" });

    rerender(<JobsTable jobs={[job()]} sort={{ column: "company", direction: "desc" }}
                        statuses={STATUSES} onSaveField={vi.fn().mockResolvedValue(true)}
                        onSortChange={onSortChange} onOpenJob={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Company" }));
    expect(onSortChange).toHaveBeenLastCalledWith(null);
  });

  it("announces the sort direction on the header cell", () => {
    renderTable({ sort: { column: "company", direction: "desc" } });

    expect(screen.getByRole("button", { name: "Company" }).closest("th"))
      .toHaveAttribute("aria-sort", "descending");
  });

  it("sorts before windowing, not after", () => {
    // Windowing first and sorting the window reorders fifty arbitrary rows and
    // calls it a sort -- the rest of the list never moves. With more rows than
    // one chunk, the first row after a descending sort must be the last of the
    // whole list, not the last of the first chunk.
    const jobs = many(RENDER_CHUNK * 3);
    renderTable({ jobs, sort: { column: "company", direction: "desc" } });

    // The company is an <input> now, so read its value rather than its text.
    const first = within(bodyRows()[0]).getByRole("textbox");
    expect(first).toHaveValue(`Co ${String(jobs.length - 1).padStart(4, "0")}`);
  });

  it("renders only the first chunk of a long list", () => {
    renderTable({ jobs: many(RENDER_CHUNK * 3) });

    expect(bodyRows()).toHaveLength(RENDER_CHUNK);
  });

  it("renders a short list whole, with no loading row", () => {
    renderTable({ jobs: many(3) });

    expect(bodyRows()).toHaveLength(3);
    expect(screen.queryByText("Loading…")).toBeNull();
  });

  it("keeps the loading row up while the prefetch is still running", () => {
    // The trap: rendered can equal available after only the first page has
    // landed. That is the end of what arrived, not the end of the list.
    renderTable({ jobs: many(3), prefetching: true });

    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("says the list is short when a page failed", () => {
    renderTable({ jobs: many(3), truncated: true });

    expect(screen.getByText(/stopped loading early/)).toBeInTheDocument();
  });

  it("does not cry truncation on a healthy list", () => {
    renderTable({ jobs: many(3) });

    expect(screen.queryByText(/stopped loading early/)).toBeNull();
  });
});

describe("JobsTable editing", () => {
  it("does not open the row when the company cell is clicked", async () => {
    // Otherwise placing a cursor in the field navigates away from the row you
    // are trying to edit.
    const { onOpenJob } = renderTable({ jobs: [job({ company: "Globex" })] });

    await userEvent.click(screen.getByRole("textbox"));

    expect(onOpenJob).not.toHaveBeenCalled();
  });

  it("saves a renamed company on blur", async () => {
    const rows = [job({ company: "Globex" })];
    const { onSaveField } = renderTable({ jobs: rows });

    const cell = screen.getByRole("textbox");
    await userEvent.clear(cell);
    await userEvent.type(cell, "Globex Inc");
    await userEvent.tab();

    expect(onSaveField).toHaveBeenCalledWith(rows[0], "company", "Globex Inc");
  });

  it("does not save a company that did not change", async () => {
    const { onSaveField } = renderTable({ jobs: [job({ company: "Globex" })] });

    await userEvent.click(screen.getByRole("textbox"));
    await userEvent.tab();

    expect(onSaveField).not.toHaveBeenCalled();
  });

  it("restores the old name rather than sending a blank one", async () => {
    // The server refuses a blank company; sending it would fail and leave the
    // cell showing nothing.
    const { onSaveField } = renderTable({ jobs: [job({ company: "Globex" })] });

    const cell = screen.getByRole("textbox");
    await userEvent.clear(cell);
    await userEvent.tab();

    expect(onSaveField).not.toHaveBeenCalled();
    expect(cell).toHaveValue("Globex");
  });

  it("puts the old name back when the rename is refused", async () => {
    // A rename moves the row to a new primary key and can collide with a job
    // already at it. The server answers 409 and writes nothing, so showing the
    // new name would be a lie about what is stored.
    const onSaveField = vi.fn().mockResolvedValue(false);
    render(
      <JobsTable jobs={[job({ company: "Globex" })]} sort={null} statuses={STATUSES}
                 onSortChange={vi.fn()} onOpenJob={vi.fn()} onSaveField={onSaveField} />,
    );

    const cell = screen.getByRole("textbox");
    await userEvent.clear(cell);
    await userEvent.type(cell, "Acme");
    await userEvent.tab();

    expect(cell).toHaveValue("Globex");
  });

  it("reverts an edit on Escape without saving", async () => {
    const { onSaveField } = renderTable({ jobs: [job({ company: "Globex" })] });

    const cell = screen.getByRole("textbox");
    await userEvent.clear(cell);
    await userEvent.type(cell, "Typo{Escape}");

    expect(onSaveField).not.toHaveBeenCalled();
    expect(cell).toHaveValue("Globex");
  });

  it("saves a status change", async () => {
    const rows = [job({ status: "Tracking" })];
    const { onSaveField } = renderTable({ jobs: rows });

    await userEvent.selectOptions(screen.getByRole("combobox"), "Applied");

    expect(onSaveField).toHaveBeenCalledWith(rows[0], "status", "Applied");
  });

  it("does not open the row when the status picker is used", async () => {
    const { onOpenJob } = renderTable();

    await userEvent.click(screen.getByRole("combobox"));

    expect(onOpenJob).not.toHaveBeenCalled();
  });

  it("offers every status the server accepts, including the blank one", () => {
    renderTable();

    expect([...screen.getByRole("combobox").querySelectorAll("option")]
      .map((o) => o.textContent))
      .toEqual(["(none)", "Tracking", "Applied", "Phone Screen", "Rejected"]);
  });
});

describe("countLabel", () => {
  it("refuses to quote a total it does not have yet", () => {
    // "50 of 1088" mid-prefetch would be a lie: 1088 is how many have arrived.
    expect(countLabel(50, 200, true)).toBe("50 of 200 loaded so far…");
  });

  it("reports the window against the whole list once loaded", () => {
    expect(countLabel(50, 200, false)).toBe("50 of 200");
  });

  it("just counts when everything is on screen", () => {
    expect(countLabel(3, 3, false)).toBe("3 jobs");
  });

  it("does not pluralise a single job", () => {
    expect(countLabel(1, 1, false)).toBe("1 job");
  });
});
