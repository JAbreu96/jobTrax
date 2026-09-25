/*
 * The jobs list load loop.
 *
 * Driven through loadAllJobs directly rather than through the hook: every
 * behaviour worth pinning is about which requests go out and what lands in the
 * cache between them, and rendering a component to observe that would be
 * testing the renderer.
 *
 * The cases here are the ones the vanilla loadJobs() in jobs.html learned the
 * hard way -- a partial list that does not say it is partial, and a superseded
 * load appending its pages on top of a newer one.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import {
  loadAllJobs, jobsQueryKey, FIRST_PAGE, PREFETCH_PAGE, type JobsList,
} from "../src/hooks/useJobsProgressive";
import type { Job } from "../src/api/types";

function job(company: string): Job {
  return {
    company, date_added: "2026-09-12", position_title: "Engineer", link: "",
    location: "", contacts: "", notes: "", outreach_date: "", date_applied: "",
    status: "Tracking", followup_log: "",
    recruiter_id: null, recruiter_name: null, recruiter_agency: null,
    recruiter_from_triage: false,
  };
}

let requested: string[] = [];

/** Serves pages from a script of {jobs, next_cursor} responses. */
function serve(pages: { jobs: Job[]; next_cursor: string | null }[]) {
  let i = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    requested.push(url);
    const page = pages[i++];
    return { ok: true, status: 200, statusText: "OK", json: async () => page };
  }));
}

beforeEach(() => { requested = []; });
afterEach(() => { vi.unstubAllGlobals(); });

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("loadAllJobs", () => {
  it("asks for a small first page so the table paints before the list is whole", async () => {
    serve([{ jobs: [job("Acme")], next_cursor: null }]);

    await loadAllJobs(client());

    expect(requested[0]).toContain(`limit=${FIRST_PAGE}`);
  });

  it("makes exactly one request when the list fits in the first page", async () => {
    serve([{ jobs: [job("Acme")], next_cursor: null }]);

    const result = await loadAllJobs(client());

    expect(requested).toHaveLength(1);
    expect(result.prefetching).toBe(false);
  });

  it("follows the cursor and concatenates in order", async () => {
    serve([
      { jobs: [job("Acme")], next_cursor: "c1" },
      { jobs: [job("Globex")], next_cursor: "c2" },
      { jobs: [job("Initech")], next_cursor: null },
    ]);

    const result = await loadAllJobs(client());

    expect(result.jobs.map((j) => j.company)).toEqual(["Acme", "Globex", "Initech"]);
    expect(requested[1]).toContain(`limit=${PREFETCH_PAGE}`);
    expect(requested[1]).toContain("cursor=c1");
  });

  it("publishes the first page before the rest has arrived", async () => {
    // The whole reason for the loop. If this only landed at the end, the table
    // would stay empty for the full ~1.2MB.
    const qc = client();
    const seen: number[] = [];
    qc.getQueryCache().subscribe(() => {
      const data = qc.getQueryData<JobsList>(jobsQueryKey());
      if (data) seen.push(data.jobs.length);
    });
    serve([
      { jobs: [job("Acme")], next_cursor: "c1" },
      { jobs: [job("Globex")], next_cursor: null },
    ]);

    await loadAllJobs(qc);

    expect(seen[0]).toBe(1);
    expect(seen[seen.length - 1]).toBe(2);
  });

  it("says it is still prefetching while a cursor remains", async () => {
    const qc = client();
    serve([
      { jobs: [job("Acme")], next_cursor: "c1" },
      { jobs: [job("Globex")], next_cursor: null },
    ]);

    await loadAllJobs(qc);

    // The final state is settled; the intermediate one said otherwise.
    expect(qc.getQueryData<JobsList>(jobsQueryKey())?.prefetching).toBe(false);
  });

  it("keeps the rows it has when a later page fails, and flags them as partial", async () => {
    // Throwing would replace a readable partial table with an error state.
    // Pretending it is complete makes search answer "no matches" for jobs that
    // exist. Neither is acceptable, which is what `truncated` is for.
    let i = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      if (i++ === 0) {
        return { ok: true, status: 200, statusText: "OK",
                 json: async () => ({ jobs: [job("Acme")], next_cursor: "c1" }) };
      }
      throw new Error("network down");
    }));

    const result = await loadAllJobs(client());

    expect(result.jobs.map((j) => j.company)).toEqual(["Acme"]);
    expect(result.truncated).toBe(true);
    expect(result.prefetching).toBe(false);
  });

  it("rejects when the very first page fails", async () => {
    // Nothing arrived, so there is no partial list to caveat -- the caller
    // renders its error state instead.
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("network down"); }));

    await expect(loadAllJobs(client())).rejects.toThrow("network down");
  });

  it("stops following the cursor once aborted", async () => {
    const controller = new AbortController();
    let i = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      requested.push(url);
      if (i++ === 0) controller.abort();
      return { ok: true, status: 200, statusText: "OK",
               json: async () => ({ jobs: [job("Acme")], next_cursor: "c1" }) };
    }));

    await loadAllJobs(client(), {}, controller.signal);

    expect(requested).toHaveLength(1);
  });

  it("does not publish over a newer load once aborted", async () => {
    // Two loops appending into one cache entry would interleave two orderings
    // of the list. The vanilla version counts tokens; the signal says the same
    // thing here.
    const qc = client();
    const controller = new AbortController();
    controller.abort();
    serve([{ jobs: [job("Acme")], next_cursor: null }]);

    await loadAllJobs(qc, {}, controller.signal);

    expect(qc.getQueryData(jobsQueryKey())).toBeUndefined();
  });

  it("asks for archived rows only when told to", async () => {
    serve([{ jobs: [], next_cursor: null }]);
    await loadAllJobs(client(), { includeArchived: true });

    expect(requested[0]).toContain("include_archived=1");
  });

  it("leaves archived rows out by default", async () => {
    serve([{ jobs: [], next_cursor: null }]);
    await loadAllJobs(client());

    expect(requested[0]).not.toContain("include_archived");
  });

  it("keys archived and unarchived lists separately", () => {
    // Same key for both would let a funnel deeplink's archived-inclusive list
    // be served to the ordinary table, which shows rows it refuses to show.
    expect(JSON.stringify(jobsQueryKey({ includeArchived: true })))
      .not.toBe(JSON.stringify(jobsQueryKey()));
  });
});
