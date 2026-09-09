import "@testing-library/jest-dom/vitest";

/*
 * jsdom implements no layout at all -- no ResizeObserver, and scrollHeight /
 * clientHeight are always 0 (see tests/js/dom_stub.js's comment on the same
 * limitation for the legacy vanilla-JS suite). MarkdownField tolerates a
 * missing ResizeObserver at runtime (real browsers all have it), but a global
 * stub here lets tests exercise the resize-driven re-measurement path
 * instead of only the mount-time one. Individual tests still override
 * scrollHeight/clientHeight on specific elements to simulate overflow --
 * this stub only supplies the constructor jsdom is missing.
 */
if (typeof globalThis.ResizeObserver === "undefined") {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}
