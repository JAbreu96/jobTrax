/*
 * Adding a job.
 *
 * The cases that matter are the failure ones. The dialog holds text somebody
 * pasted and typed, so every path that could throw it away is worth pinning --
 * a duplicate link, a refused host, a validation miss.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AddJobModal } from "../src/components/shared/AddJobModal";
import { dailyGoalProgress, DAILY_GOAL } from "../src/lib/dailyGoal";
import type { Job } from "../src/api/types";

const STATUSES = ["Tracking", "Applied", "Rejected"];

function renderModal(props: Partial<React.ComponentProps<typeof AddJobModal>> = {}) {
  const onSubmit = vi.fn().mockResolvedValue({} as Job);
  const onFetchUrl = vi.fn().mockResolvedValue({});
  const onClose = vi.fn();
  render(
    <AddJobModal statuses={STATUSES} onSubmit={onSubmit}
                 onFetchUrl={onFetchUrl} onClose={onClose} {...props} />,
  );
  return { onSubmit, onFetchUrl, onClose };
}

const field = (name: string) => screen.getByRole("textbox", { name: new RegExp(name, "i") });

describe("AddJobModal", () => {
  it("refuses to submit without a company or a title", async () => {
    const { onSubmit } = renderModal();

    await userEvent.click(screen.getByRole("button", { name: "Add job" }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/required/i);
  });

  it("submits what was typed", async () => {
    const { onSubmit } = renderModal();

    await userEvent.type(field("company"), "Stripe");
    await userEvent.type(field("position title"), "Engineer");
    await userEvent.click(screen.getByRole("button", { name: "Add job" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ company: "Stripe", position_title: "Engineer" }));
  });

  it("closes once the job is added", async () => {
    const { onClose } = renderModal();

    await userEvent.type(field("company"), "Stripe");
    await userEvent.type(field("position title"), "Engineer");
    await userEvent.click(screen.getByRole("button", { name: "Add job" }));

    expect(onClose).toHaveBeenCalled();
  });

  it("keeps the dialog open and the text intact when the server refuses", async () => {
    // A duplicate link answers 409. Closing here means retyping a posting you
    // already pasted.
    const onSubmit = vi.fn().mockRejectedValue(
      new Error("This URL is already tracked (Stripe, added 2026-01-01)."));
    const { onClose } = renderModal({ onSubmit });

    await userEvent.type(field("company"), "Stripe");
    await userEvent.type(field("position title"), "Engineer");
    await userEvent.click(screen.getByRole("button", { name: "Add job" }));

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/already tracked/);
    expect(field("company")).toHaveValue("Stripe");
  });

  it("fills the form from a fetched posting", async () => {
    const onFetchUrl = vi.fn().mockResolvedValue({
      company: "Stripe", position_title: "Engineer",
      location: "Remote", job_summary: "## About",
    });
    renderModal({ onFetchUrl });

    await userEvent.type(field("posting url"), "https://boards.greenhouse.io/x");
    await userEvent.click(screen.getByRole("button", { name: "Fetch" }));

    expect(await screen.findByDisplayValue("Stripe")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Remote")).toBeInTheDocument();
  });

  it("keeps what was already typed when the fetch fills only some fields", async () => {
    const onFetchUrl = vi.fn().mockResolvedValue({ company: "Stripe" });
    renderModal({ onFetchUrl });

    await userEvent.type(field("position title"), "My own title");
    await userEvent.type(field("posting url"), "https://boards.greenhouse.io/x");
    await userEvent.click(screen.getByRole("button", { name: "Fetch" }));

    expect(await screen.findByDisplayValue("Stripe")).toBeInTheDocument();
    expect(field("position title")).toHaveValue("My own title");
  });

  it("falls back to the pasted URL when the posting carries none", async () => {
    const onFetchUrl = vi.fn().mockResolvedValue({ company: "Stripe" });
    renderModal({ onFetchUrl });

    await userEvent.type(field("posting url"), "https://boards.greenhouse.io/x");
    await userEvent.click(screen.getByRole("button", { name: "Fetch" }));

    // The Link field specifically -- the URL box still holds it too, which is
    // why this asserts on the destination rather than on the document.
    await screen.findByDisplayValue("Stripe");
    expect(screen.getByRole("textbox", { name: /^link/i }))
      .toHaveValue("https://boards.greenhouse.io/x");
  });

  it("shows the server's reason when a host refuses to be fetched", async () => {
    // LinkedIn, Indeed and Glassdoor are rejected server-side with a message
    // telling you to paste the details manually. That message is the useful
    // part; a generic failure would send you looking for a bug.
    const onFetchUrl = vi.fn().mockRejectedValue(
      new Error("LinkedIn/Indeed/Glassdoor block automated fetching — paste the details manually."));
    renderModal({ onFetchUrl });

    await userEvent.type(field("posting url"), "https://linkedin.com/jobs/1");
    await userEvent.click(screen.getByRole("button", { name: "Fetch" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/paste the details manually/);
  });

  it("does not fetch an empty URL", async () => {
    const { onFetchUrl } = renderModal();

    expect(screen.getByRole("button", { name: "Fetch" })).toBeDisabled();
    expect(onFetchUrl).not.toHaveBeenCalled();
  });

  it("closes on Escape", async () => {
    // The Jinja modal closes on a backdrop click only, so a keyboard user
    // could open it and not get out.
    const { onClose } = renderModal();

    await userEvent.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalled();
  });

  it("closes on a backdrop click but not on a click inside", async () => {
    const { onClose } = renderModal();

    await userEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("dailyGoalProgress", () => {
  function job(overrides: Partial<Job> = {}): Job {
    return {
      company: "Acme", date_added: "2026-05-10", position_title: "Engineer",
      link: "", location: "", contacts: "", notes: "", outreach_date: "",
      date_applied: "", status: "Tracking", followup_log: "",
      recruiter_id: null, recruiter_name: null, recruiter_agency: null,
      recruiter_from_triage: false, ...overrides,
    };
  }

  it("counts rows applied today", () => {
    const jobs = [
      job({ status: "Applied", date_applied: "2026-05-10" }),
      job({ status: "Applied", date_applied: "2026-05-10" }),
    ];
    expect(dailyGoalProgress(jobs, "2026-05-10").applied).toBe(2);
  });

  it("ignores rows applied on another day", () => {
    const jobs = [job({ status: "Applied", date_applied: "2026-05-09" })];
    expect(dailyGoalProgress(jobs, "2026-05-10").applied).toBe(0);
  });

  it("needs both the status and the date, not either", () => {
    // Status alone counts every job ever applied to; date alone counts a row
    // that has since moved on to Phone Screen.
    const jobs = [
      job({ status: "Applied", date_applied: "" }),
      job({ status: "Phone Screen", date_applied: "2026-05-10" }),
    ];
    expect(dailyGoalProgress(jobs, "2026-05-10").applied).toBe(0);
  });

  it("is met at the goal, not one past it", () => {
    const jobs = Array.from({ length: DAILY_GOAL }, () =>
      job({ status: "Applied", date_applied: "2026-05-10" }));
    expect(dailyGoalProgress(jobs, "2026-05-10").met).toBe(true);
  });

  it("is not met one short", () => {
    const jobs = Array.from({ length: DAILY_GOAL - 1 }, () =>
      job({ status: "Applied", date_applied: "2026-05-10" }));
    expect(dailyGoalProgress(jobs, "2026-05-10").met).toBe(false);
  });
});
