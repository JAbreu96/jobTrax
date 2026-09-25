/*
 * Adding and removing interview rounds.
 *
 * Separate from useJobFieldEditing because rounds are not job fields: they
 * live in their own table, arrive only through /api/jobs/detail, and are
 * written by inbox-triage on a cron as well as by hand. That second writer is
 * why the detail query is invalidated rather than patched -- a local patch
 * would paper over rounds the cron added since the page loaded, and the round
 * list is short enough that the refetch costs nothing.
 *
 * Ports the persistence half of makeInterviewsField in
 * src/static/job_fields.js. The one-date model is deliberate: `occurred_date`
 * was dropped from the API, and /api/interviews/add now rejects it -- the
 * scheduled date alone decides whether a round is booked or happened.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { postJSON } from "../api/client";
import { jobKeyFields, rowKey, type JobKeyInput } from "../lib/jobFields";
import type { InterviewType } from "../api/types";

export interface AddInterviewFields {
  interview_type: InterviewType;
  scheduled_date: string;
  type_label?: string;
  loop_id?: string;
  self_rating?: string;
  notes?: string;
}

/** Matches every ["jobDetail", key, summary] entry for one job.
 *
 *  Same predicate shape, and the same reason, as jobDetailEntries() in
 *  useJobFieldEditing: the key object is compared structurally, so a filter
 *  built from a fat Job row matches none of the entries mounted with a bare
 *  JobKey. rowKey() compares the four identity columns and only those. */
function jobDetailEntries(key: JobKeyInput) {
  const target = rowKey(key);
  return {
    predicate: (q: { queryKey: readonly unknown[] }) =>
      q.queryKey[0] === "jobDetail" &&
      q.queryKey[1] != null &&
      rowKey(q.queryKey[1] as JobKeyInput) === target,
  };
}

export function useInterviewEditing(job: JobKeyInput) {
  const queryClient = useQueryClient();

  function refresh() {
    void queryClient.invalidateQueries(jobDetailEntries(job));
    // The Insights funnel and the upcoming-interviews list both count rounds,
    // so they are stale the moment one is added anywhere.
    void queryClient.invalidateQueries({ queryKey: ["upcomingInterviews"] });
    void queryClient.invalidateQueries({ queryKey: ["funnel"] });
    void queryClient.invalidateQueries({ queryKey: ["interviewStats"] });
  }

  const addInterview = useMutation({
    mutationFn: (fields: AddInterviewFields) =>
      postJSON<unknown>("/api/interviews/add", { ...jobKeyFields(job), ...fields }),
    onSuccess: refresh,
  });

  const deleteInterview = useMutation({
    mutationFn: (id: number) => postJSON<unknown>("/api/interviews/delete", { id }),
    onSuccess: refresh,
  });

  return { addInterview, deleteInterview };
}
