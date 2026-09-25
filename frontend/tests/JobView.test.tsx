/*
 * The tabbed shell and the status rail.
 *
 * lib/timeline.ts already covers which nodes appear for a given row; these
 * cover the parts that only exist once it is on screen -- that a node is a
 * control and not a picture, that panels keep their state, and that the
 * fields the legacy panel made editable but the API rejects are not editable
 * here.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { JobView } from "../src/components/shared/JobView";
import { StatusRail } from "../src/components/shared/StatusRail";
import type { Interview, Job } from "../src/api/types";

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    company: "Fin", date_added: "2026-09-12", position_title: "Forward Deployed Engineer",
    link: "https://example.com/job", location: "San Francisco, CA",
    contacts: "", notes: "", outreach_date: "", date_applied: "2026-09-23",
    status: "Applied", followup_log: "",
    recruiter_id: null, recruiter_name: null, recruiter_agency: null,
    recruiter_from_triage: false,
    ...overrides,
  };
}

function round(overrides: Partial<Interview> = {}): Interview {
  return {
    company: "Fin", date_added: "2026-09-12", position_title: "Forward Deployed Engineer",
    link: "", id: 1, interview_type: "phone_screen", type_label: null, loop_id: null,
    scheduled_date: "2026-09-30", self_rating: null, notes: null,
    ...overrides,
  };
}

function renderView(props: Partial<React.ComponentProps<typeof JobView>> = {}) {
  const onSaveField = vi.fn();
  const onSaveCompanySection = vi.fn();
  const onDelete = vi.fn();
  render(
    <JobView
      job={{ ...makeJob(), job_summary: "## Requirements\n\n- A strong background" }}
      rounds={[]}
      interviewTypes={["phone_screen", "technical", "other"]}
      recruiters={[]}
      onSaveField={onSaveField}
      setRecruiter={vi.fn()}
      createRecruiter={vi.fn()}
      onAddInterview={vi.fn().mockResolvedValue({})}
      onDeleteInterview={vi.fn().mockResolvedValue({})}
      onSaveCompanySection={onSaveCompanySection}
      onDelete={onDelete}
      {...props}
    />,
  );
  return { onSaveField, onSaveCompanySection, onDelete };
}

describe("JobView tabs", () => {
  it("opens on Overview every time, never the last tab used", async () => {
    renderView();

    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute(
      "aria-selected", "true");
  });

  it("switches panels on click", async () => {
    renderView();

    await userEvent.click(screen.getByRole("tab", { name: "Prep" }));

    expect(screen.getByRole("tabpanel")).toHaveAttribute("id", "panel-Prep");
  });

  it("moves between tabs with the arrow keys", async () => {
    renderView();
    screen.getByRole("tab", { name: "Overview" }).focus();

    await userEvent.keyboard("{ArrowRight}");

    expect(screen.getByRole("tab", { name: "Company" })).toHaveAttribute(
      "aria-selected", "true");
  });

  it("wraps around at the ends", async () => {
    renderView();
    screen.getByRole("tab", { name: "Overview" }).focus();

    await userEvent.keyboard("{ArrowLeft}");

    expect(screen.getByRole("tab", { name: "Prep" })).toHaveAttribute(
      "aria-selected", "true");
  });

  it("keeps a visited panel mounted so returning to it loses nothing", async () => {
    renderView();

    await userEvent.click(screen.getByRole("tab", { name: "Prep" }));
    await userEvent.click(screen.getByRole("tab", { name: "Overview" }));

    // Still in the DOM, so a half-typed round survives the round trip.
    //
    // This asserts the attribute and nothing more, on purpose: jsdom does not
    // apply CSS-module stylesheets, so every class here is an identity string
    // with no styles behind it and toBeVisible() cannot see a display rule.
    // Whether `hidden` actually hides the panel is a CSS question, checked in
    // tests/panelHidden.test.ts -- see it for the bug that made the
    // distinction worth spelling out.
    const prep = document.querySelector("#panel-Prep");
    expect(prep).not.toBeNull();
    expect(prep).toHaveAttribute("hidden");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("id", "panel-Overview");
  });

  it("does not mount a panel that has never been opened", () => {
    renderView();

    expect(document.querySelector("#panel-Prep")).toBeNull();
  });

  it("calls onClose on Escape", async () => {
    const onClose = vi.fn();
    renderView({ onClose });

    await userEvent.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalled();
  });
});

describe("JobView fields", () => {
  it("renders location as static text, not an editable field", () => {
    // `location` is absent from EDITABLE_COLUMNS, so /api/jobs/update answers
    // 400 for it -- an editable box here would fail on every save.
    renderView();

    const label = screen.getByText("Location");
    const field = label.parentElement!;
    expect(within(field).queryByRole("textbox")).toBeNull();
    expect(field).toHaveTextContent("San Francisco, CA");
  });

  it("puts the delete control outside the tabs", async () => {
    const { onDelete } = renderView();

    await userEvent.click(screen.getByRole("button", { name: /delete this job/i }));

    expect(onDelete).toHaveBeenCalled();
  });
});

// --- the rail ---------------------------------------------------------------

function renderRail(job: Partial<Job> = {}, rounds: Interview[] = []) {
  const onSetStatus = vi.fn().mockResolvedValue(undefined);
  render(
    <StatusRail job={{ ...makeJob(job) }} rounds={rounds}
                onSetStatus={onSetStatus} onSaveNotes={vi.fn()} />,
  );
  return { onSetStatus };
}

describe("StatusRail", () => {
  it("sets the status when a node is clicked", async () => {
    // The timeline is the control; there is no separate <select> beside it.
    const { onSetStatus } = renderRail({ status: "Applied" });

    await userEvent.click(screen.getByRole("button", { name: /Phone Screen/ }));

    expect(onSetStatus).toHaveBeenCalledWith("Phone Screen");
  });

  it("marks the furthest reached node as the current step", () => {
    renderRail({ status: "Applied" });

    expect(screen.getByRole("button", { name: /Applied/ }))
      .toHaveAttribute("aria-current", "step");
  });

  it("says 'date unknown' rather than inventing one", () => {
    renderRail({ status: "Phone Screen", date_applied: "" });

    expect(screen.getAllByText("date unknown").length).toBeGreaterThan(0);
  });

  it("shows a free-text date exactly as stored", () => {
    renderRail({ status: "Applied", date_applied: "emailed Tuesday" });

    expect(screen.getByText("emailed Tuesday")).toBeInTheDocument();
  });

  it("renders a rejected job as an end-cap, with no Offer node", () => {
    renderRail({ status: "Rejected" });

    expect(screen.queryByRole("button", { name: /Offer/ })).toBeNull();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
  });

  it("offers the terminal outcomes only while the job is still open", async () => {
    const { onSetStatus } = renderRail({ status: "Applied" });

    await userEvent.click(screen.getByRole("button", { name: /mark rejected/i }));

    expect(onSetStatus).toHaveBeenCalledWith("Rejected");
  });

  it("names the tail rather than drawing empty nodes for it", () => {
    // Four path statuses have zero rows in the whole tracker; drawing them
    // would put five hollow circles under one filled one.
    renderRail({ status: "Applied" });

    expect(screen.getByText(/then Technical · System Design · Behavioral · Offer/))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /System Design/ })).toBeNull();
  });

  it("nests recorded rounds under their node", () => {
    renderRail({ status: "Phone Screen" },
               [round({ scheduled_date: "2026-09-30", type_label: "Intro chat" })]);

    expect(screen.getByText(/Intro chat/)).toBeInTheDocument();
  });

  it("warns when the status is one the vocabulary cannot place", () => {
    renderRail({ status: "Outreached" });

    expect(screen.getByText(/isn.t one of the tracked stages/)).toBeInTheDocument();
  });
});
