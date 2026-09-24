/*
 * The status rail's logic, asserted directly rather than through a render.
 *
 * Every case here is a row shape that exists in the live tracker and that a
 * naive `rank(status) >= rank(node)` implementation gets wrong. The first
 * group is the important one: "Rejected" sits at index 9 in STATUS_ORDER,
 * above "Offer" at 7, so the obvious implementation reports that all 177
 * rejected jobs reached an offer.
 */
import { describe, it, expect } from "vitest";
import { timelineNodes, PATH } from "../src/lib/timeline";
import type { Interview, InterviewType } from "../src/api/types";

function round(interview_type: InterviewType, scheduled_date: string | null): Interview {
  return {
    company: "Acme", date_added: "2026-01-01", position_title: "Engineer", link: "",
    id: 1, interview_type, type_label: null, loop_id: null,
    scheduled_date, self_rating: null, notes: null,
  };
}

const node = (t: ReturnType<typeof timelineNodes>, status: string) =>
  t.nodes.find((n) => n.status === status);

// --- Rejected and Accepted are outcomes, not positions -----------------------

describe("terminal statuses", () => {
  it("does not report a rejected job as having reached Offer", () => {
    const t = timelineNodes({ status: "Rejected", date_added: "2026-01-01" });

    expect(node(t, "Offer")).toBeUndefined();
    expect(t.terminal).toBe("Rejected");
  });

  it("places a rejected job by its evidence, not by its status", () => {
    const t = timelineNodes(
      { status: "Rejected", date_added: "2026-01-01", date_applied: "2026-02-01" },
      [round("technical", "2026-03-01")],
    );

    // It got as far as Technical before being turned down.
    expect(node(t, "Technical")?.reached).toBe(true);
    expect(node(t, "Technical")?.current).toBe(true);
    expect(node(t, "System Design")?.reached).toBe(false);
  });

  it("does not invent an Applied date for a rejected cold outreach", () => {
    // APPLIED_STATUSES excludes Rejected precisely because a company can turn
    // down an approach that was never an application.
    const t = timelineNodes({ status: "Rejected", date_added: "2026-01-01" });

    expect(node(t, "Applied")?.reached).toBe(false);
    expect(node(t, "Tracking")?.reached).toBe(true);
  });

  it("treats Accepted as implying the offer it accepts", () => {
    const t = timelineNodes({ status: "Accepted", date_added: "2026-01-01" });

    expect(node(t, "Offer")?.reached).toBe(true);
    expect(t.terminal).toBe("Accepted");
  });

  it("renders neither terminal status as a node", () => {
    for (const status of ["Rejected", "Accepted"]) {
      const t = timelineNodes({ status, date_added: "2026-01-01" });
      expect(t.nodes.map((n) => n.status)).not.toContain(status);
    }
  });
});

// --- the typical row ---------------------------------------------------------

describe("shape", () => {
  it("shows the reached nodes plus exactly one step ahead", () => {
    // ~740 of 1314 rows look like this; it is the case to optimise.
    const t = timelineNodes({
      status: "Applied", date_added: "2026-01-01", date_applied: "2026-02-01",
    });

    expect(t.nodes.map((n) => n.status)).toEqual(["Tracking", "Applied", "Phone Screen"]);
    expect(node(t, "Applied")?.current).toBe(true);
    expect(node(t, "Phone Screen")?.reached).toBe(false);
  });

  it("puts the unrendered remainder in the tail", () => {
    const t = timelineNodes({ status: "Applied", date_added: "2026-01-01" });

    expect(t.upcoming).toEqual(["Technical", "System Design", "Behavioral", "Offer"]);
  });

  it("has no tail and no next step once the path is complete", () => {
    const t = timelineNodes({ status: "Offer", date_added: "2026-01-01" });

    expect(t.nodes).toHaveLength(PATH.length);
    expect(t.upcoming).toEqual([]);
    expect(node(t, "Offer")?.current).toBe(true);
  });
});

// --- dates -------------------------------------------------------------------

describe("dates", () => {
  it("passes a free-text date through untouched", () => {
    // outreach_date/date_applied predate validation and hold values like this;
    // parsing them would turn a readable rail into an error.
    const t = timelineNodes({
      status: "Applied", date_added: "2026-01-01", date_applied: "emailed Tuesday",
    });

    expect(node(t, "Applied")?.date).toBe("emailed Tuesday");
  });

  it("marks a node reached even when it has no date", () => {
    // Historical rows sit at an interview status with no interview row and no
    // date. The node is still reached; the UI renders "date unknown".
    const t = timelineNodes({ status: "Phone Screen", date_added: "2026-01-01" });

    expect(node(t, "Phone Screen")).toMatchObject({ reached: true, date: "" });
  });

  it("never invents a date for Offer", () => {
    // Nothing records when an offer arrived, and adding a column for it would
    // be reset by sync_jobs_to_sqlite, which writes only the 12 sheet columns.
    const t = timelineNodes({ status: "Offer", date_added: "2026-01-01" });

    expect(node(t, "Offer")?.date).toBe("");
    expect(node(t, "Offer")?.reached).toBe(true);
  });

  it("dates an interview node from its earliest round", () => {
    const t = timelineNodes(
      { status: "Technical", date_added: "2026-01-01" },
      [round("technical", "2026-05-02"), round("technical", "2026-04-01")],
    );

    expect(node(t, "Technical")?.date).toBe("2026-04-01");
    expect(node(t, "Technical")?.rounds.map((r) => r.scheduled_date))
      .toEqual(["2026-04-01", "2026-05-02"]);
  });
});

// --- rounds ------------------------------------------------------------------

describe("rounds", () => {
  it("counts a recruiter screen as the first conversation", () => {
    // The most common round type on the live data by a wide margin; dropping
    // it would blank the rail on most jobs that ever interviewed.
    const t = timelineNodes({ status: "Applied", date_added: "2026-01-01" },
                            [round("recruiter_screen", "2026-03-01")]);

    expect(node(t, "Phone Screen")?.rounds).toHaveLength(1);
  });

  it("does not let an unpositioned round type move the rail", () => {
    // A take-home can happen at any point; asserting a position from one
    // would be a guess.
    const t = timelineNodes({ status: "Applied", date_added: "2026-01-01" },
                            [round("take_home", "2026-03-01")]);

    expect(node(t, "Applied")?.current).toBe(true);
    expect(t.nodes.some((n) => n.rounds.length)).toBe(false);
  });

  it("tolerates a round with no date", () => {
    const t = timelineNodes({ status: "Technical", date_added: "2026-01-01" },
                            [round("technical", null)]);

    expect(node(t, "Technical")?.date).toBe("");
    expect(node(t, "Technical")?.rounds).toHaveLength(1);
  });
});

// --- statuses the vocabulary cannot place ------------------------------------

describe("unplaceable statuses", () => {
  it("falls back to evidence rather than rendering an empty rail", () => {
    // PR 0 migrated the 51 rows that were in this state, but status_rank()
    // still answers -1 for anything new, and a blank rail is how that would
    // go unnoticed a second time.
    const t = timelineNodes(
      { status: "Outreached", date_added: "2026-01-01", date_applied: "2026-02-01" },
    );

    expect(node(t, "Applied")?.reached).toBe(true);
    expect(t.unplaceable).toBe(true);
  });

  it("still reaches Tracking when there is no evidence at all", () => {
    const t = timelineNodes({ status: "Who knows", date_added: "2026-01-01" });

    expect(node(t, "Tracking")?.reached).toBe(true);
    expect(node(t, "Tracking")?.current).toBe(true);
  });

  it("does not flag an empty status as unplaceable", () => {
    // 55 rows have no status. That is "not started", not "unrecognised".
    const t = timelineNodes({ status: "", date_added: "2026-01-01" });

    expect(t.unplaceable).toBe(false);
    expect(node(t, "Tracking")?.reached).toBe(true);
  });
});
