/*
 * The title bar and view switcher, ported from the <header> block that every
 * Jinja template carries (jobs.html:240-248, kanban.html, insights.html).
 *
 * Deleting jobs.html deletes the only copy of this that "/" had, and without
 * it the React list is a page with no way off it -- the board and the
 * insights view would still exist and be unreachable except by typing a URL.
 *
 * Two things here are deliberate:
 *
 * No CSS module. `header`, `h1` and `nav.view-nav` are global rules in
 * src/static/job_views.css, shared with the two templates that are still
 * Jinja, and the shell links that sheet. Restating them in a module would put
 * a second copy of the nav's styling in the tree -- exactly the drift
 * tests/test_stylesheets.py exists to prevent. (The opposite call was right
 * for the goal badge in JobsPage: that one is inside a module-styled toolbar
 * whose hashed class names those global selectors cannot reach.)
 *
 * Plain <a>, not <Link>. React routes "/" and "/job" and nothing else --
 * /kanban and /insights are Flask routes serving Jinja. A <Link> to one would
 * push the path into history and hand it to a router that has no match for
 * it, which renders a blank page under a URL that works perfectly on reload.
 */

export type ViewName = "table" | "kanban" | "insights";

const VIEWS: Array<{ name: ViewName; label: string; href: string }> = [
  { name: "table", label: "Table", href: "/" },
  { name: "kanban", label: "Kanban", href: "/kanban" },
  { name: "insights", label: "Insights", href: "/insights" },
];

/*
 * The templates also put a stats line and a goal badge in this bar. Neither
 * moves here: the "N of M" count is already rendered by JobFilterBar beside
 * the controls it describes, and the goal badge by JobsPage's toolbar. A
 * second copy of either would be a second thing to keep in step.
 */
export function AppHeader({ active }: { active: ViewName }) {
  return (
    <header>
      <h1>Job Tracker</h1>
      <nav className="view-nav">
        {VIEWS.map((v) => (
          <a key={v.name} href={v.href}
             className={v.name === active ? "active" : undefined}
             aria-current={v.name === active ? "page" : undefined}>
            {v.label}
          </a>
        ))}
      </nav>
    </header>
  );
}
