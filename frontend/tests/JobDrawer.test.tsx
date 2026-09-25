/*
 * Opening a job as a drawer over the list.
 *
 * What is worth pinning here is not that a panel appears -- it is that one URL
 * renders two ways and that the three exits agree with each other. A drawer
 * whose close button and whose Back button disagree leaves history pointing at
 * a job nobody is looking at, which shows up later as a reload landing
 * somewhere nobody asked for.
 *
 * Driven through <App /> rather than <JobDrawer /> alone, because the
 * behaviour under test lives in the seam between them: which location the
 * routes are matched against.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../src/App";
import type { Job } from "../src/api/types";

function job(overrides: Partial<Job> = {}): Job {
  return {
    company: "Acme", date_added: "2026-09-12", position_title: "Engineer",
    link: "", location: "New York, NY", contacts: "", notes: "",
    outreach_date: "", date_applied: "", status: "Tracking", followup_log: "",
    recruiter_id: null, recruiter_name: null, recruiter_agency: null,
    recruiter_from_triage: false, ...overrides,
  };
}

const JOBS = [job({ company: "Globex", position_title: "Platform Engineer" })];

function serve() {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    let body: unknown = { jobs: JOBS, next_cursor: null };
    if (url.startsWith("/api/config")) {
      body = { status_values: ["", "Tracking", "Applied"], interview_types: ["Phone Screen"] };
    } else if (url.startsWith("/api/jobs/detail")) {
      body = {
        job: JOBS[0], job_summary: "A role description.",
        interviews: [], prep_items: [], company_profile: null,
      };
    } else if (url.startsWith("/api/recruiters")) {
      body = { recruiters: [] };
    }
    return { ok: true, status: 200, statusText: "OK", json: async () => body };
  }));
}

function renderApp(entries: string[] = ["/"]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={entries}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Clicks the one row in the list, which is how a drawer is opened at all. */
async function openTheDrawer() {
  renderApp();
  const title = await screen.findByText("Platform Engineer");
  await userEvent.click(title);
  return await screen.findByRole("dialog", { name: /job details/i });
}

const listRows = () =>
  document.querySelector("tbody")
    ? within(document.querySelector("tbody")!).queryAllByRole("row")
    : [];

beforeEach(serve);
afterEach(() => vi.unstubAllGlobals());

describe("opening a job from the list", () => {
  it("opens it as a drawer, not as a new page", async () => {
    await openTheDrawer();

    expect(screen.getByRole("dialog", { name: /job details/i }))
      .toBeInTheDocument();
  });

  it("leaves the list on screen behind it", async () => {
    // The whole point of a drawer over a page: the row you came from is still
    // visible, so the next job is one click away rather than one Back and one
    // click.
    await openTheDrawer();

    expect(listRows()).toHaveLength(1);
  });

  it("shows the job inside the drawer", async () => {
    const drawer = await openTheDrawer();

    expect(await within(drawer).findByText("A role description."))
      .toBeInTheDocument();
  });
});

describe("the ways out of the drawer", () => {
  it("closes on Escape", async () => {
    await openTheDrawer();

    await userEvent.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("closes on the close button", async () => {
    const drawer = await openTheDrawer();

    await userEvent.click(within(drawer).getByRole("button", { name: "Close" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("closes on a click outside it, but not on one inside", async () => {
    const drawer = await openTheDrawer();

    await userEvent.click(drawer);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("drawer-scrim"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("leaves the list behind once it closes, not a blank page", async () => {
    // Closing pops the history entry the row click pushed. Get that wrong --
    // by tracking "open" in component state instead -- and the URL stays at
    // /job with no drawer on it, which a reload turns into a page nobody
    // asked for.
    await openTheDrawer();

    await userEvent.keyboard("{Escape}");

    await waitFor(() => expect(listRows()).toHaveLength(1));
  });
});

describe("the same URL arrived at cold", () => {
  it("renders the full page, with no drawer and no list", async () => {
    // A bookmark, a pasted link, a hard refresh: history state does not
    // survive any of them, and there is no list to drape a drawer over.
    renderApp(["/job?company=Globex&date_added=2026-09-12&position_title=Platform+Engineer&link="]);

    expect(await screen.findByText("A role description.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(listRows()).toHaveLength(0);
  });

  it("is the destination of the drawer's own expand button", async () => {
    const drawer = await openTheDrawer();

    await userEvent.click(within(drawer).getByRole("button", { name: /open full page/i }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("A role description.")).toBeInTheDocument();
    expect(listRows()).toHaveLength(0);
  });
});

/*
 * Not tested here, and deliberately not: the `window.location.pathname !== "/"`
 * guard on JobsPage's ?q= effect. These tests drive a MemoryRouter, which
 * never touches window.location, so any assertion about it would pass without
 * the guard and prove nothing. The guard is defensive rather than a fix for a
 * reachable bug -- the effect fires only when the search term changes, and the
 * box is behind the scrim while the drawer is open -- but it is one line
 * standing between a mounted list and a job's deep link, so it stays.
 */
