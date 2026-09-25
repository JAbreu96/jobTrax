/*
 * The job view as a drawer over the list, the way Simplify does it.
 *
 * Chrome only: the panel, the scrim, and the three ways out of it. What goes
 * inside is the same JobViewPage the full-page route renders -- see App.tsx
 * for how one URL picks between them.
 *
 * Closing is `navigate(-1)` rather than a state flag, and that is the whole
 * reason this is a route at all. The drawer was opened by a history push, so
 * the browser Back button closes it whether or not this component cooperates.
 * A separate "is the drawer open" boolean would let those two disagree: Back
 * would change the URL out from under an open drawer, or the X would leave a
 * history entry pointing at a job nobody is looking at.
 */
import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import styles from "./JobDrawer.module.css";

export function JobDrawer({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const panel = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef<Element | null>(null);

  const close = () => navigate(-1);

  useEffect(() => {
    /*
     * Focus moves into the panel and comes back to the row on close. Without
     * this the keyboard user's focus stays on a row behind the scrim: Tab
     * walks the list they cannot see, and Escape closes a drawer they were
     * never in.
     */
    restoreFocus.current = document.activeElement;
    panel.current?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        navigate(-1);
      }
    };
    document.addEventListener("keydown", onKey);

    /*
     * The page behind does not scroll while the drawer is open -- otherwise a
     * wheel gesture past the end of the panel scrolls the list underneath,
     * which looks like the drawer moving. The panel keeps its own scroll.
     */
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
      (restoreFocus.current as HTMLElement | null)?.focus?.();
    };
    // navigate is stable; this runs once per drawer open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* Same URL, no backgroundLocation: the full-page route takes over in place.
     replace, not push, so Back still returns to the list rather than
     re-opening the drawer on the job just expanded. */
  const expand = () =>
    navigate(location.pathname + location.search, { replace: true });

  return (
    <div className={styles.scrim} onClick={close} data-testid="drawer-scrim">
      <div
        ref={panel}
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-label="Job details"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.bar}>
          <button type="button" className={styles.barButton} onClick={expand}>
            Open full page
          </button>
          <button type="button" className={styles.close} aria-label="Close"
                  onClick={close}>×</button>
        </div>
        <div className={styles.content}>{children}</div>
      </div>
    </div>
  );
}
