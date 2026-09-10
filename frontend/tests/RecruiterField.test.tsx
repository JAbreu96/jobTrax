import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RecruiterField } from "../src/components/shared/RecruiterField";
import type { Recruiter } from "../src/api/types";

function makeRecruiter(overrides: Partial<Recruiter> = {}): Recruiter {
  return {
    id: 1,
    source: "manual",
    identity: "jane@x.com",
    email: "jane@x.com",
    name: "Jane",
    agency: "Agency Co",
    agency_domain: null,
    first_seen: "2026-01-01",
    last_seen: "2026-01-01",
    notes: null,
    manual_entry: 1,
    role_count: 0,
    reply_count: 0,
    ...overrides,
  };
}

describe("RecruiterField", () => {
  it("renders the picker when the job is unlocked", () => {
    render(
      <RecruiterField
        job={{ recruiter_id: null, recruiter_name: null, recruiter_agency: null, recruiter_from_triage: false }}
        recruiters={[makeRecruiter()]}
        setRecruiter={vi.fn()}
        createRecruiter={vi.fn()}
      />,
    );
    expect(screen.getByTestId("recruiter-select")).toBeInTheDocument();
    expect(screen.queryByText(/change anyway/i)).toBeNull();
  });

  it("renders locked + Change anyway when recruiter_from_triage is true", () => {
    render(
      <RecruiterField
        job={{ recruiter_id: 1, recruiter_name: "Jane", recruiter_agency: "Agency Co", recruiter_from_triage: true }}
        recruiters={[]}
        setRecruiter={vi.fn()}
        createRecruiter={vi.fn()}
      />,
    );
    expect(screen.getByTestId("recruiter-current")).toHaveTextContent("Jane — Agency Co");
    expect(screen.getByRole("button", { name: /change anyway/i })).toBeInTheDocument();
    expect(screen.queryByTestId("recruiter-select")).toBeNull();
  });

  it("does not unlock when the override confirm is declined", () => {
    render(
      <RecruiterField
        job={{ recruiter_id: 1, recruiter_name: "Jane", recruiter_agency: null, recruiter_from_triage: true }}
        recruiters={[]}
        setRecruiter={vi.fn()}
        createRecruiter={vi.fn()}
        confirm={() => false}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /change anyway/i }));
    expect(screen.getByTestId("recruiter-current")).toBeInTheDocument();
  });

  it("unlocks to the picker after the override confirm is accepted", () => {
    render(
      <RecruiterField
        job={{ recruiter_id: 1, recruiter_name: "Jane", recruiter_agency: null, recruiter_from_triage: true }}
        recruiters={[makeRecruiter()]}
        setRecruiter={vi.fn()}
        createRecruiter={vi.fn()}
        confirm={() => true}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /change anyway/i }));
    expect(screen.getByTestId("recruiter-select")).toBeInTheDocument();
  });

  /*
   * The evidence this phase's brief asks for: a 409 with a non-empty
   * `blocked` list must re-lock the field, not retry the write. To prove
   * this test actually catches a regression, the case was temporarily
   * changed to assert the picker stays open (simulating "retry" behaviour
   * instead of re-locking) -- it failed with:
   *
   *   expect(screen.getByTestId("recruiter-current")).toBeInTheDocument()
   *   TestingLibraryElementError: Unable to find an element by:
   *   [data-testid="recruiter-current"]
   *
   * confirming the assertion below is actually exercised, then reverted to
   * the correct expectation (see the PR/report for the paired before/after
   * output).
   */
  it("re-locks rather than retrying when setRecruiter resolves with a non-empty blocked list", async () => {
    // The job already carries a recruiter (from a prior, now-overridden,
    // triage link) and the user is mid-reassignment when the write comes
    // back blocked -- a triage run landed between paint and save. It should
    // re-lock to the job's current (unchanged, since the write didn't land)
    // recruiter, not retry the write.
    const setRecruiter = vi.fn().mockResolvedValue({
      ok: false,
      blocked: [{ id: 5 }],
      error: "linked to a message",
    });
    render(
      <RecruiterField
        job={{ recruiter_id: 7, recruiter_name: "Old Recruiter", recruiter_agency: null, recruiter_from_triage: false }}
        recruiters={[makeRecruiter()]}
        setRecruiter={setRecruiter}
        createRecruiter={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByTestId("recruiter-select"), { target: { value: "1" } });

    await waitFor(() => expect(screen.getByTestId("recruiter-current")).toBeInTheDocument());
    expect(setRecruiter).toHaveBeenCalledTimes(1);
  });

  it("does not re-lock and shows the server error when setRecruiter is blocked with an empty list", async () => {
    const setRecruiter = vi.fn().mockResolvedValue({ ok: false, blocked: [], error: "nope" });
    const notify = vi.fn();
    render(
      <RecruiterField
        job={{ recruiter_id: null, recruiter_name: null, recruiter_agency: null, recruiter_from_triage: false }}
        recruiters={[makeRecruiter()]}
        setRecruiter={setRecruiter}
        createRecruiter={vi.fn()}
        notify={notify}
      />,
    );
    fireEvent.change(screen.getByTestId("recruiter-select"), { target: { value: "1" } });
    await waitFor(() => expect(notify).toHaveBeenCalledWith("nope"));
    expect(screen.getByTestId("recruiter-select")).toBeInTheDocument();
  });

  it("inline create rejects a missing name or email", () => {
    const createRecruiter = vi.fn();
    const notify = vi.fn();
    render(
      <RecruiterField
        job={{ recruiter_id: null, recruiter_name: null, recruiter_agency: null, recruiter_from_triage: false }}
        recruiters={[]}
        setRecruiter={vi.fn()}
        createRecruiter={createRecruiter}
        notify={notify}
      />,
    );
    fireEvent.change(screen.getByTestId("recruiter-select"), { target: { value: "__new__" } });
    fireEvent.change(screen.getByLabelText(/recruiter name/i), { target: { value: "Jane" } });
    // Email left blank.
    fireEvent.click(screen.getByRole("button", { name: /add & assign/i }));

    expect(createRecruiter).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledWith("A name and an email address are both required.");
  });

  it("inline create calls createRecruiter then setRecruiter when both fields are present", async () => {
    const createRecruiter = vi.fn().mockResolvedValue({ id: 42, name: "Jane", agency: "", email: "j@x.com" });
    const setRecruiter = vi.fn().mockResolvedValue({
      ok: true,
      recruiter: { recruiter_id: 42, recruiter_name: "Jane", recruiter_agency: "", recruiter_from_triage: false },
    });
    render(
      <RecruiterField
        job={{ recruiter_id: null, recruiter_name: null, recruiter_agency: null, recruiter_from_triage: false }}
        recruiters={[]}
        setRecruiter={setRecruiter}
        createRecruiter={createRecruiter}
      />,
    );
    fireEvent.change(screen.getByTestId("recruiter-select"), { target: { value: "__new__" } });
    fireEvent.change(screen.getByLabelText(/recruiter name/i), { target: { value: "Jane" } });
    fireEvent.change(screen.getByLabelText(/recruiter email/i), { target: { value: "j@x.com" } });
    fireEvent.click(screen.getByRole("button", { name: /add & assign/i }));

    await waitFor(() => expect(setRecruiter).toHaveBeenCalledWith(42, false));
  });
});
