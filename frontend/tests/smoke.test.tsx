import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../src/App";

function renderAt(path: string) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("App", () => {
  it("serves the jobs list at /", () => {
    // It fetches, so with no stubbed fetch it lands on its loading state --
    // enough to prove the route resolves to JobsPage rather than to nothing.
    renderAt("/");
    expect(screen.getByText(/loading jobs/i)).toBeInTheDocument();
  });

  it("serves the job view at /job", () => {
    renderAt("/job?company=Acme");
    expect(screen.queryByText(/loading jobs/i)).toBeNull();
  });

  /*
   * The basename is gone: the app is served from "/" now, not from the /app
   * staging mount (see main.tsx). What replaces the old basename trap is the
   * reverse hazard -- React routing a path Flask still owns.
   *
   * /kanban and /insights are Flask routes rendering Jinja. React never
   * receives them on a page load: the browser asks the server and the server
   * answers with a different page. A route here for either would fire only on
   * a client-side navigation to it, which is exactly the bug -- a blank panel
   * under a URL that renders fine on reload.
   */
  it("routes neither the board nor the insights view", () => {
    renderAt("/kanban");
    expect(screen.queryByText(/loading jobs/i)).toBeNull();
    expect(screen.queryByText(/not yet ported/i)).toBeNull();
  });

  it("keeps the view switcher on every page it does route", () => {
    // Without it the list is a page with no way off it: the board and the
    // insights view stay reachable only by typing their URLs.
    renderAt("/");
    expect(screen.getByRole("link", { name: "Kanban" })).toBeInTheDocument();

    renderAt("/job?company=Acme");
    expect(screen.getAllByRole("link", { name: "Insights" }).length)
      .toBeGreaterThan(0);
  });
});
