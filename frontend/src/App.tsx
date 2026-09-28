import { Routes, Route } from "react-router-dom";
import JobsPage from "./components/pages/JobsPage";
import JobViewPage from "./components/pages/JobViewPage";
import { AppHeader } from "./components/shared/AppHeader";
import "./styles/tokens.css";

/*
 * The jobs list is React's for real as of this rung: Flask's "/" serves this
 * shell and src/templates/jobs.html is gone.
 *
 * There are no /kanban or /insights routes here, and their absence is the
 * point. Those two paths are still Flask routes rendering Jinja, so React
 * never receives them -- the placeholders that used to sit here ("not yet
 * ported") were only ever reachable under the /app staging mount, and keeping
 * them now would claim this app owns paths it does not. Phase 5 adds the
 * board and Phase 7 the insights view, each moving its Flask route onto the
 * shell at the same time.
 *
 * The router itself is mounted in main.tsx, not here, so tests can wrap
 * <App /> in a MemoryRouter without nesting two routers.
 */
export default function App() {
  return (
    <>
      {/* Both routes are the table view: /job is one of its rows opened. */}
      <AppHeader active="table" />
      <Routes>
        <Route path="/" element={<JobsPage />} />
        {/* The job key is four columns, so it rides in the query string rather
            than the path -- `link` is itself a URL and does not survive being a
            path segment. */}
        <Route path="/job" element={<JobViewPage />} />
      </Routes>
    </>
  );
}
