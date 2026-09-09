/*
 * A deliberately tiny markdown subset, ported from src/static/job_fields.js's
 * `renderMarkdownInto` / `appendInlineMarkdown` (see that file's lines
 * ~126-190 as of the React rewrite's Phase 2).
 *
 * The original mutated a DOM container directly. This module is the same
 * grammar expressed as pure functions that return React nodes instead --
 * `parseMarkdown` never touches `document`, so it can be unit-tested without
 * jsdom and reused by any component that wants to render job notes.
 *
 * This is NOT a general markdown parser and should not grow into one. Do not
 * add a markdown library here -- the grammar is small on purpose:
 *
 *   - blank lines are skipped
 *   - `#{1,6} text` -> <h4> (all heading levels collapse to one size)
 *   - runs of `- text` / `* text` -> <ul><li>
 *   - anything else accumulates into a <p>, with <br> between consecutive
 *     lines of the same paragraph
 *   - empty input -> a single "(empty)" placeholder paragraph
 *
 * Inline, within any line: **bold**, `code`, and [text](url) links.
 */
import { createElement, type ReactNode } from "react";

const INLINE_TOKEN_RE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;

// Only http(s) hrefs become real anchors. This is a deliberate safety guard,
// carried over unchanged from job_fields.js's appendInlineMarkdown: the
// source text here is job data (notes a user typed, or pasted from a
// posting), not authored copy, so a `javascript:`, `data:`, or other
// non-http(s) scheme must never become a clickable link. Anything that
// doesn't match stays as literal text, brackets and all.
function parseInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let tokenIndex = 0;
  let match: RegExpExecArray | null;

  INLINE_TOKEN_RE.lastIndex = 0;
  while ((match = INLINE_TOKEN_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const token = match[0];
    const key = `${keyPrefix}-i${tokenIndex++}`;

    if (token.startsWith("**")) {
      nodes.push(createElement("strong", { key }, token.slice(2, -2)));
    } else if (token.startsWith("`")) {
      nodes.push(createElement("code", { key }, token.slice(1, -1)));
    } else {
      const linkMatch = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
      if (linkMatch && /^https?:\/\//i.test(linkMatch[2])) {
        nodes.push(
          createElement(
            "a",
            {
              key,
              href: linkMatch[2],
              target: "_blank",
              rel: "noopener noreferrer",
            },
            linkMatch[1],
          ),
        );
      } else {
        nodes.push(token);
      }
    }
    lastIndex = INLINE_TOKEN_RE.lastIndex;
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}

/**
 * Parses `raw` into an array of React block-level nodes (`<h4>`, `<ul>`,
 * `<p>`), ready to render as `{parseMarkdown(value)}`. Never returns an empty
 * array -- empty/whitespace-only input renders as a single placeholder
 * paragraph, matching the original's "(empty)" state.
 */
export function parseMarkdown(raw: string | null | undefined): ReactNode[] {
  const lines = (raw ?? "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let blockIndex = 0;

  const isBlank = (line: string) => /^\s*$/.test(line);
  const isHeading = (line: string) => /^#{1,6}\s+/.test(line);
  const isListItem = (line: string) => /^[-*]\s+/.test(line);

  while (i < lines.length) {
    const line = lines[i];

    if (isBlank(line)) {
      i++;
      continue;
    }

    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    if (heading) {
      const key = `b${blockIndex++}`;
      blocks.push(createElement("h4", { key }, parseInline(heading[1], key)));
      i++;
      continue;
    }

    if (isListItem(line)) {
      const key = `b${blockIndex++}`;
      const items: ReactNode[] = [];
      let itemIndex = 0;
      while (i < lines.length && isListItem(lines[i])) {
        const content = lines[i].replace(/^[-*]\s+/, "");
        const itemKey = `${key}-${itemIndex++}`;
        items.push(createElement("li", { key: itemKey }, parseInline(content, itemKey)));
        i++;
      }
      blocks.push(createElement("ul", { key }, items));
      continue;
    }

    const key = `b${blockIndex++}`;
    const paraNodes: ReactNode[] = [];
    let lineIndex = 0;
    let first = true;
    while (i < lines.length && !isBlank(lines[i]) && !isListItem(lines[i]) && !isHeading(lines[i])) {
      if (!first) {
        paraNodes.push(createElement("br", { key: `${key}-br${lineIndex}` }));
      }
      paraNodes.push(...parseInline(lines[i], `${key}-${lineIndex}`));
      first = false;
      lineIndex++;
      i++;
    }
    blocks.push(createElement("p", { key }, paraNodes));
  }

  if (blocks.length === 0) {
    blocks.push(createElement("p", { key: "empty", className: "markdown-empty" }, "(empty)"));
  }

  return blocks;
}
