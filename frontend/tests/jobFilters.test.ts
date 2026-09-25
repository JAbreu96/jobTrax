/*
 * The filter semantics.
 *
 * These are worth testing exhaustively because their failure mode is silent.
 * A filter that is slightly too generous shows a few extra rows and nobody
 * notices until a number on Insights disagrees with the list it links to --
 * which is the bug class the funnel deeplink exists to make visible.
 */
import { describe, it, expect } from "vitest";
import {
  filterJobs, matchesFunnel, isAutoApplied, funnelFromSearch, wantsArchived,
  searchFromQuery, funnelBannerText, searchBannerText, BLANK,
} from "../src/lib/jobFilters";
import { rowKey } from "../src/lib/jobFields";
import type { Job } from "../src/api/types";

function job(overrides: Partial<Job> = {}): Job {
  return {
    company: "Acme", date_added: "2026-05-10", position_title: "Engineer",
    link: "", location: "New York, NY", contacts: "", notes: "",
    outreach_date: "", date_applied: "", status: "Tracking", followup_log: "",
    recruiter_id: null, recruiter_name: null, recruiter_agency: null,
    recruiter_from_triage: false,
    ...overrides,
  };
}

const names = (jobs: Job[]) => jobs.map((j) => j.company);

describe("search", () => {
  it("matches the company", () => {
    const jobs = [job({ company: "Stripe" }), job({ company: "Globex" })];
    expect(names(filterJobs(jobs, { q: "stri" }))).toEqual(["Stripe"]);
  });

  it("matches notes, which are not a visible column", () => {
    // Searching notes is why /api/jobs carries them at all -- it is where
    // "applypass", recruiter names and context end up.
    const jobs = [job({ company: "Stripe", notes: "referred by Dana" }), job()];
    expect(names(filterJobs(jobs, { q: "dana" }))).toEqual(["Stripe"]);
  });

  it("matches the title and the location too", () => {
    const jobs = [
      job({ company: "A", position_title: "Forward Deployed Engineer" }),
      job({ company: "B", location: "Lisbon" }),
      job({ company: "C" }),
    ];
    expect(names(filterJobs(jobs, { q: "deployed" }))).toEqual(["A"]);
    expect(names(filterJobs(jobs, { q: "lisbon" }))).toEqual(["B"]);
  });

  it("ignores case and surrounding space", () => {
    const jobs = [job({ company: "Stripe" })];
    expect(filterJobs(jobs, { q: "  STRIPE " })).toHaveLength(1);
  });

  it("returns everything for an empty query", () => {
    const jobs = [job(), job({ company: "B" })];
    expect(filterJobs(jobs, { q: "   " })).toHaveLength(2);
  });
});

describe("status filter", () => {
  it("matches one status exactly", () => {
    const jobs = [job({ status: "Applied" }), job({ company: "B", status: "Tracking" })];
    expect(names(filterJobs(jobs, { status: "Applied" }))).toEqual(["Acme"]);
  });

  it("__blank__ finds rows with no status at all", () => {
    const jobs = [job({ status: "" }), job({ company: "B", status: "Applied" })];
    expect(names(filterJobs(jobs, { status: BLANK }))).toEqual(["Acme"]);
  });

  it("__blank__ treats whitespace as blank", () => {
    expect(filterJobs([job({ status: "   " })], { status: BLANK })).toHaveLength(1);
  });
});

describe("recruiter filter", () => {
  it("matches one recruiter by id", () => {
    const jobs = [job({ recruiter_id: 7 }), job({ company: "B", recruiter_id: 9 })];
    expect(names(filterJobs(jobs, { recruiterId: "7" }))).toEqual(["Acme"]);
  });

  it("__blank__ finds rows with no recruiter", () => {
    const jobs = [job({ recruiter_id: null }), job({ company: "B", recruiter_id: 9 })];
    expect(names(filterJobs(jobs, { recruiterId: BLANK }))).toEqual(["Acme"]);
  });
});

describe("date range", () => {
  it("excludes rows before the start", () => {
    const jobs = [job({ date_added: "2026-05-10" }),
                  job({ company: "B", date_added: "2026-01-01" })];
    expect(names(filterJobs(jobs, { dateFrom: "2026-03-01" }))).toEqual(["Acme"]);
  });

  it("excludes rows after the end", () => {
    const jobs = [job({ date_added: "2026-05-10" }),
                  job({ company: "B", date_added: "2026-09-01" })];
    expect(names(filterJobs(jobs, { dateTo: "2026-06-01" }))).toEqual(["Acme"]);
  });

  it("includes both endpoints", () => {
    const jobs = [job({ date_added: "2026-05-10" })];
    expect(filterJobs(jobs, { dateFrom: "2026-05-10", dateTo: "2026-05-10" }))
      .toHaveLength(1);
  });

  it("drops an undated row from a bounded range", () => {
    // "Added since the 1st" should not include a row nobody dated.
    expect(filterJobs([job({ date_added: "" })], { dateFrom: "2026-01-01" }))
      .toHaveLength(0);
  });

  it("keeps an undated row when no range is set", () => {
    expect(filterJobs([job({ date_added: "" })], {})).toHaveLength(1);
  });
});

describe("the funnel deeplink", () => {
  it("applied means dated, not status Applied", () => {
    // The funnel counts date_applied. A row advanced straight to Phone Screen
    // by triage has a date and belongs in the count; one merely labelled
    // Applied with no date does not.
    const dated = job({ status: "Phone Screen", date_applied: "2026-05-01" });
    const labelled = job({ company: "B", status: "Applied", date_applied: "" });

    expect(names(filterJobs([dated, labelled], { funnel: { stage: "applied", source: "all" } })))
      .toEqual(["Acme"]);
  });

  it("outreached means an outreach date", () => {
    const jobs = [job({ outreach_date: "2026-04-02" }), job({ company: "B" })];
    expect(names(filterJobs(jobs, { funnel: { stage: "outreached", source: "all" } })))
      .toEqual(["Acme"]);
  });

  it("screen groups every interview stage", () => {
    const stages = ["Phone Screen", "Technical", "System Design", "Behavioral"];
    const jobs = stages.map((s, i) => job({ company: `C${i}`, status: s }))
      .concat(job({ company: "Out", status: "Applied" }));

    expect(filterJobs(jobs, { funnel: { stage: "screen", source: "all" } }))
      .toHaveLength(stages.length);
  });

  it("rejected matches the status case-insensitively", () => {
    expect(filterJobs([job({ status: "rejected" })],
                      { funnel: { stage: "rejected", source: "all" } })).toHaveLength(1);
  });

  it("interviewed lets everything through until its keys arrive", () => {
    // Otherwise the table shows "no results" for as long as the second fetch
    // takes, which reads as an empty filter rather than a loading one.
    const jobs = [job(), job({ company: "B" })];
    expect(filterJobs(jobs, {
      funnel: { stage: "interviewed", source: "all", interviewedKeys: null },
    })).toHaveLength(2);
  });

  it("interviewed narrows to the keys once they have", () => {
    const seen = job({ company: "Seen" });
    const jobs = [seen, job({ company: "Unseen" })];
    expect(names(filterJobs(jobs, {
      funnel: {
        stage: "interviewed", source: "all",
        interviewedKeys: new Set([rowKey(seen)]),
      },
    }))).toEqual(["Seen"]);
  });

  it("an empty key set is an answer, not a loading state", () => {
    expect(filterJobs([job()], {
      funnel: { stage: "interviewed", source: "all", interviewedKeys: new Set() },
    })).toHaveLength(0);
  });

  it("source=hand drops the ApplyPass rows", () => {
    const jobs = [job({ company: "Hand" }),
                  job({ company: "Auto", notes: "applypass auto-applied" })];
    expect(names(filterJobs(jobs, {
      funnel: { stage: "applied", source: "hand" },
    }).concat())).toEqual([]);   // neither has date_applied yet
    expect(names(filterJobs(
      jobs.map((j) => ({ ...j, date_applied: "2026-05-01" })),
      { funnel: { stage: "applied", source: "hand" } },
    ))).toEqual(["Hand"]);
  });

  it("source=auto keeps only them", () => {
    const jobs = [job({ company: "Hand", date_applied: "2026-05-01" }),
                  job({ company: "Auto", date_applied: "2026-05-01",
                        notes: "Auto-applied via ApplyPass" })];
    expect(names(filterJobs(jobs, { funnel: { stage: "applied", source: "auto" } })))
      .toEqual(["Auto"]);
  });

  it("recognises both spellings Insights counts", () => {
    expect(isAutoApplied(job({ notes: "ApplyPass submitted this" }))).toBe(true);
    expect(isAutoApplied(job({ notes: "auto-applied on 5/1" }))).toBe(true);
    expect(isAutoApplied(job({ notes: "applied by hand" }))).toBe(false);
  });

  it("an unknown stage filters nothing rather than everything", () => {
    // A link from a future Insights row must not empty the table.
    expect(matchesFunnel(job(), { stage: "somethingelse", source: "all" })).toBe(true);
  });
});

describe("reading the URL", () => {
  it("finds a stage link and defaults its source", () => {
    expect(funnelFromSearch("?stage=applied"))
      .toMatchObject({ stage: "applied", source: "all" });
  });

  it("keeps an explicit source", () => {
    expect(funnelFromSearch("?stage=applied&source=auto")?.source).toBe("auto");
  });

  it("is null with no stage", () => {
    expect(funnelFromSearch("?q=stripe")).toBeNull();
  });

  it("includes archived for a stage link, to match the funnel", () => {
    expect(wantsArchived("?stage=applied")).toBe(true);
  });

  it("includes archived when a ?q= link says so explicitly", () => {
    expect(wantsArchived("?q=stripe&include_archived=1")).toBe(true);
  });

  it("does not widen the population for a search the user typed", () => {
    expect(wantsArchived("?q=stripe")).toBe(false);
  });

  it("reads and trims the search term", () => {
    expect(searchFromQuery("?q=%20stripe%20")).toBe("stripe");
  });

  it("is empty with no q", () => {
    expect(searchFromQuery("?stage=applied")).toBe("");
  });
});

describe("banner wording", () => {
  it("names the stage and the source", () => {
    expect(funnelBannerText({ stage: "screen", source: "auto" }))
      .toBe("at an interview stage · auto-submitted (ApplyPass)");
  });

  it("falls back to the raw value for an unknown stage", () => {
    expect(funnelBannerText({ stage: "mystery", source: "all" }))
      .toBe("mystery · all sources");
  });

  it("says nothing when there is no funnel", () => {
    expect(funnelBannerText(null)).toBeNull();
  });

  it("quotes the current search term", () => {
    expect(searchBannerText("stripe")).toBe("Searching for “stripe”");
  });

  it("distinguishes no banner from an empty one", () => {
    expect(searchBannerText("   ")).toBeNull();
  });
});

describe("filters compose", () => {
  it("applies every filter at once", () => {
    const jobs = [
      job({ company: "Keep", status: "Applied", recruiter_id: 7,
            date_added: "2026-05-10", notes: "referred by Dana" }),
      job({ company: "WrongStatus", status: "Tracking", recruiter_id: 7,
            date_added: "2026-05-10", notes: "referred by Dana" }),
      job({ company: "WrongDate", status: "Applied", recruiter_id: 7,
            date_added: "2026-01-01", notes: "referred by Dana" }),
      job({ company: "NoMatch", status: "Applied", recruiter_id: 7,
            date_added: "2026-05-10", notes: "" }),
    ];

    expect(names(filterJobs(jobs, {
      q: "dana", status: "Applied", recruiterId: "7",
      dateFrom: "2026-03-01", dateTo: "2026-06-01",
    }))).toEqual(["Keep"]);
  });

  it("returns the input order, not a sorted one", () => {
    // Sorting is the table's job and happens after this.
    const jobs = [job({ company: "Zeta" }), job({ company: "Alpha" })];
    expect(names(filterJobs(jobs, {}))).toEqual(["Zeta", "Alpha"]);
  });
});
