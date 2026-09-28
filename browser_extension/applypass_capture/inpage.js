// ApplyPass capture without DevTools: inject this into the dashboard tab, and it
// pages through "Job Applied" by itself and downloads one merged export.
//
// The DevTools panel next to this file needs a human to open DevTools and click
// through every page. An agent driving Chrome can do neither, so this does the
// same job from inside the page: it wraps XMLHttpRequest and fetch to read each
// page as the app receives it, clicks "next" until every page has arrived, and
// hands back a file in the shape scripts/parse_applied_jobs.py already accepts.
// Like the panel, it never touches the database.
//
// Three things the first full run (2,782 records, 28 pages) taught, each handled
// below rather than rediscovered:
//   - "previous" and "next" are the same element with the same generated class,
//     so the next button is found by position: the arrow right of the page number.
//   - ApplyPass is a Bubble app, and Bubble ignores synthetic clicks while a
//     workflow is still running. A click that produces no page is retried, and
//     after that the run parks as "stuck" and asks for one real click.
//   - A background tab keeps running but slower, so waits are generous and the
//     run is resumable rather than restarted.
//
// Usage from the Claude-in-Chrome javascript tool (each call must finish in 45s,
// so start() returns immediately and status() is polled):
//
//   <contents of this file>                       // installs window.__applypassCapture
//   __applypassCapture.start()                    // runs in the background
//   __applypassCapture.status()                   // poll until state is "done"
//   __applypassCapture.download()                 // -> "applied_inbox_<stamp>.json"
//
// The pure helpers at the top are exported for node --test; everything that
// touches the DOM lives in the driver below them.

(function (root) {
  "use strict";

  const RECORD_KEY = "_api_c2_match_id";

  // --- pure helpers ---------------------------------------------------------

  /**
   * One page of the Job Applied list, read out of a parsed response body, or
   * null when the body is not one.
   *
   * Bubble flattens the API connector's response into dotted keys on a single
   * object -- `_api_c2_body.data` beside `_api_c2_body.page` -- so the page
   * numbers are siblings of the records, found by suffix. Finding the records
   * by their identifying field rather than by key is the same bet detect.mjs
   * makes, for the same reason: the envelope's name is not stable.
   */
  function readPage(body, maxDepth = 8) {
    if (maxDepth < 0 || body === null || typeof body !== "object") return null;
    if (!Array.isArray(body)) {
      for (const [key, value] of Object.entries(body)) {
        if (Array.isArray(value) && value.length && value.every(isRecord)) {
          const meta = (name) => {
            const k = Object.keys(body).find((x) => x === name || x.endsWith("." + name));
            return k === undefined ? null : Number(body[k]);
          };
          return {
            key,
            records: value,
            page: meta("page"),
            pageSize: meta("pageSize"),
            totalPages: meta("totalPages"),
            totalRecords: meta("totalRecords"),
          };
        }
      }
    }
    for (const value of Object.values(body)) {
      const found = readPage(value, maxDepth - 1);
      if (found) return found;
    }
    return null;
  }

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value) &&
      RECORD_KEY in value;
  }

  /**
   * Whether a page came from the Job Applied tab. Job Matches answers from the
   * same endpoint in the same shape, so the only tell is in the records: every
   * applied record is submitted, and a matches page is mostly not. The first
   * live run of this script had its tab click swallowed while the app was still
   * loading and captured Job Matches -- 17,000 records nobody applied to.
   */
  function isAppliedPage(records) {
    return records.every((r) => r._api_c2_application_submitted_bool === true);
  }

  /** Every captured page's records, deduped on match_id, in page order. */
  function mergePages(pages) {
    const byId = new Map();
    for (const n of Object.keys(pages).map(Number).sort((a, b) => a - b)) {
      for (const record of pages[n]) byId.set(record[RECORD_KEY], record);
    }
    return [...byId.values()];
  }

  /** Page numbers 1..totalPages that have not arrived. */
  function missingPages(pages, totalPages) {
    const out = [];
    for (let n = 1; n <= totalPages; n++) if (!pages[n]) out.push(n);
    return out;
  }

  /**
   * The "next" arrow, from plain rectangles: the nearest textless button to the
   * right of the page-number button, on the same row. `buttons` is
   * [{text, left, right, top, bottom, ref}], so it can be tested without a DOM.
   *
   * By position because it is the only thing that tells the arrows apart. On
   * page 1 there is one arrow; from page 2 on there are two with an identical
   * class, and picking by class sent the first run backwards from page 7.
   */
  function pickNext(buttons, pageButton) {
    const mid = (b) => (b.top + b.bottom) / 2;
    return buttons
      .filter((b) => b !== pageButton && !b.text && b.left >= pageButton.right - 2 &&
        Math.abs(mid(b) - mid(pageButton)) < 20)
      .sort((a, b) => a.left - b.left)[0] || null;
  }

  /** 2026-09-28T11-16-22 -- the data/applied_inbox_archive/ convention. */
  function timestamp(d = new Date()) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
      `T${p(d.getHours())}-${p(d.getMinutes())}-${p(d.getSeconds())}`;
  }

  const helpers = {
    readPage, isAppliedPage, mergePages, missingPages, pickNext, timestamp, RECORD_KEY,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = helpers;
    return;
  }

  // --- driver: everything below needs the live page -------------------------

  // Re-injecting must not wrap the network twice or drop pages already held.
  if (root.__applypassCapture) return;

  const PAGE_SIZE = 100;
  const PAGE_TIMEOUT_MS = 15000;
  // Page 1 comes after a page-size change, which Bubble queues behind whatever
  // it is still doing from the page load; the first live run needed more than 15s.
  const FIRST_PAGE_TIMEOUT_MS = 40000;
  const CLICKS_PER_PAGE = 3;

  const state = {
    pages: {},
    totalPages: null,
    totalRecords: null,
    wrongTab: 0,        // Job Matches pages seen and refused
    state: "idle",      // idle | running | stuck | done | error
    message: "",
    log: [],
  };

  function ingest(text) {
    let body;
    try {
      body = JSON.parse(text);
    } catch {
      return;
    }
    const found = readPage(body);
    if (!found || !found.page) return;
    // Only 100-per-page responses count. Getting page 1 can mean flipping the
    // size through 50, and that response can land after the 100 one -- stored,
    // it would overwrite page 1 with half a page.
    if (found.pageSize && found.pageSize !== PAGE_SIZE) return;
    if (!isAppliedPage(found.records)) {
      state.wrongTab += 1;
      return;
    }
    state.pages[found.page] = found.records;
    if (found.totalPages) state.totalPages = found.totalPages;
    if (found.totalRecords) state.totalRecords = found.totalRecords;
  }

  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener("load", () => {
      if (typeof this.responseText === "string" && this.responseText.includes(RECORD_KEY)) {
        ingest(this.responseText);
      }
    });
    return origSend.apply(this, args);
  };
  const origFetch = root.fetch;
  root.fetch = async function (...args) {
    const resp = await origFetch.apply(this, args);
    resp.clone().text().then((t) => { if (t.includes(RECORD_KEY)) ingest(t); }).catch(() => {});
    return resp;
  };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function rect(el) {
    const r = el.getBoundingClientRect();
    return { text: el.textContent.trim(), left: r.left, right: r.right, top: r.top,
             bottom: r.bottom, ref: el };
  }

  function pageSizeSelect() {
    return [...document.querySelectorAll("select")]
      .find((s) => sizeOption(s, "100")) || null;
  }

  // Bubble renders the dropdown's placeholder as a real <option>, valued
  // PLACEHOLDER_<n> and labelled with the page size the app currently holds --
  // which it remembers between visits. So the selected label is the truth about
  // the current size, but the option to *choose* must be the real one: selecting
  // the placeholder fires nothing.
  function sizeOption(select, label) {
    return [...select.options].find((o) =>
      o.textContent.trim() === label && !o.value.includes("PLACEHOLDER")) || null;
  }

  /** The page-number button on the pager row, found beside the page-size select. */
  function pager() {
    const select = pageSizeSelect();
    if (!select) return null;
    const row = rect(select);
    const mid = (b) => (b.top + b.bottom) / 2;
    const buttons = [...document.querySelectorAll("button")].map(rect)
      .filter((b) => Math.abs(mid(b) - mid(row)) < 20 && b.right <= row.left);
    const pageButton = buttons.find((b) => /^\d+$/.test(b.text));
    if (!pageButton) return null;
    return { current: Number(pageButton.text), next: pickNext(buttons, pageButton) };
  }

  function click(el) {
    for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
      el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: root }));
    }
  }

  function setPageSize(label) {
    const select = pageSizeSelect();
    select.value = sizeOption(select, label).value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function waitFor(pageNo, timeout = PAGE_TIMEOUT_MS) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      if (state.pages[pageNo]) return true;
      await sleep(400);
    }
    return false;
  }

  async function run() {
    state.state = "running";
    state.message = "";

    if (!state.pages[1]) {
      // A size change reloads from page 1, which is the only way to get page 1's
      // response without navigating. Already on 100, flip through 50 so the
      // change still fires.
      const select = pageSizeSelect();
      if (!select) return fail("no page-size select -- is the Job Applied list showing?");
      const current = select.options[select.selectedIndex]?.textContent.trim();
      if (current === "100") {
        setPageSize("50");
        await sleep(3000);
      }
      setPageSize("100");
      if (!(await waitFor(1, FIRST_PAGE_TIMEOUT_MS))) {
        return fail(state.wrongTab
          ? "the list showing is Job Matches, not Job Applied: click the Job Applied " +
            "tab, wait for it to load, then call start() again"
          : "page 1 never arrived after selecting 100 per page");
      }
    }

    while (true) {
      const p = pager();
      if (!p) return fail("pager not found");
      const target = p.current + 1;
      if (state.totalPages && p.current >= state.totalPages) break;
      if (!p.next) return fail(`no next arrow on page ${p.current}`);

      let arrived = false;
      for (let attempt = 1; attempt <= CLICKS_PER_PAGE && !arrived; attempt++) {
        // Click again only if the last click did not move the pager. A slow page
        // is not an ignored click: re-clicking it advanced the first live run two
        // pages at once, and a page jumped over that way never gets requested.
        const now = pager();
        if (!now || now.current < target) click(p.next.ref);
        arrived = await waitFor(target);
      }
      state.log.push(`page ${target}: ${arrived ? "ok" : "no response"}`);
      if (!arrived) {
        state.state = "stuck";
        state.message = `page ${target} did not load. The app ignores synthetic clicks while ` +
          `it is busy: click the next arrow once by hand, then call resume().`;
        return;
      }
    }

    const missing = missingPages(state.pages, state.totalPages || 0);
    if (missing.length) {
      return fail(`finished paging but pages ${missing.join(", ")} never arrived`);
    }
    state.state = "done";
  }

  function fail(message) {
    state.state = "error";
    state.message = message;
  }

  function start() {
    if (state.state === "running") return status();
    run().catch((e) => fail(String(e && e.stack || e)));
    return status();
  }

  function status() {
    const records = mergePages(state.pages);
    const got = Object.keys(state.pages).map(Number);
    return {
      state: state.state,
      message: state.message,
      pages: got.length,
      totalPages: state.totalPages,
      records: records.length,
      totalRecords: state.totalRecords,
      missing: state.totalPages ? missingPages(state.pages, state.totalPages) : [],
      wrongTabPagesRefused: state.wrongTab,
      lastLog: state.log.slice(-3),
    };
  }

  function download() {
    const records = mergePages(state.pages);
    const name = `applied_inbox_${timestamp()}.json`;
    const url = URL.createObjectURL(new Blob([JSON.stringify(records)],
                                             { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    return { file: name, records: records.length };
  }

  root.__applypassCapture = { start, resume: start, status, download, helpers };
})(typeof window !== "undefined" ? window : globalThis);
