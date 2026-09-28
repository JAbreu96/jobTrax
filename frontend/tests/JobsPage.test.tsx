/*
 * The job list page's half of the ?q= contract, and the header that replaced
 * the Jinja one.
 *
 * These take over from tests/test_search_deeplink.py, which is deleted with
 * jobs.html. That file could only assert on the *text* of an inline script
 * nothing in the repo executed -- "this substring appears in the template".
 * The behaviour is reachable now, so these run it instead: what the box is
 * filled with, and what the address bar says afterwards.
 *
 * Insights links here with ?q=<company>, so the deeplink is a live contract
 * with a view that is still Jinja and still has no idea React is on the other
 * end.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import JobsPage from "../src/components/pages/JobsPage";
import { AppHeader } from "../src/components/shared/AppHeader";
import type { Job } from "../src/api/types";

function job(overrides: Partial<Job> = {}): Job {
  return {
    company: "Acme", date_added: "2026-09-12", position_title: "Engineer",
    link: "", location: "", contacts: "", notes: "", outreach_date: "",
    date_applied: "", status: "Tracking", followup_log: "",
    recruiter_id: null, recruiter_name: null, recruiter_agency: null,
    recruiter_from_triage: false, ...overrides,
  };
}

const JOBS = [job({ company: "Acme" }), job({ company: "Globex", link: "g" })];

function serve() {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = url.startsWith("/api/config")
      ? { status_values: ["", "Tracking", "Applied"], interview_types: [] }
      : { jobs: JOBS, next_cursor: null };
    return { ok: true, status: 200, statusText: "OK", json: async () => body };
  }));
}

/**
 * JobsPage reads `window.location.search` directly rather than the router's,
 * because it is also the thing that writes it back with replaceState -- so the
 * real history object is what has to be set up here, not a MemoryRouter entry.
 */
function renderPage(search = "") {
  window.history.replaceState(null, "", `/${search}`);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/${search}`]}>
        <JobsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const searchBox = () => screen.getByRole("searchbox");

beforeEach(serve);
afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("JobsPage and the ?q= deeplink", () => {
  it("fills the search box from the URL it arrived with", async () => {
    renderPage("?q=Globex");

    await waitFor(() => expect(searchBox()).toHaveValue("Globex"));
  });

  it("filters to the linked company rather than merely showing the term", async () => {
    // Filling the box and filtering the list are two separate wires. The
    // Jinja version had them separate too -- its search listener updated the
    // URL for a while without re-rendering the table.
    renderPage("?q=Globex");

    // Scoped to the table body: the search box itself now also holds
    // "Globex", so an unscoped display-value query matches two elements.
    await waitFor(() => expect(document.querySelector("tbody")).not.toBeNull());
    const rows = within(document.querySelector("tbody")!);
    expect(rows.getByDisplayValue("Globex")).toBeInTheDocument();
    expect(rows.queryByDisplayValue("Acme")).toBeNull();
  });

  it("writes what is typed back into the address bar", async () => {
    renderPage();
    await waitFor(() => expect(searchBox()).toBeInTheDocument());

    await userEvent.type(searchBox(), "Acme");

    await waitFor(() => expect(window.location.search).toBe("?q=Acme"));
  });

  it("keeps the path when it rewrites the query", async () => {
    // replaceState with a bare query string drops the path: the address bar
    // would read "?q=Acme" with no "/" in front of it.
    renderPage();
    await waitFor(() => expect(searchBox()).toBeInTheDocument());

    await userEvent.type(searchBox(), "Acme");

    await waitFor(() => expect(window.location.pathname).toBe("/"));
  });

  it("replaces the history entry instead of pushing one per keystroke", async () => {
    const push = vi.spyOn(window.history, "pushState");
    renderPage();
    await waitFor(() => expect(searchBox()).toBeInTheDocument());

    await userEvent.type(searchBox(), "Acme");

    // Otherwise Back walks out of a twelve-character search one letter at a
    // time.
    expect(push).not.toHaveBeenCalled();
    push.mockRestore();
  });

  it("drops ?q= from the URL when the box is cleared", async () => {
    renderPage("?q=Acme");
    await waitFor(() => expect(searchBox()).toHaveValue("Acme"));

    await userEvent.clear(searchBox());

    await waitFor(() => expect(window.location.search).toBe(""));
  });

  it("keeps the rest of the query string while rewriting ?q=", async () => {
    // ?include_archived=1 is how insights deeplinks an archived company.
    // Rebuilding the query from the term alone would silently drop it and
    // answer "no matches" for a row that is right there.
    renderPage("?include_archived=1");
    await waitFor(() => expect(searchBox()).toBeInTheDocument());

    await userEvent.type(searchBox(), "Acme");

    await waitFor(() =>
      expect(window.location.search).toContain("include_archived=1"));
    expect(window.location.search).toContain("q=Acme");
  });
});

describe("AppHeader", () => {
  it("links the two views React does not route", () => {
    // Plain hrefs on purpose: /kanban and /insights are Flask routes serving
    // Jinja. A <Link> would hand them to a router with no match and render a
    // blank page under a URL that works fine on reload.
    render(<AppHeader active="table" />);

    expect(screen.getByRole("link", { name: "Kanban" }))
      .toHaveAttribute("href", "/kanban");
    expect(screen.getByRole("link", { name: "Insights" }))
      .toHaveAttribute("href", "/insights");
  });

  it("marks the view being shown", () => {
    render(<AppHeader active="table" />);

    expect(screen.getByRole("link", { name: "Table" }))
      .toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Kanban" }))
      .not.toHaveAttribute("aria-current");
  });

  it("uses the shared stylesheet's class names, not hashed module ones", () => {
    // header / h1 / nav.view-nav are global rules in src/static/job_views.css,
    // shared with the templates still on Jinja. A CSS module would hash these
    // names, the global rules would stop matching, and the nav would render
    // unstyled -- with every test still green, since jsdom applies no CSS.
    render(<AppHeader active="table" />);

    const nav = screen.getByRole("navigation");
    expect(nav.className).toBe("view-nav");
    expect(screen.getByRole("link", { name: "Table" }).className).toBe("active");
  });
});
