import { describe, it, expect } from "vitest";
import { assetFileName } from "../src/lib/assetNames";

describe("assetFileName", () => {
  it("pins the stylesheet to the name app_shell.html links", () => {
    // A bare "[name][extname]" writes index.css here, and the template's
    // conditional link then finds nothing and renders the page unstyled.
    expect(assetFileName({ names: ["index.css"] })).toBe("assets/main[extname]");
  });

  it("leaves other assets under their own names", () => {
    expect(assetFileName({ names: ["logo.svg"] })).toBe("assets/[name][extname]");
    expect(assetFileName({ names: ["Inter.woff2"] })).toBe("assets/[name][extname]");
  });

  it("does not fall over when rollup reports no names", () => {
    expect(assetFileName({})).toBe("assets/[name][extname]");
  });
});
