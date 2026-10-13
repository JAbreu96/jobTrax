// ApplyPass capture without DevTools: inject this into the signed-in dashboard
// tab, and it reads the Application column straight from the API the column
// itself calls, then downloads one merged export.
//
// ApplyPass moved from Bubble to a Next.js app in October 2026. The Bubble
// version of this file drove the pager by hand -- a page-size select, a next
// arrow, synthetic clicks the app often ignored -- because Bubble's data only
// ever arrived as a side effect of the UI. The new board is an infinite-scroll
// Kanban, and its Application column is one plain GET:
//
//   /api/jobListingMatches?current_stage_type_key=job_applied&page=N&pageSize=20&...
//
// authenticated by the session cookie. Asking for it from inside the tab, sorted
// by submission date at 500 a page, needs no scrolling and no clicks: a full
// capture is ~8 requests, an incremental one ~2, and the whole run fits in one
// javascript-tool call. Like the panel, it only reads; it never touches the
// database.
//
// Usage from the Claude-in-Chrome javascript tool:
//
//   <contents of this file>                                    // installs window.__applypassCapture
//   await __applypassCapture.run({stopBefore: "2026-09-29"})   // -> status(); omit for a full run
//   __applypassCapture.download()                              // -> {file, records}
//
// The helpers at the top, `capture` included, are exported for node --test;
// only the fetch and the download below them need the live page.

(function (root) {
  "use strict";

  const RECORD_KEY = "match_id";
  const APPLIED_STAGE = "job_applied";
  const PAGE_SIZE = 500;
  // The importer never reads the description, and it is ~5KB of a ~7.5KB record.
  // Dropped here so the download, the inbox file and every archived copy stay small.
  const DESCRIPTION_FIELDS = ["job_description", "job_description_raw_html",
                              "job_description_truncated"];

  // --- helpers --------------------------------------------------------------

  /**
   * One page of the Application column, newest submission first. The column
   * itself asks for 20 at a time sorted by match score; the date sort is what
   * lets an incremental capture stop early, and the endpoint takes 500 a page.
   */
  function pageUrl(origin, jspId, page, pageSize = PAGE_SIZE) {
    const url = new URL("/api/jobListingMatches", origin);
    const params = {
      jsp_id: jspId,
      jobDetails: "true",
      includeCurrentStage: "true",
      current_stage_type_key: APPLIED_STAGE,
      page,
      pageSize,
      sortFirstByMatchScoreDesc: "false",
      sortBy: "application_submitted_date",
      sortOrder: "desc",
    };
    for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v));
    return url.toString();
  }

  /**
   * Whether every record on a page belongs in the Application column. Job
   * Matches answers from the same endpoint in the same shape, and the first
   * Bubble-era run captured 17,000 of those by mistake.
   */
  function isAppliedPage(records) {
    return records.every((r) => r.current_stage_type_key === APPLIED_STAGE &&
      r.application_submitted_bool === true);
  }

  /**
   * Whether a page reaches back past the cutoff, so paging can stop after it.
   * Pages arrive newest submission first, so once a page holds a record
   * submitted before `stopBefore` every later page is older still -- and already
   * in the tracker. `stopBefore` comes from `parse_applied_jobs.py --cutoff`.
   */
  function reachedCutoff(records, stopBefore) {
    if (!stopBefore) return false;
    return records.some((r) => {
      const submitted = String(r.application_submitted_date || "").slice(0, 10);
      return submitted !== "" && submitted < stopBefore;
    });
  }

  /** A record without its description fields. */
  function slim(record) {
    const out = { ...record };
    for (const field of DESCRIPTION_FIELDS) delete out[field];
    return out;
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

  /** 2026-09-28T11-16-22 -- the data/applied_inbox_archive/ convention. */
  function timestamp(d = new Date()) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
      `T${p(d.getHours())}-${p(d.getMinutes())}-${p(d.getSeconds())}`;
  }

  /**
   * Page through the Application column. `getJson(url)` does the fetching, so
   * node tests can hand in a fake ApplyPass. `onPage` sees the result after
   * every page, for a caller that wants progress.
   */
  async function capture(getJson, origin, { stopBefore = "", pageSize = PAGE_SIZE,
                                            onPage = () => {} } = {}) {
    const me = await getJson(new URL("/api/me", origin).toString());
    if (!me || me.jsp_id === undefined || me.jsp_id === null) {
      throw new Error("/api/me returned no jsp_id");
    }
    const read = async (page) => {
      const body = await getJson(pageUrl(origin, me.jsp_id, page, pageSize));
      if (!body || !Array.isArray(body.data)) throw new Error(`page ${page} has no data array`);
      if (!isAppliedPage(body.data)) {
        throw new Error(`page ${page} holds records from outside the Application column`);
      }
      return body;
    };

    const result = { pages: {}, totalPages: null, totalRecords: null, stoppedAt: null, log: [] };
    let firstTotal = null;
    for (let page = 1; ; page++) {
      const body = await read(page);
      result.pages[page] = body.data.map(slim);
      result.totalPages = body.totalPages;
      result.totalRecords = body.totalRecords;
      if (page === 1) firstTotal = body.totalRecords;
      result.log.push(`page ${page}: ${body.data.length} records`);
      onPage(result);
      if (reachedCutoff(body.data, stopBefore)) {
        result.stoppedAt = page;
        break;
      }
      // A missing totalPages or an empty page ends the run rather than paging forever.
      if (!body.totalPages || !body.data.length || page >= body.totalPages) break;
    }

    // The service keeps applying while this runs, and every new application lands
    // on page 1 -- already read. Later pages only shift down, which repeats a
    // record rather than skipping one; the repeats dedupe on match_id. So re-read
    // page 1 once, kept as page 0 beside the first copy.
    const grew = (result.totalRecords || 0) - (firstTotal || 0);
    if (grew > 0) {
      result.pages[0] = (await read(1)).data.map(slim);
      result.log.push(`page 1 re-read: ${grew} submitted during the run`);
    }
    return result;
  }

  const helpers = {
    pageUrl, isAppliedPage, reachedCutoff, slim, mergePages, missingPages, timestamp, capture,
    RECORD_KEY, PAGE_SIZE,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = helpers;
    return;
  }

  // --- driver: everything below needs the live page -------------------------

  // No guard against re-injecting: nothing on the page is wrapped any more, so
  // injecting a newer copy simply replaces the old one.

  const state = {
    pages: {},
    totalPages: null,
    totalRecords: null,
    stopBefore: "",     // incremental cutoff; "" pages everything
    stoppedAt: null,    // the page that reached the cutoff
    state: "idle",      // idle | running | done | error
    message: "",
    log: [],
  };

  // Error messages name the path only: the query carries the account id, and
  // the javascript tool withholds any output that looks like a query string.
  async function getJson(url) {
    const resp = await root.fetch(url, { credentials: "include",
                                         headers: { accept: "application/json" } });
    if (resp.status === 401 || resp.status === 403) {
      throw new Error("signed out of ApplyPass: sign in, then run again");
    }
    if (!resp.ok) throw new Error(`${new URL(url).pathname} answered HTTP ${resp.status}`);
    return resp.json();
  }

  async function run(options = {}) {
    if (state.state === "running") return status();
    Object.assign(state, {
      pages: {}, totalPages: null, totalRecords: null, stoppedAt: null, log: [],
      stopBefore: options.stopBefore || "", state: "running", message: "",
    });
    try {
      const result = await capture(getJson, root.location.origin, {
        stopBefore: state.stopBefore,
        pageSize: options.pageSize || PAGE_SIZE,
        onPage: (partial) => Object.assign(state, partial),
      });
      Object.assign(state, result, { state: "done" });
    } catch (e) {
      state.state = "error";
      state.message = String((e && e.message) || e);
    }
    return status();
  }

  function status() {
    const records = mergePages(state.pages);
    const got = Object.keys(state.pages).map(Number).filter((n) => n >= 1);
    return {
      state: state.state,
      message: state.message,
      pages: got.length,
      totalPages: state.totalPages,
      records: records.length,
      totalRecords: state.totalRecords,
      missing: state.totalPages
        ? missingPages(state.pages, state.stoppedAt || state.totalPages) : [],
      stopBefore: state.stopBefore,
      stoppedAt: state.stoppedAt,
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

  root.__applypassCapture = { run, status, download, helpers };
})(typeof window !== "undefined" ? window : globalThis);
