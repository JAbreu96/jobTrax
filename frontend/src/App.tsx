import { Routes, Route } from "react-router-dom";
import JobsPage from "./components/pages/JobsPage";
import JobViewPage from "./components/pages/JobViewPage";
import "./styles/tokens.css";

// The board and insights are still their own cutovers. The jobs list is real
// as of this rung, but read-only -- Flask's "/" still serves the Jinja table,
// and this lives at /app until the React one can edit.
function KanbanPlaceholder() {
  return <h1>Kanban board — not yet ported</h1>;
}

function InsightsPlaceholder() {
  return <h1>Insights — not yet ported</h1>;
}

// The router itself (with basename="/app") is mounted in main.tsx, not here,
// so tests can wrap <App /> in their own Router (e.g. MemoryRouter) without
// nesting two routers. See main.tsx for the basename comment -- it's a
// Phase 0 staging trap: none of "/", "/kanban" or "/insights" are handed to
// React yet, those Flask routes still serve the existing Jinja templates.
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<JobsPage />} />
      <Route path="/kanban" element={<KanbanPlaceholder />} />
      <Route path="/insights" element={<InsightsPlaceholder />} />
      {/* The job key is four columns, so it rides in the query string rather
          than the path -- `link` is itself a URL and does not survive being a
          path segment. */}
      <Route path="/job" element={<JobViewPage />} />
    </Routes>
  );
}
