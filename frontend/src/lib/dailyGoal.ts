/*
 * How many jobs were applied to today, against the daily target.
 *
 * Ported from updateGoalBadge() in src/templates/jobs.html. Pure so the
 * counting rule is testable without a DOM -- it has two conditions and both
 * are easy to get subtly wrong.
 */
import { localISODate } from "./jobFields";
import type { Job } from "../api/types";

export const DAILY_GOAL = 5;

export interface GoalProgress {
  applied: number;
  goal: number;
  met: boolean;
}

/**
 * Counts rows whose status is exactly "Applied" **and** whose date_applied is
 * today.
 *
 * Both conditions, not either. Status alone would count every job ever
 * applied to; date alone would count a row that has since moved on to Phone
 * Screen -- which is a real application made today, but the badge is a
 * measure of the Applied pile, and the vanilla version drew it this way. The
 * comparison is against local-midnight ISO, not UTC: at 8pm Eastern, a UTC
 * date is already tomorrow and the badge would silently reset mid-evening.
 */
export function dailyGoalProgress(jobs: Job[], today = localISODate(new Date())): GoalProgress {
  const applied = jobs.filter(
    (j) => j.status === "Applied" && (j.date_applied || "") === today,
  ).length;
  return { applied, goal: DAILY_GOAL, met: applied >= DAILY_GOAL };
}
