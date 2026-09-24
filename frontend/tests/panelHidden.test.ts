/*
 * That `hidden` on a tab panel actually hides it.
 *
 * This is a CSS test rather than a rendering test because it has to be. The
 * component sets the `hidden` attribute, and JobView.test.tsx asserts that --
 * but jsdom does not apply CSS-module stylesheets, so a rendering test sees
 * class names with no styles behind them and toBeVisible() cannot tell the
 * difference between hidden and not.
 *
 * It shipped broken exactly once for that reason. `.panel { display: flex }`
 * is a class selector and outranks the user-agent's `[hidden] { display: none
 * }`, so switching tabs moved the indicator and left every panel that had been
 * opened stacked down the page -- with the whole unit suite green. It was
 * found by looking at the page.
 *
 * Reading the stylesheet is the cheapest thing that would have caught it.
 * Same approach as tests/test_stylesheets.py on the Python side.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Read off disk rather than imported. Vite's `?raw` does not help here: for a
// `.module.css` the CSS-modules transform runs first and hands back the class
// proxy object, not the text. Resolved from the working directory because
// under jsdom `import.meta.url` is not a file: URL.
const css = readFileSync(
  resolve(process.cwd(), "src/components/shared/JobView.module.css"),
  "utf8",
);

describe("JobView.module.css", () => {
  it("overrides the panel's display when [hidden] is set", () => {
    const rule = /\.panel\[hidden\]\s*\{[^}]*display:\s*none/;
    expect(css).toMatch(rule);
  });

  it("still lays the visible panel out as a column", () => {
    // If this ever stops being a class with its own `display`, the override
    // above is no longer needed and this test should go with it.
    expect(css).toMatch(/\.panel\s*\{[^}]*display:\s*flex/);
  });
});
