/*
 * React port of `create(ctx)`'s persistence surface in
 * src/static/job_fields.js (lines ~215-403 as of Phase 2, plus the recruiter
 * persistence helpers at ~330-386).
 *
 * Phase 3a added saveField and deleteJob; Phase 3b adds the recruiter pair
 * below, which <RecruiterField> is the only consumer of. The two shipped
 * separately because together they ran to three times this repo's per-PR
 * budget.
 *
 * That file mixed persistence
 * (`saveField`, `deleteJob`, `saveJobRecruiter`, `createRecruiter`,
 * `loadRecruiters`) with DOM building (`create(ctx)` and its field
 * builders). This hook owns only the persistence half; the field builders
 * become the components in this directory.
 *
 * ctx keys that do NOT reappear here, and why:
 *   - `interviewTypes` was a Jinja global this file couldn't see. Phase 0's
 *     `useConfig()` (frontend/src/api/queries.ts) already exposes
 *     `interview_types` over HTTP, so callers use that directly instead of
 *     threading it through this hook.
 *   - `tagFields` set `data-field` on editable elements so the kanban modal
 *     could find them again to rebuild. React re-renders from state, so
 *     nothing ever needs to "find a node again" -- there is no port of this
 *     key at all.
 *   - `stopClicks` doesn't belong in a persistence hook either way -- see
 *     the per-component comments (DateField, FollowupField, DetailField,
 *     RecruiterField) for where that decision landed.
 *
 * `afterSave` / `onDeleted` redesign:
 * The original mutated a shared `allJobs` array in place and then called a
 * view-supplied `render()`. In React, "mutate the array" is exactly what a
 * TanStack Query cache update is for: `patchJobInCaches` / `removeJobFromCaches`
 * below update every cached `/api/jobs` page and `/api/jobs/detail` entry for
 * the affected job, so any component reading that data (a table row, a goal
 * badge, a kanban column) re-renders on its own -- no hand-rolled
 * `afterSave`/`render()` callback needed for that part.
 *
 * What's left over -- work a cache update cannot do, like the kanban modal
 * closing itself after a delete -- stays as an optional callback
 * (`onFieldSaved` / `onDeleted`) on this hook, deliberately narrower than the
 * original's "redraw everything" callbacks.
 */
import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { postJSON, ApiError } from "../api/client";
import { jobKeyFields, rowKey, type JobKeyInput } from "../lib/jobFields";
import type { Job, JobKey, JobsPage, JobDetail, Recruiter } from "../api/types";

// ---------------------------------------------------------------------------
// Cache helpers -- the React replacement for "mutate `job`, then re-render".
// ---------------------------------------------------------------------------

function patchJobInCaches(queryClient: QueryClient, key: JobKeyInput, patch: Partial<Job>) {
  queryClient.setQueriesData<JobsPage>({ queryKey: ["jobs"], exact: false }, (page) => {
    if (!page) return page;
    return {
      ...page,
      jobs: page.jobs.map((j) => (rowKey(j) === rowKey(key) ? { ...j, ...patch } : j)),
    };
  });
  // /api/jobs/detail is keyed by the job key, not by list membership, so it
  // needs its own patch -- but only interviews/job_summary live there today,
  // neither of which this hook ever writes, so there is nothing to patch yet.
  // Left as a no-op comment rather than silently doing nothing invisibly.
}

function removeJobFromCaches(queryClient: QueryClient, key: JobKeyInput) {
  queryClient.setQueriesData<JobsPage>({ queryKey: ["jobs"], exact: false }, (page) => {
    if (!page) return page;
    return { ...page, jobs: page.jobs.filter((j) => rowKey(j) !== rowKey(key)) };
  });
  queryClient.removeQueries({ queryKey: ["jobDetail", key], exact: false });
}

// ---------------------------------------------------------------------------
// saveField
// ---------------------------------------------------------------------------

export interface SaveFieldVariables {
  job: JobKeyInput;
  field: string;
  value: string;
}

interface SaveFieldResponse {
  date_applied?: string;
  [k: string]: unknown;
}

// ---------------------------------------------------------------------------
// setRecruiter -- POST /api/jobs/recruiter
// ---------------------------------------------------------------------------

export interface RecruiterLinkResult {
  recruiter_id: number | null;
  recruiter_name: string | null;
  recruiter_agency: string | null;
  recruiter_from_triage: boolean;
}

// Resolves rather than throws on a 409: the original's comment on
// saveJobRecruiter explains why a blocked write is an *expected* answer here
// (the link belongs to a message; the caller offers an override), not an
// error. Any other failure still throws, same as saveField/deleteJob.
export type SetRecruiterResult =
  | { ok: true; recruiter: RecruiterLinkResult }
  | { ok: false; blocked: unknown[]; error: string };

export interface CreateRecruiterFields {
  name: string;
  agency: string;
  email: string;
}

export interface UseJobFieldEditingOptions {
  /** Called after a field write lands, in addition to the cache patch. */
  onFieldSaved?: (job: JobKeyInput, field: string, value: string) => void;
  /** Called after a successful delete, in addition to the cache removal. */
  onDeleted?: (job: JobKeyInput) => void;
}

export function useJobFieldEditing(options: UseJobFieldEditingOptions = {}) {
  const queryClient = useQueryClient();

  /*
   * Mutates `job` in place on success so the caller's copy stays current
   * without a refetch, and picks up `date_applied` when the server
   * back-fills it as a side effect of moving a job to Applied.
   *
   * Ported behaviour, React-shaped: instead of mutating a plain object, the
   * mutation patches every cache that holds this job. Components read the
   * job from `useJobs`/`useJobDetail`, so they see the new value the same
   * render TanStack Query re-renders them for -- no separate "did it work"
   * plumbing needed beyond the mutation's own pending/error state.
   */
  const saveField = useMutation({
    mutationFn: async ({ job, field, value }: SaveFieldVariables) => {
      return postJSON<SaveFieldResponse>("/api/jobs/update", {
        ...jobKeyFields(job),
        field,
        value,
      });
    },
    onSuccess: (data, variables) => {
      const patch: Partial<Job> = { [variables.field]: variables.value } as Partial<Job>;
      if (data.date_applied !== undefined) {
        patch.date_applied = data.date_applied;
      }
      patchJobInCaches(queryClient, variables.job, patch);
      options.onFieldSaved?.(variables.job, variables.field, variables.value);
    },
  });

  /*
   * Confirmation itself is NOT this mutation's job -- see DeleteJobButton
   * (or whichever component ends up owning the delete control in Phase 4/5)
   * for the injectable confirm() seam. This mutation assumes the caller has
   * already confirmed, mirroring `deleteJob`'s body *after* its `confirm()`
   * guard in the original.
   */
  const deleteJob = useMutation({
    mutationFn: (job: JobKeyInput) => postJSON<unknown>("/api/jobs/delete", jobKeyFields(job)),
    onSuccess: (_data, job) => {
      removeJobFromCaches(queryClient, job);
      options.onDeleted?.(job);
    },
  });

  const setRecruiter = useMutation({
    mutationFn: async (vars: {
      job: JobKeyInput;
      recruiterId: number | null;
      override: boolean;
    }): Promise<SetRecruiterResult> => {
      try {
        const data = await postJSON<{ recruiter: RecruiterLinkResult | null }>(
          "/api/jobs/recruiter",
          {
            ...jobKeyFields(vars.job),
            recruiter_id: vars.recruiterId,
            override: vars.override,
          },
        );
        const r = data.recruiter;
        return {
          ok: true,
          recruiter: {
            recruiter_id: r ? r.recruiter_id : null,
            recruiter_name: r ? r.recruiter_name : null,
            recruiter_agency: r ? r.recruiter_agency : null,
            // message_id on the wire (see recruiterLabel/saveJobRecruiter in
            // the original) means "this link came from inbox-triage".
            recruiter_from_triage: !!(r && (r as unknown as { message_id?: unknown }).message_id),
          },
        };
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          const body = e.body as { blocked?: unknown[] } | undefined;
          return { ok: false, blocked: body?.blocked ?? [], error: e.message };
        }
        throw e;
      }
    },
    onSuccess: (result, variables) => {
      if (result.ok) {
        patchJobInCaches(queryClient, variables.job, {
          recruiter_id: result.recruiter.recruiter_id,
          recruiter_name: result.recruiter.recruiter_name,
          recruiter_agency: result.recruiter.recruiter_agency,
          recruiter_from_triage: result.recruiter.recruiter_from_triage,
        });
      }
      // The blocked (409) case is deliberately NOT patched here: the caller
      // (RecruiterField) re-locks by patching recruiter_from_triage itself,
      // because that patch has to happen synchronously with the redraw --
      // see the component for the "raced with triage" comment.
    },
  });

  /*
   * The original's `loadRecruiters` kept a module-level cache shared by
   * every combobox on the page, refreshed after a create. That cache is
   * just `useRecruiters()` (frontend/src/api/queries.ts) now -- TanStack
   * Query already dedupes and shares the fetch. This mutation's onSuccess
   * invalidates that query instead of manually refetching and splicing the
   * result in, so a recruiter created from any field becomes selectable
   * everywhere on the next render.
   */
  const createRecruiter = useMutation({
    mutationFn: (fields: CreateRecruiterFields) =>
      postJSON<{ recruiter: Recruiter }>("/api/recruiters/add", fields),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recruiters"] });
    },
  });

  return { saveField, deleteJob, setRecruiter, createRecruiter };
}

// Re-exported only for tests that want to assert on cache shape directly
// without reaching into the hook's closure.
export const _internal = { patchJobInCaches, removeJobFromCaches };

export type { JobKey, JobDetail };
