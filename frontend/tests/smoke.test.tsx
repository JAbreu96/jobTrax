import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../src/App";

function renderAt(path: string, basename?: string) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]} basename={basename}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// Proves the Vite + Vitest + React Testing Library + jsdom wiring works.
// Phases 1-3 depend on this scaffold being sound before they add real tests.
describe("App", () => {
  it("renders the jobs placeholder at /", () => {
    renderAt("/");
    expect(screen.getByText(/jobs table — not yet ported/i)).toBeInTheDocument();
  });

  it("routes to each placeholder", () => {
    renderAt("/kanban");
    expect(screen.getByText(/kanban board — not yet ported/i)).toBeInTheDocument();
  });

  // The Phase 0 trap. The app is mounted under Flask's throwaway /app route
  // with a matching basename (see main.tsx), so the router must strip that
  // prefix before matching. Get the basename wrong and every route falls
  // through to nothing -- a blank page, not an error, which is exactly the
  // failure that reads as "the build is broken" when the build is fine.
  it("matches routes under the /app basename the staging mount serves", () => {
    renderAt("/app/insights", "/app");
    expect(screen.getByText(/insights — not yet ported/i)).toBeInTheDocument();
  });

  it("renders nothing when the basename does not match the path", () => {
    renderAt("/app/insights");
    expect(screen.queryByText(/not yet ported/i)).toBeNull();
  });
});
