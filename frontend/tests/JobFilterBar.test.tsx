/*
 * The filter controls.
 *
 * The filtering itself is covered without a DOM in jobFilters.test.ts; these
 * cover what only exists once the controls are on screen -- which recruiters
 * get offered, what the date shortcuts actually set, and that the two banners
 * appear when and only when they should.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { JobFilterBar, recruiterOptions } from "../src/components/shared/JobFilterBar";
import { localISODate, startOfWeekISO } from "../src/lib/jobFields";
import type { Job } from "../src/api/types";

function job(overrides: Partial<Job> = {}): Job {
  return {
    company: "Acme", date_added: "2026-05-10", position_title: "Engineer",
    link: "", location: "", contacts: "", notes: "", outreach_date: "",
    date_applied: "", status: "Tracking", followup_log: "",
    recruiter_id: null, recruiter_name: null, recruiter_agency: null,
    recruiter_from_triage: false,
    ...overrides,
  };
}

function renderBar(props: Partial<React.ComponentProps<typeof JobFilterBar>> = {}) {
  const onChange = vi.fn();
  render(
    <JobFilterBar
      jobs={[job()]}
      statuses={["Tracking", "Applied", "Rejected"]}
      filters={{}}
      onChange={onChange}
      funnel={null}
      matched={1}
      total={1}
      {...props}
    />,
  );
  return { onChange };
}

describe("JobFilterBar", () => {
  it("offers every status plus both sentinels", () => {
    renderBar();
    const select = screen.getByLabelText("Filter by status");

    expect([...select.querySelectorAll("option")].map((o) => o.textContent))
      .toEqual(["All statuses", "Tracking", "Applied", "Rejected", "(no status)"]);
  });

  it("offers only recruiters attached to a loaded row", () => {
    // Not /api/recruiters: it costs ~2s and lists 107 people, most attached to
    // no tracked job.
    renderBar({
      jobs: [
        job({ recruiter_id: 7, recruiter_name: "Dana Cole", recruiter_agency: "AceStack" }),
        job({ recruiter_id: null }),
      ],
    });
    const select = screen.getByLabelText("Filter by recruiter");

    expect([...select.querySelectorAll("option")].map((o) => o.textContent))
      .toEqual(["All recruiters", "(no recruiter)", "Dana Cole — AceStack"]);
  });

  it("reports the filtered count against the loaded count", () => {
    renderBar({ matched: 12, total: 122 });
    expect(screen.getByText("12 of 122 jobs")).toBeInTheDocument();
  });

  it("just counts when nothing is filtered out", () => {
    renderBar({ matched: 122, total: 122 });
    expect(screen.getByText("122 jobs")).toBeInTheDocument();
  });

  it("passes the typed query up", async () => {
    const { onChange } = renderBar();

    await userEvent.type(screen.getByLabelText("Search jobs"), "s");

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ q: "s" }));
  });

  it("Today sets both ends of the range to today", async () => {
    const { onChange } = renderBar();

    await userEvent.click(screen.getByRole("button", { name: "Today" }));

    const today = localISODate(new Date());
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ dateFrom: today, dateTo: today }));
  });

  it("This week runs from the start of the week to today", async () => {
    const { onChange } = renderBar();

    await userEvent.click(screen.getByRole("button", { name: "This week" }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      dateFrom: startOfWeekISO(new Date()), dateTo: localISODate(new Date()),
    }));
  });

  it("Clear dates clears only the dates", async () => {
    const { onChange } = renderBar({ filters: { q: "stripe", status: "Applied" } });

    await userEvent.click(screen.getByRole("button", { name: "Clear dates" }));

    expect(onChange).toHaveBeenCalledWith({
      q: "stripe", status: "Applied", dateFrom: "", dateTo: "",
    });
  });

  it("shows the funnel banner, and says archived rows are included", () => {
    // The population note matters: the funnel counts archived rows, so the
    // list it links to has to admit it is showing more than the table usually
    // does.
    renderBar({ funnel: { stage: "screen", source: "auto" } });

    expect(screen.getByText(/at an interview stage · auto-submitted/))
      .toBeInTheDocument();
    expect(screen.getByText(/archived included/)).toBeInTheDocument();
  });

  it("has no funnel banner without a funnel", () => {
    renderBar();
    expect(screen.queryByText(/Filtered from/)).toBeNull();
  });

  it("shows the search banner for the current term, not the loaded one", () => {
    renderBar({ filters: { q: "stripe" } });
    expect(screen.getByText(/Searching for/)).toBeInTheDocument();
  });

  it("drops the search banner when the box is emptied", () => {
    renderBar({ filters: { q: "  " } });
    expect(screen.queryByText(/Searching for/)).toBeNull();
  });
});

describe("recruiterOptions", () => {
  it("labels by name and agency together", () => {
    // Agency alone collides: two AceStack recruiters give two options both
    // reading "AceStack LLC" with no way to tell them apart.
    const options = recruiterOptions([
      job({ recruiter_id: 1, recruiter_name: "Dana", recruiter_agency: "AceStack" }),
      job({ recruiter_id: 2, recruiter_name: "Sam", recruiter_agency: "AceStack" }),
    ]);

    expect(options.map(([, label]) => label))
      .toEqual(["Dana — AceStack", "Sam — AceStack"]);
  });

  it("lists each recruiter once however many roles they pitched", () => {
    const options = recruiterOptions([
      job({ recruiter_id: 1, recruiter_name: "Dana" }),
      job({ recruiter_id: 1, recruiter_name: "Dana" }),
    ]);

    expect(options).toHaveLength(1);
  });

  it("sorts by the label, not by id", () => {
    const options = recruiterOptions([
      job({ recruiter_id: 9, recruiter_name: "Aaron" }),
      job({ recruiter_id: 1, recruiter_name: "Zoe" }),
    ]);

    expect(options.map(([id]) => id)).toEqual([9, 1]);
  });

  it("falls back to a label rather than an empty option", () => {
    const options = recruiterOptions([job({ recruiter_id: 3 })]);
    expect(options[0][1]).toBeTruthy();
  });
});
