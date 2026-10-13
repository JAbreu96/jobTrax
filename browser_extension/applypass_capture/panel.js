import { findExportRecords, recordId } from "./detect.mjs";

// State lives in memory only, so it dies with DevTools. That is deliberate:
// chrome.storage would survive, but it would also serve a buffer with no
// indication of whether it is from tonight or from three weeks ago, and a stale
// import is expensive to undo once it reaches Turso. The mitigation is wording
// -- the count stays visible and the empty state says the buffer is temporary.

/** match_id -> record. Deduping this capture, NOT the tracker's contents. */
const records = new Map();
const rows = [];
let seen = 0;
let rejected = 0;
let unreadable = 0;
let selectedId = null;
let nextRowId = 1;

const el = (id) => document.getElementById(id);

chrome.devtools.network.onRequestFinished.addListener((request) => {
  const type = request._resourceType;
  if (type !== "xhr" && type !== "fetch") return;
  seen += 1;
  request.getContent((content) => {
    ingest(request, content);
    render();
  });
  render();
});

function ingest(request, content) {
  const url = request.request?.url ?? "";
  const status = request.response?.status ?? 0;
  const time = new Date().toLocaleTimeString();

  if (!content) {
    // getContent hands back an empty string with no error when Chrome has
    // dropped the retained body. Detection reads the body, so an unreadable
    // response can never be recognized -- under exports-only listing it would
    // vanish silently and take a whole page of records with it. That is the one
    // failure here that produces a wrong answer rather than an obvious one, so
    // it gets a visible row.
    unreadable += 1;
    rows.push({ id: nextRowId++, kind: "error", url, status, time });
    return;
  }

  let parsed;
  try {
    parsed = JSON.parse(content);
  } catch {
    rejected += 1;
    return;
  }

  const found = findExportRecords(parsed);
  if (!found) {
    rejected += 1;
    return;
  }

  let added = 0;
  for (const record of found) {
    const key = recordId(record) ?? JSON.stringify(record);
    if (!records.has(key)) {
      records.set(key, record);
      added += 1;
    }
  }

  rows.push({
    id: nextRowId++,
    kind: "export",
    url,
    status,
    time,
    total: found.length,
    added,
    body: JSON.stringify(found, null, 2),
  });
}

// ── rendering ────────────────────────────────────────────────────────────────

function render() {
  const n = records.size;
  el("count").textContent = `${n} record${n === 1 ? "" : "s"} captured`;

  const warn = el("unreadable");
  warn.hidden = unreadable === 0;
  warn.textContent = `${unreadable} response${unreadable === 1 ? "" : "s"} unreadable`;

  el("download").disabled = n === 0;
  el("copy").disabled = n === 0;
  el("clear").disabled = n === 0 && rows.length === 0;

  renderList();
  renderDetail();
}

function renderList() {
  const list = el("list");
  list.textContent = "";

  if (rows.length === 0) {
    list.append(emptyState());
    return;
  }

  for (const row of rows) {
    const node = document.createElement("div");
    node.className = "row" + (row.kind === "error" ? " error" : "");
    if (row.id === selectedId) node.classList.add("selected");

    const url = document.createElement("div");
    url.className = "url";
    url.textContent = row.url;
    url.title = row.url;

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent =
      row.kind === "error"
        ? `${row.time} · ${row.status} · body unavailable — re-fetch this page`
        : `${row.time} · ${row.status} · ${row.total} records · ` +
          `${row.added} new / ${row.total - row.added} already captured`;

    node.append(url, meta);
    if (row.kind === "export") {
      node.addEventListener("click", () => {
        selectedId = row.id;
        render();
      });
    }
    list.append(node);
  }
}

function emptyState() {
  const box = document.createElement("div");
  box.id = "empty";

  const first = document.createElement("p");
  if (seen === 0) {
    first.textContent =
      "No XHR or fetch responses seen yet. The panel only sees requests made " +
      "while it is listening — reload the ApplyPass page with this panel open.";
  } else {
    // "saw 47, matched 0" points at detection; "saw 0" points at the reload.
    first.textContent =
      `Saw ${seen} XHR/fetch response${seen === 1 ? "" : "s"}, matched 0. ` +
      `${rejected} were not ApplyPass exports. If you expected a match here, ` +
      `check the response shape in the Network tab.`;
  }

  const second = document.createElement("p");
  second.textContent =
    "Captured records are held in memory only — closing DevTools discards them. " +
    "Download after each run.";

  box.append(first, second);
  return box;
}

function renderDetail() {
  const row = rows.find((r) => r.id === selectedId && r.kind === "export");
  const filter = el("filter");
  filter.disabled = !row;
  if (!row) {
    el("body").textContent = "";
    return;
  }
  const needle = filter.value.trim().toLowerCase();
  const lines = row.body.split("\n");
  el("body").textContent = needle
    ? lines.filter((l) => l.toLowerCase().includes(needle)).join("\n")
    : row.body;
}

// ── actions ──────────────────────────────────────────────────────────────────

/** 2026-08-23T14-05-33 — matches the data/applied_inbox_archive/ convention. */
function timestamp() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
    `T${p(d.getHours())}-${p(d.getMinutes())}-${p(d.getSeconds())}`
  );
}

function payload() {
  return JSON.stringify([...records.values()], null, 2);
}

el("download").addEventListener("click", () => {
  const name = `applied_inbox_${timestamp()}.json`;
  const url = URL.createObjectURL(new Blob([payload()], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);

  // Show the exact filename: Chrome appends " (1)" to repeat downloads, so a
  // glob in the mv below can otherwise pick up a stale file.
  const saved = el("saved");
  saved.hidden = false;
  saved.textContent = `Wrote ${name} — mv ~/Downloads/${name} data/applied_inbox.json`;
});

el("copy").addEventListener("click", async () => {
  const button = el("copy");
  try {
    await navigator.clipboard.writeText(payload());
    button.textContent = "Copied";
  } catch {
    // Clipboard access can be refused when the panel is not focused; the
    // textarea route still works there.
    const ta = document.createElement("textarea");
    ta.value = payload();
    document.body.append(ta);
    ta.select();
    button.textContent = document.execCommand("copy") ? "Copied" : "Copy failed";
    ta.remove();
  }
  setTimeout(() => (button.textContent = "Copy JSON"), 1500);
});

el("clear").addEventListener("click", () => {
  records.clear();
  rows.length = 0;
  seen = rejected = unreadable = 0;
  selectedId = null;
  el("saved").hidden = true;
  el("filter").value = "";
  render();
});

el("filter").addEventListener("input", renderDetail);

render();
