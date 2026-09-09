import { Routes, Route } from "react-router-dom";

// Phase 0 placeholders. Real UI ports land in later phases:
//   /         -> Phase 4/5 (jobs table)
//   /kanban   -> Phase 5 (kanban board)
//   /insights -> Phase 7 (funnel/silence/recruiter/interview views)
function JobsPlaceholder() {
  return <h1>Jobs table — not yet ported</h1>;
}

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
      <Route path="/" element={<JobsPlaceholder />} />
      <Route path="/kanban" element={<KanbanPlaceholder />} />
      <Route path="/insights" element={<InsightsPlaceholder />} />
    </Routes>
  );
}
