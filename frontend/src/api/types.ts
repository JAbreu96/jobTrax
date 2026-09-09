/**
 * Response shapes for src/jobs_gui.py's /api/* routes.
 *
 * These are derived from an actual dump of every endpoint's response against
 * a throwaway database (see the Phase 0 brief) -- not from reading the Python
 * in isolation, because nullability and shape details (e.g. /api/jobs's bare
 * array vs. {jobs, next_cursor}) are easy to get wrong from the source alone.
 * Every later phase's view code depends on these being right.
 */

// ---------------------------------------------------------------------------
// Shared vocabulary (src/jobs_db.py)
// ---------------------------------------------------------------------------

// STATUS_ORDER in src/jobs_db.py lines ~80-90. The first entry is the empty
// string -- an unset status, not "no such status" (that's status_rank() -1).
export type JobStatus =
  | ""
  | "Tracking"
  | "Applied"
  | "Phone Screen"
  | "Technical"
  | "System Design"
  | "Behavioral"
  | "Offer"
  | "Accepted"
  | "Rejected";

// INTERVIEW_TYPES in src/jobs_db.py lines ~854-864.
export type InterviewType =
  | "recruiter_screen"
  | "phone_screen"
  | "technical"
  | "behavioral"
  | "system_design"
  | "take_home"
  | "pair_programming"
  | "final_round"
  | "other";

// GET /api/config. Replaces the Jinja tojson injection jobs.html/kanban.html
// use today.
export interface AppConfig {
  status_values: JobStatus[];
  interview_types: InterviewType[];
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

// The four columns that identify a row (src/jobs_db.py KEY_COLUMNS). Widened
// twice as collisions surfaced -- see the comment on _migrate_key there.
export interface JobKey {
  company: string;
  date_added: string;
  position_title: string;
  link: string;
}

// A row as returned by /api/jobs (LIST_COLUMNS). job_summary is deliberately
// absent -- it's two thirds of the payload by bytes and never searched, so
// it's fetched per row on expand instead, via /api/jobs/detail.
export interface Job extends JobKey {
  location: string;
  contacts: string;
  notes: string;
  outreach_date: string;
  date_applied: string;
  status: string;
  followup_log: string;
  // Nullable: a job need not have a recruiter attached.
  recruiter_id: number | null;
  recruiter_name: string | null;
  recruiter_agency: string | null;
  // Whether the recruiter link came from a mail (inbox-triage), which is what
  // makes it read-only in the UI until the user overrides it.
  recruiter_from_triage: boolean;
}

// GET /api/jobs with no ?limit returns a bare Job[]. GET /api/jobs?limit=N
// returns this paged shape instead. Both shapes must be handled by callers.
export interface JobsPage {
  jobs: Job[];
  next_cursor: string | null;
}

// GET /api/jobs/detail. job_summary is present unless the caller passed
// ?summary=0 (the client already has it cached), so it's optional here.
export interface JobDetail {
  interviews: Interview[];
  job_summary?: string;
}

// ---------------------------------------------------------------------------
// Interviews
// ---------------------------------------------------------------------------

export interface Interview extends JobKey {
  id: number;
  interview_type: InterviewType;
  type_label: string | null;
  loop_id: string | null;
  scheduled_date: string | null;
  occurred_date: string | null;
  self_rating: number | null;
  notes: string | null;
}

// GET /api/interviews/upcoming: interview rows plus scheduling-derived
// fields. Never counted toward any rate (see the comment on the Flask route).
export interface UpcomingInterview extends Interview {
  days_away: number;
  overdue: boolean;
}

export interface InterviewOutcomeCounts {
  advanced: number;
  failed: number;
  ghosted: number;
  awaiting_outcome: number;
  decided: number;
  rate: number | null;
}

export interface InterviewTypeStats {
  interview_type: InterviewType;
  total: InterviewOutcomeCounts;
  standalone: InterviewOutcomeCounts;
  loop: InterviewOutcomeCounts;
}

// GET /api/interviews/stats
export interface InterviewStats {
  by_type: InterviewTypeStats[];
  totals: {
    rounds: number;
    advanced: number;
    failed: number;
    ghosted: number;
    awaiting_outcome: number;
    orphaned: number;
    decided: number;
  };
  rate_min_rounds: number;
}

// ---------------------------------------------------------------------------
// Recruiters
// ---------------------------------------------------------------------------

export interface Recruiter {
  id: number;
  source: string;
  identity: string;
  email: string;
  name: string;
  agency: string;
  agency_domain: string | null;
  first_seen: string;
  last_seen: string;
  notes: string | null;
  // SQLite/libSQL stores this as an INTEGER 0/1, and the route hands it back
  // unconverted -- not a real bool at the JSON boundary.
  manual_entry: number;
  role_count: number;
  reply_count: number;
}

export interface RecruiterRole {
  id: number;
  recruiter_id: number;
  company: string;
  date_added: string;
  position_title: string;
  link: string;
  sourced_date: string;
  account: string | null;
  message_id: string | null;
  recruiter_name: string;
  recruiter_agency: string;
  recruiter_source: string;
  recruiter_identity: string;
  job_status: string;
  job_notes: string;
}

// A job that looks like it came from a conversation (LinkedIn/mail link) but
// has no recruiter linked to it -- jobs_db.unlinked_recruiter_rows(). Sorted by
// coverage tier then date. Auto-apply imports are excluded at the source.
export interface UncapturedRecruiterRow {
  company: string;
  date_added: string;
  position_title: string;
  link: string;
  status: string;
  notes: string | null;
  date_applied: string | null;
}

// Two counts and never a ratio -- recruiter_coverage()'s docstring explains
// why: the denominator is a heuristic, so a percentage would improve as the
// heuristic got stricter.
export interface RecruiterCoverage {
  captured: number;
  suspected_uncaptured: number;
  rows: UncapturedRecruiterRow[];
}

// GET /api/recruiters
export interface RecruitersResponse {
  recruiters: Recruiter[];
  roles: RecruiterRole[];
  coverage: RecruiterCoverage;
}

// ---------------------------------------------------------------------------
// Funnel
// ---------------------------------------------------------------------------

export interface FunnelStage {
  stage: string;
  count: number;
  rate: number | null;
}

export interface FunnelSource {
  interviewed_total: number;
  interviewed_unattributed: number;
  application_path: FunnelStage[];
  outreach_path: FunnelStage[];
  rejected: number;
  both_paths: number;
}

// GET /api/funnel. `sources` carries the same shape three times, sliced by
// how the job was found.
export interface FunnelStats {
  sources: {
    all: FunnelSource;
    hand: FunnelSource;
    auto: FunnelSource;
  };
  rate_min_denominator: number;
}

// ---------------------------------------------------------------------------
// Silence
// ---------------------------------------------------------------------------

export interface SilenceCounts {
  hand: number;
  auto: number;
  total: number;
}

export interface SilenceRow {
  company: string;
  date_added: string;
  position_title: string;
  link: string;
  status: string;
  state: string;
  signal: string;
  since: string;
  idle_days: number;
  auto_applied: boolean;
}

// GET /api/silence. Derived on read -- no silence verdict is ever stored.
export interface SilenceStats {
  counts: {
    ghosted: SilenceCounts;
    no_response: SilenceCounts;
    waiting: SilenceCounts;
  };
  ghosted_rows: SilenceRow[];
  no_response_rows: SilenceRow[];
  ghosted_after_days: number;
  no_response_after_days: number;
}
