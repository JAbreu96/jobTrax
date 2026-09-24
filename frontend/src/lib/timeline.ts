/*
 * The right rail's status timeline, as a pure function of a job and its rounds.
 *
 * Kept out of the component on purpose: nearly every rule below is a trap that
 * only shows up on particular rows, and the rows that trigger them are rare
 * enough that a rendering test would not reliably meet them. They are asserted
 * directly instead -- see tests/timeline.test.ts.
 *
 * Mirrors STATUS_ORDER in src/jobs_db.py (:89-92). That list is the source of
 * truth; this file must not invent an ordering of its own.
 */
import type { Interview, InterviewType, JobStatus } from "../api/types";

/*
 * The spine. Deliberately NOT the whole of STATUS_ORDER: "Rejected" and
 * "Accepted" are outcomes, not positions on the path, and rendering them as
 * nodes is the single most likely defect here. "Rejected" sits at index 9 in
 * STATUS_ORDER -- above "Offer" at 7 -- so any `rank(status) >= rank(node)`
 * test marks every rejected job as having reached Offer. jobs_db's
 * APPLIED_STATUSES already excludes Rejected for the same reason, with a
 * comment explaining that a cold outreach can be turned down by a company that
 * was never applied to.
 *
 * "" (rank 0) is likewise absent: it means no status has been set, which is a
 * position before the path rather than on it.
 */
export const PATH: JobStatus[] = [
  "Tracking",
  "Applied",
  "Phone Screen",
  "Technical",
  "System Design",
  "Behavioral",
  "Offer",
];

export const TERMINAL: JobStatus[] = ["Rejected", "Accepted"];

/*
 * Which node a recorded round is evidence for.
 *
 * `recruiter_screen` maps to "Phone Screen" because the tracker has no
 * separate node for it and it is, in practice, the first conversation -- on
 * the live data it is also the single most common round type, so dropping it
 * would blank the rail on the majority of jobs that ever interviewed.
 * `take_home`, `pair_programming` and `other` map to nothing: they happen at
 * varying points and asserting a position from them would be a guess. They
 * still appear in the Prep tab's round list; they just do not move the rail.
 */
const ROUND_NODE: Partial<Record<InterviewType, JobStatus>> = {
  recruiter_screen: "Phone Screen",
  phone_screen: "Phone Screen",
  technical: "Technical",
  system_design: "System Design",
  behavioral: "Behavioral",
  final_round: "Behavioral",
};

export interface TimelineJob {
  status?: string | null;
  date_added?: string | null;
  date_applied?: string | null;
}

export interface TimelineNode {
  status: JobStatus;
  /** Raw, never parsed -- these columns predate validation and hold prose. */
  date: string;
  reached: boolean;
  /** The furthest reached node: where "you are here" points. */
  current: boolean;
  /** Rounds recorded against this node, earliest first. */
  rounds: Interview[];
}

export interface Timeline {
  nodes: TimelineNode[];
  /** Path statuses past the last rendered node, for the muted "then ..." tail. */
  upcoming: JobStatus[];
  /** "Rejected" / "Accepted" -- an end-cap badge, never a node. */
  terminal: JobStatus | null;
  /** True when the job has a status but nothing places it on the path. */
  unplaceable: boolean;
}

function earliest(rounds: Interview[]): string {
  const dates = rounds
    .map((r) => (r.scheduled_date || "").trim())
    .filter(Boolean)
    .sort();
  return dates[0] || "";
}

/**
 * Build the rail.
 *
 * Renders what actually happened, the immediate next step, and nothing else --
 * four of the seven path statuses (System Design, Behavioral, Offer, Accepted)
 * have zero rows across the whole tracker, so rendering all of them puts five
 * hollow circles under one filled one on the ~740 jobs sitting at Applied.
 * The remainder becomes a one-line `upcoming` tail.
 */
export function timelineNodes(job: TimelineJob, rounds: Interview[] = []): Timeline {
  const status = (job.status || "").trim() as JobStatus;
  const terminal = TERMINAL.includes(status) ? status : null;

  const byNode = new Map<JobStatus, Interview[]>();
  for (const round of rounds) {
    const node = ROUND_NODE[round.interview_type];
    if (node) byNode.set(node, [...(byNode.get(node) || []), round]);
  }

  /*
   * How far along the path this job is, as an index into PATH.
   *
   * A status on the path answers it directly. Otherwise the answer has to come
   * from evidence, and the two cases that need it are the interesting ones:
   *
   *   - Rejected. The status says the outcome, not how far it got. Reading a
   *     position out of it would put every rejected job at Offer.
   *   - A status outside STATUS_ORDER entirely. PR 0 migrated the 51 such rows
   *     that existed, but status_rank() still returns -1 for anything new, and
   *     a rail that silently renders nothing reached is how that would go
   *     unnoticed a second time.
   *
   * Accepted is the exception: you cannot accept without an offer, so it
   * implies the end of the path.
   */
  let reachedIndex = PATH.indexOf(status);
  const placeable = reachedIndex >= 0;
  if (status === "Accepted") {
    reachedIndex = PATH.indexOf("Offer");
  } else if (!placeable) {
    reachedIndex = -1;
    for (const [node] of byNode) {
      reachedIndex = Math.max(reachedIndex, PATH.indexOf(node));
    }
    if ((job.date_applied || "").trim()) {
      reachedIndex = Math.max(reachedIndex, PATH.indexOf("Applied"));
    }
    // date_added is part of the primary key, so a row always has one and
    // "Tracking" is always at least true.
    reachedIndex = Math.max(reachedIndex, PATH.indexOf("Tracking"));
  }

  // One past the furthest reached: the single next step stays visible so the
  // rail still says what comes next, which is half of tracking readiness.
  const lastRendered = Math.min(reachedIndex + 1, PATH.length - 1);

  const nodes: TimelineNode[] = PATH.slice(0, lastRendered + 1).map((node, i) => {
    const nodeRounds = (byNode.get(node) || [])
      .slice()
      .sort((a, b) => (a.scheduled_date || "").localeCompare(b.scheduled_date || ""));
    let date = "";
    if (node === "Tracking") date = (job.date_added || "").trim();
    else if (node === "Applied") date = (job.date_applied || "").trim();
    else date = earliest(nodeRounds);
    return {
      status: node,
      date,
      reached: i <= reachedIndex,
      current: i === reachedIndex,
      rounds: nodeRounds,
    };
  });

  return {
    nodes,
    upcoming: PATH.slice(lastRendered + 1),
    terminal,
    unplaceable: status !== "" && !placeable && !TERMINAL.includes(status),
  };
}
