/*
 * The jobs list, painted after the first page and completed in the background.
 *
 * Ports the load loop from loadJobs() in src/templates/jobs.html. The shape of
 * that loop is not incidental: /api/jobs over 1,088 active rows is ~1.2MB, so
 * fetching it in one request means an empty table for about a second, while
 * fetching only a page means search and sort silently answer against a subset.
 * Fifty rows, then the rest at 2,000 a time, gives a readable table immediately
 * and a complete one to search against shortly after.
 *
 * Why the loop lives inside queryFn rather than in useInfiniteQuery:
 * patchJobInCaches (useJobFieldEditing) reads and rewrites a flat JobsPage
 * under ["jobs", options]. useInfiniteQuery stores {pages, pageParams} instead,
 * so converting would make every field save and every delete throw. The
 * original spec called this out and it is still true. Publishing each page with
 * setQueryData under the same flat key keeps that contract while still painting
 * progressively -- the cache never holds anything but a flat list.
 */
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { getJSON } from "../api/client";
import type { Job, JobsPage } from "../api/types";

// Matches FIRST_PAGE / PREFETCH_PAGE in jobs.html. The first is sized to fill
// a screen; the second is sized to finish in as few round trips as the server's
// own cap allows.
export const FIRST_PAGE = 50;
export const PREFETCH_PAGE = 2000;

export interface JobsList {
  jobs: Job[];
  /** More pages are still arriving. Not the same as "the list is short". */
  prefetching: boolean;
  /**
   * A page failed and the rest will never arrive, so `jobs` is a prefix of the
   * real list rather than all of it. Callers must say so on screen: a silently
   * short list makes the search box answer "no matches" for jobs that exist.
   */
  truncated: boolean;
}

export interface UseJobsOptions {
  includeArchived?: boolean;
}

export function jobsQueryKey(options: UseJobsOptions = {}) {
  return ["jobs", options] as const;
}

function pageUrl(options: UseJobsOptions, limit: number, cursor?: string) {
  const params = new URLSearchParams();
  if (options.includeArchived) params.set("include_archived", "1");
  params.set("limit", String(limit));
  if (cursor) params.set("cursor", cursor);
  return `/api/jobs?${params.toString()}`;
}

export function useJobsProgressive(options: UseJobsOptions = {}) {
  const queryClient = useQueryClient();

  return useQuery<JobsList>({
    queryKey: jobsQueryKey(options),
    queryFn: ({ signal }) => loadAllJobs(queryClient, options, signal),
    // The loop already refuses to publish once the signal aborts, and a
    // background refetch of a 1.2MB list on every window focus is not a thing
    // anyone asked for.
    refetchOnWindowFocus: false,
  });
}

/**
 * Exported for tests: the whole behaviour is in here, and driving it through a
 * React hook to assert on page counts would test the renderer instead.
 */
export async function loadAllJobs(
  queryClient: QueryClient,
  options: UseJobsOptions = {},
  signal?: AbortSignal,
): Promise<JobsList> {
  const key = jobsQueryKey(options);

  // Publishing a page means writing it to the cache the observers already read
  // from. Skipped once aborted: a superseded load must not overwrite the newer
  // one's rows, which is what the loadToken counter guards against in the
  // vanilla version -- here the signal already carries that information.
  const publish = (list: JobsList) => {
    if (signal?.aborted) return;
    queryClient.setQueryData<JobsList>(key, list);
  };

  let jobs: Job[] = [];
  let cursor: string | null | undefined;

  try {
    const first = await getJSON<JobsPage>(pageUrl(options, FIRST_PAGE), signal);
    jobs = first.jobs;
    cursor = first.next_cursor;
  } catch (err) {
    // The first page failing is a genuinely empty result, not a short list --
    // there is nothing to show and nothing to caveat. Let it reject so the
    // caller renders its error state.
    throw err;
  }
  publish({ jobs, prefetching: Boolean(cursor), truncated: false });

  while (cursor) {
    if (signal?.aborted) break;
    let next: JobsPage;
    try {
      next = await getJSON<JobsPage>(pageUrl(options, PREFETCH_PAGE, cursor), signal);
    } catch {
      // Stop rather than retry, and keep what arrived. Throwing here would
      // discard the rows already on screen and replace a readable partial table
      // with an error -- worse than a complete-looking table, which is why the
      // flag exists rather than either extreme.
      const truncated = { jobs, prefetching: false, truncated: true };
      publish(truncated);
      return truncated;
    }
    jobs = jobs.concat(next.jobs);
    cursor = next.next_cursor;
    publish({ jobs, prefetching: Boolean(cursor), truncated: false });
  }

  return { jobs, prefetching: false, truncated: false };
}
