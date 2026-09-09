/**
 * TanStack Query hooks for the /api/* routes that exist today. Deliberately
 * thin -- no UI logic lives here, just the fetch + query key + typing.
 */

import { useQuery } from "@tanstack/react-query";
import { getJSON } from "./client";
import type {
  AppConfig,
  FunnelStats,
  Job,
  JobDetail,
  JobKey,
  JobsPage,
  RecruitersResponse,
  SilenceStats,
  InterviewStats,
  UpcomingInterview,
} from "./types";

export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: () => getJSON<AppConfig>("/api/config"),
  });
}

export interface UseJobsOptions {
  limit?: number;
  cursor?: string;
  includeArchived?: boolean;
}

// /api/jobs returns a bare Job[] with no ?limit, or {jobs, next_cursor} with
// one. This hook always resolves to a JobsPage so callers don't have to
// branch on the caller's own arguments to know which shape came back.
export function useJobs(options: UseJobsOptions = {}) {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.includeArchived) params.set("include_archived", "1");
  const qs = params.toString();

  return useQuery({
    queryKey: ["jobs", options],
    queryFn: async (): Promise<JobsPage> => {
      const data = await getJSON<Job[] | JobsPage>(`/api/jobs${qs ? `?${qs}` : ""}`);
      return Array.isArray(data) ? { jobs: data, next_cursor: null } : data;
    },
  });
}

export function useJobDetail(key: JobKey | undefined, options: { summary?: boolean } = {}) {
  return useQuery({
    queryKey: ["jobDetail", key, options.summary],
    queryFn: () => {
      const k = key as JobKey;
      const params = new URLSearchParams({
        company: k.company,
        date_added: k.date_added,
        position_title: k.position_title,
        link: k.link,
      });
      if (options.summary === false) params.set("summary", "0");
      return getJSON<JobDetail>(`/api/jobs/detail?${params.toString()}`);
    },
    enabled: key !== undefined,
  });
}

export function useFunnel() {
  return useQuery({
    queryKey: ["funnel"],
    queryFn: () => getJSON<FunnelStats>("/api/funnel"),
  });
}

export function useSilence() {
  return useQuery({
    queryKey: ["silence"],
    queryFn: () => getJSON<SilenceStats>("/api/silence"),
  });
}

export function useRecruiters() {
  return useQuery({
    queryKey: ["recruiters"],
    queryFn: () => getJSON<RecruitersResponse>("/api/recruiters"),
  });
}

export function useUpcomingInterviews(includePast = false) {
  return useQuery({
    queryKey: ["upcomingInterviews", includePast],
    queryFn: () =>
      getJSON<UpcomingInterview[]>(
        `/api/interviews/upcoming${includePast ? "?include_past=1" : ""}`,
      ),
  });
}

export function useInterviewStats() {
  return useQuery({
    queryKey: ["interviewStats"],
    queryFn: () => getJSON<InterviewStats>("/api/interviews/stats"),
  });
}
