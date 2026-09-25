/*
 * That the "there is more text below" fade only appears when there is.
 *
 * A CSS test, for the same reason as panelHidden.test.ts: jsdom applies no
 * CSS-module stylesheet and reports every scrollHeight as 0, so a rendering
 * test can neither see the gradient nor make a field overflow. Reading the
 * rule is the only thing here that can fail when the bug comes back.
 *
 * The bug: the fade was hung on `.rendered:not(.expanded)`, the same selector
 * as the clamp, so every clamped field got a gradient over its last line
 * whether or not anything was clipped. On a short field -- a two-line note in
 * the status rail, a three-sentence company section -- it read as text cut off
 * mid-sentence. Found by looking at the page; no test could have seen it.
 *
 * The two selectors cannot be merged back together. `max-height` has to apply
 * before the component measures, or scrollHeight equals clientHeight and
 * nothing is ever detected as overflowing; `.clamped` is added only after that
 * measurement comes back true.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(
  resolve(process.cwd(), "src/components/shared/MarkdownField.module.css"),
  "utf8",
);

describe("MarkdownField.module.css", () => {
  it("clamps every unexpanded field, so overflow can be measured at all", () => {
    expect(css).toMatch(/\.rendered:not\(\.expanded\)\s*\{[^}]*max-height/);
  });

  it("fades only a field measured as overflowing, not every clamped one", () => {
    expect(css).toMatch(/\.rendered\.clamped::after\s*\{/);
    expect(css).not.toMatch(/\.rendered:not\(\.expanded\)::after/);
  });
});
