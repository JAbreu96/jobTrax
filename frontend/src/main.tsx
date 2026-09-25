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

// No basename: the app is served from "/" now, not from the /app staging
// mount. app_shell() in src/jobs_gui.py answers /app with a redirect so the
// links written during the rewrite keep working.
//
// /kanban and /insights are still Flask's. React must not route them -- it
// only ever sees a path Flask handed it, and Flask has no route for those, so
// a link to one has to be a plain <a> that leaves the app (see AppHeader).
ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
