import { Routes, Route, useLocation } from "react-router-dom";
import type { Location } from "react-router-dom";
import JobsPage from "./components/pages/JobsPage";
import JobViewPage from "./components/pages/JobViewPage";
import { AppHeader } from "./components/shared/AppHeader";
import { JobDrawer } from "./components/shared/JobDrawer";
import "./styles/tokens.css";

/*
 * The jobs list is React's for real: Flask's "/" serves this shell and
 * src/templates/jobs.html is gone.
 *
 * There are no /kanban or /insights routes here, and their absence is the
 * point. Those two paths are still Flask routes rendering Jinja, so React
 * never receives them -- keeping a route for either would claim this app owns
 * a path it does not. Phase 5 adds the board and Phase 7 the insights view,
 * each moving its Flask route onto the shell at the same time.
 *
 * The router itself is mounted in main.tsx, not here, so tests can wrap
 * <App /> in a MemoryRouter without nesting two routers.
 */

/*
 * /job renders two ways, and which one is not a property of the URL.
 *
 * Clicking a row opens the job as a drawer over the list, the way Simplify
 * does: the list stays on screen, keeps its scroll position, its filters and
 * its loaded rows, and Back closes the drawer. Arriving at the same URL cold
 * -- a bookmark, a pasted link, a hard refresh -- has no list to drape a
 * drawer over, so it renders as the full page.
 *
 * The difference is carried in history state: a row click pushes /job with a
 * `backgroundLocation`, which is the list's own location. When it is present
 * the routes below are matched against *it* rather than against the current
 * URL, so JobsPage stays mounted and mounted means not refetched -- and the
 * drawer is rendered on top from the real location. When it is absent (state
 * does not survive a reload, which is exactly right here) the same <Routes>
 * matches /job and renders the page.
 *
 * Both are the same JobViewPage. The drawer is chrome around it, not a second
 * implementation of it.
 */
interface DrawerState {
  backgroundLocation?: Location;
}

export default function App() {
  const location = useLocation();
  const background = (location.state as DrawerState | null)?.backgroundLocation;

  return (
    <>
      {/* Both routes are the table view: /job is one of its rows opened. */}
      <AppHeader active="table" />
      <Routes location={background ?? location}>
        <Route path="/" element={<JobsPage />} />
        {/* The job key is four columns, so it rides in the query string rather
            than the path -- `link` is itself a URL and does not survive being a
            path segment. */}
        <Route path="/job" element={<JobViewPage />} />
      </Routes>

      {background && (
        <Routes>
          <Route path="/job" element={
            <JobDrawer><JobViewPage layout="drawer" /></JobDrawer>
          } />
        </Routes>
      )}
    </>
  );
}
