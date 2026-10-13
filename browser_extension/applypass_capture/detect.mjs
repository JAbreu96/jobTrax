// Recognizing an ApplyPass export, without knowing what the response looks like.
//
// The obvious check -- "is the body an array of records?" -- is wrong here.
// scripts/parse_applied_jobs.py:273-274 unwraps `data`, `results` *and* `matches`
// before parsing, and nobody writes three fallbacks speculatively. That is scar
// tissue from real payloads, and it says the records arrive wrapped in an
// envelope whose name is not stable.
//
// So we key on the records themselves rather than on their container: walk the
// parsed body and return the first array whose elements carry a match id.
// Envelope name and nesting depth stop mattering, and no domain or API path has
// to be hardcoded. The Bubble app sent `_api_c2_match_id`; the Next.js app that
// replaced it in October 2026 sends a bare `match_id`. Both are accepted, so the
// panel reads either app and an archived export still parses.
//
// This module deliberately touches no Chrome APIs so it stays runnable under
// `node --test`. It is the one piece of this extension whose failure is silent
// -- a wrong walk yields an empty panel and no stack trace -- so it is the one
// piece that gets tests.

export const RECORD_KEYS = ["match_id", "_api_c2_match_id"];

/** A plain object carrying the export's identifying field. */
function isRecord(value) {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    RECORD_KEYS.some((key) => key in value)
  );
}

/** A record's match id, under whichever key its app used. */
export function recordId(record) {
  for (const key of RECORD_KEYS) if (key in record) return record[key];
  return undefined;
}

function walk(node, depth) {
  if (depth < 0 || node === null || typeof node !== "object") return null;

  if (Array.isArray(node)) {
    // Filter rather than require every element to match: a page that carries a
    // trailing summary object alongside its records should still be captured.
    const records = node.filter(isRecord);
    if (records.length) return records;
    for (const item of node) {
      const found = walk(item, depth - 1);
      if (found) return found;
    }
    return null;
  }

  for (const value of Object.values(node)) {
    const found = walk(value, depth - 1);
    if (found) return found;
  }
  return null;
}

/**
 * Find the export records anywhere in a parsed response body.
 * Returns an array of records, or null if this body is not an export.
 *
 * @param {unknown} body   parsed JSON
 * @param {number} maxDepth  guard against pathological nesting
 */
export function findExportRecords(body, maxDepth = 8) {
  // A single-record response (the parser's own `or [data]` fallback case) is
  // not an array and would otherwise fall through the walk entirely.
  if (isRecord(body)) return [body];
  return walk(body, maxDepth);
}
