import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";

const queryClient = new QueryClient();

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("#root element not found");
}

// basename="/app" is a Phase 0 staging trap: none of "/", "/kanban" or
// "/insights" are handed to React yet -- those Flask routes still serve the
// existing Jinja templates. This whole app is mounted under the throwaway
// /app route instead (see app_shell() in src/jobs_gui.py) so it doesn't
// collide with them. This is temporary: as each real view is cut over in
// Phases 4, 5 and 7, its route moves off /app and onto its real path, and
// once all three are cut over this basename goes away entirely.
ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename="/app">
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
