/**
 * TanStack Query hooks for the /api/* routes that exist today. Deliberately
 * thin -- no UI logic lives here, just the fetch + query key + typing.
 */

import { useQuery } from "@tanstack/react-query";
import { getJSON } from "./client";
import type {
  AppConfig,
  CompanyProfileResponse,
  FunnelStats,
  JobDetail,
  JobKey,
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

export function useJobDetail(
  key: JobKey | undefined,
  options: { summary?: boolean; job?: boolean; prep?: boolean } = {},
) {
  return useQuery({
    queryKey: ["jobDetail", key, options.summary, options.job, options.prep],
    queryFn: () => {
      const k = key as JobKey;
      const params = new URLSearchParams({
        company: k.company,
        date_added: k.date_added,
        position_title: k.position_title,
        link: k.link,
      });
      if (options.summary === false) params.set("summary", "0");
      if (options.job) params.set("job", "1");
      if (options.prep) params.set("prep", "1");
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

// Keyed on the company, not the job. Two roles at one employer share the
// profile and therefore share the cache entry, so researching from one job and
// opening the other shows the research already there.
export function useCompanyProfile(company: string | undefined) {
  return useQuery({
    queryKey: ["companyProfile", (company || "").trim().toLowerCase()],
    queryFn: () =>
      getJSON<CompanyProfileResponse>(
        `/api/companies/profile?company=${encodeURIComponent(company as string)}`,
      ),
    enabled: Boolean((company || "").trim()),
  });
}
