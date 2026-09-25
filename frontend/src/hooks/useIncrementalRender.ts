/*
 * How many rows of a result set are actually in the DOM.
 *
 * Ports renderedCount / observeSentinel from src/templates/jobs.html. 1,088
 * rows of six cells each is ~6,500 nodes, and React does not make that free --
 * it makes it slower, because each one carries fibre overhead the vanilla
 * version's raw appendChild did not. The window grows when a sentinel at the
 * bottom scrolls into view.
 *
 * The distinction this exists to preserve: reaching the end of what has
 * *arrived* is not reaching the end of the *list*. With the first 50-row page
 * landed and the prefetch still running, rendered can equal available while
 * more is still coming -- so "there is nothing more to show" has to consider
 * both, or the loading row disappears a second into a five-second load.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export const RENDER_CHUNK = 50;

export interface UseIncrementalRenderOptions {
  /** Rows available to render right now -- not the size of the whole list. */
  available: number;
  /** More rows are still arriving from the server. */
  prefetching: boolean;
}

export function useIncrementalRender({
  available, prefetching,
}: UseIncrementalRenderOptions) {
  const [rendered, setRendered] = useState(RENDER_CHUNK);
  const sentinelRef = useRef<HTMLElement | null>(null);

  /*
   * A new result set starts at its top; an update to the one on screen does
   * not. Filter and sort changes call this; an arriving prefetch page or a
   * status edit does not, and keeps the reader where they are.
   */
  const resetToTop = useCallback(() => setRendered(RENDER_CHUNK), []);

  const atEnd = rendered >= available && !prefetching;

  // A callback ref rather than useEffect on a ref object: the sentinel unmounts
  // whenever the list empties and remounts when it refills, and a ref object
  // would hand the effect a node that is no longer in the document.
  const setSentinel = useCallback((node: HTMLElement | null) => {
    sentinelRef.current = node;
  }, []);

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || atEnd) return;
    // jsdom has no IntersectionObserver and the tests drive `rendered` through
    // growNow() instead, so this degrades to "no auto-growth" rather than
    // throwing.
    if (typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      setRendered((n) => Math.min(n + RENDER_CHUNK, Math.max(available, n)));
    });
    observer.observe(node);
    return () => observer.disconnect();
    // `rendered` is a dependency: the observer has to be rebuilt after each
    // growth, or a sentinel that never leaves the viewport (a short window, a
    // tall screen) fires once and then stops.
  }, [available, atEnd, rendered]);

  /** Grows the window by one chunk. Exported for tests and for a "show more"
   *  fallback where no observer exists. */
  const growNow = useCallback(() => {
    setRendered((n) => Math.min(n + RENDER_CHUNK, Math.max(available, n)));
  }, [available]);

  return {
    rendered: Math.min(rendered, available),
    atEnd,
    resetToTop,
    growNow,
    setSentinel,
  };
}
