import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { createElement } from "react";
import { parseMarkdown } from "../src/lib/markdown";

// Renders parseMarkdown's output into a container the same way a real
// consumer (MarkdownField) would, so assertions read the actual DOM rather
// than poking at React elements directly.
function renderMarkdown(raw: string | null | undefined) {
  return render(createElement("div", null, parseMarkdown(raw)));
}

describe("parseMarkdown", () => {
  it("renders a heading as <h4>", () => {
    const { container } = renderMarkdown("# Title");
    const h4 = container.querySelector("h4");
    expect(h4).not.toBeNull();
    expect(h4?.textContent).toBe("Title");
  });

  it("collapses all heading levels 1-6 to <h4>", () => {
    const { container } = renderMarkdown("###### Small heading");
    expect(container.querySelectorAll("h4")).toHaveLength(1);
  });

  it("renders a run of - or * lines as one <ul><li>...", () => {
    const { container } = renderMarkdown("- one\n* two\n- three");
    const ul = container.querySelectorAll("ul");
    expect(ul).toHaveLength(1);
    const items = ul[0].querySelectorAll("li");
    expect(items).toHaveLength(3);
    expect(Array.from(items).map((li) => li.textContent)).toEqual(["one", "two", "three"]);
  });

  it("joins consecutive plain lines into one <p> with <br> between them", () => {
    const { container } = renderMarkdown("line one\nline two");
    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs).toHaveLength(1);
    expect(paragraphs[0].querySelectorAll("br")).toHaveLength(1);
    expect(paragraphs[0].textContent).toBe("line oneline two");
  });

  it("skips blank lines", () => {
    const { container } = renderMarkdown("first\n\n\nsecond para");
    expect(container.querySelectorAll("p")).toHaveLength(2);
  });

  it("renders empty input as a single (empty) placeholder", () => {
    const { container } = renderMarkdown("");
    const p = container.querySelector("p.markdown-empty");
    expect(p).not.toBeNull();
    expect(p?.textContent).toBe("(empty)");
  });

  it("treats null/undefined the same as empty input", () => {
    const { container } = renderMarkdown(undefined);
    expect(container.querySelector("p.markdown-empty")).not.toBeNull();
  });

  it("treats whitespace-only input as empty", () => {
    const { container } = renderMarkdown("   \n\t\n  ");
    expect(container.querySelector("p.markdown-empty")).not.toBeNull();
  });

  it("renders **bold** as <strong>", () => {
    const { container } = renderMarkdown("this is **bold** text");
    const strong = container.querySelector("strong");
    expect(strong?.textContent).toBe("bold");
    expect(container.querySelector("p")?.textContent).toBe("this is bold text");
  });

  it("renders `code` as <code>", () => {
    const { container } = renderMarkdown("run `npm test` now");
    const code = container.querySelector("code");
    expect(code?.textContent).toBe("npm test");
  });

  it("renders an http(s) link as a real anchor with safe attributes", () => {
    const { container } = renderMarkdown("[Docs](https://example.com/x)");
    const a = container.querySelector("a");
    expect(a).not.toBeNull();
    expect(a?.getAttribute("href")).toBe("https://example.com/x");
    expect(a?.getAttribute("target")).toBe("_blank");
    expect(a?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(a?.textContent).toBe("Docs");
  });

  it("allows http (not just https) links", () => {
    const { container } = renderMarkdown("[Site](http://example.com)");
    expect(container.querySelector("a")).not.toBeNull();
  });

  it("does NOT linkify a non-http(s) scheme -- the safety guard", () => {
    const { container } = renderMarkdown("[click me](javascript:alert(1))");
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("p")?.textContent).toBe("[click me](javascript:alert(1))");
  });

  it("does NOT linkify a relative or scheme-less path", () => {
    const { container } = renderMarkdown("[home](/dashboard)");
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("p")?.textContent).toBe("[home](/dashboard)");
  });

  it("renders a mixed document of headings, lists, and paragraphs with inline tokens", () => {
    const raw = [
      "# Heading",
      "",
      "Some **bold** and `code` and a [link](https://example.com).",
      "",
      "- item one",
      "- item two",
      "",
      "Trailing line one",
      "Trailing line two",
    ].join("\n");
    const { container } = renderMarkdown(raw);

    expect(container.querySelectorAll("h4")).toHaveLength(1);
    expect(container.querySelectorAll("ul")).toHaveLength(1);
    expect(container.querySelectorAll("ul li")).toHaveLength(2);
    expect(container.querySelectorAll("p")).toHaveLength(2);
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelector("code")?.textContent).toBe("code");
    expect(container.querySelector("a")?.getAttribute("href")).toBe("https://example.com");
    expect(container.querySelectorAll("p")[1].querySelectorAll("br")).toHaveLength(1);
  });
});
