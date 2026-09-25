/*
 * The read-only jobs table.
 *
 * The cases worth pinning are the two the vanilla table got right for
 * non-obvious reasons: sorting happens before windowing, and "rendered
 * everything that has arrived" is not "rendered the whole list".
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

function renderTable(props: Partial<React.ComponentProps<typeof JobsTable>> = {}) {
  const onOpenJob = vi.fn();
  const onSortChange = vi.fn();
  const result = render(
    <JobsTable jobs={[job()]} sort={null}
               onSortChange={onSortChange} onOpenJob={onOpenJob} {...props} />,
  );
  return { onOpenJob, onSortChange, ...result };
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
    const rows = [job({ company: "Globex" })];
    const { onOpenJob } = renderTable({ jobs: rows });

    await userEvent.click(screen.getByText("Globex"));

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
                        onSortChange={onSortChange} onOpenJob={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Company" }));
    expect(onSortChange).toHaveBeenLastCalledWith(
      { column: "company", direction: "desc" });

    rerender(<JobsTable jobs={[job()]} sort={{ column: "company", direction: "desc" }}
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

    const first = within(bodyRows()[0]).getByText(/^Co /);
    expect(first).toHaveTextContent(`Co ${String(jobs.length - 1).padStart(4, "0")}`);
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
