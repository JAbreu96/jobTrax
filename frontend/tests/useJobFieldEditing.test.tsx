/*
 * Covers the persistence surface ported from src/static/job_fields.js's
 * saveField/deleteJob/saveJobRecruiter/createRecruiter (lines ~215-403,
 * ~330-386 as of Phase 2), now as TanStack Query mutations.
 *
 * fetch is mocked directly (vi.stubGlobal) rather than the client module, so
 * these tests also exercise api/client.ts's request-shape and error-parsing
 * behaviour end to end.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useJobFieldEditing } from "../src/hooks/useJobFieldEditing";
import type { Job, JobsPage } from "../src/api/types";

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    company: "Acme",
    date_added: "2026-01-01",
    position_title: "Engineer",
    link: "https://example.com/job",
    location: "Remote",
    contacts: "",
    notes: "",
    outreach_date: "",
    date_applied: "",
    status: "Tracking",
    followup_log: "",
    recruiter_id: null,
    recruiter_name: null,
    recruiter_agency: null,
    recruiter_from_triage: false,
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function wrapperWithJobsCache(job: Job) {
  const queryClient = new QueryClient();
  const page: JobsPage = { jobs: [job], next_cursor: null };
  queryClient.setQueryData(["jobs", {}], page);
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return { queryClient, Wrapper };
}

describe("useJobFieldEditing", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("saveField posts the full composite key plus field/value", async () => {
    const job = makeJob();
    const { Wrapper } = wrapperWithJobsCache(job);
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(jsonResponse({}));

    const { result } = renderHook(() => useJobFieldEditing(), { wrapper: Wrapper });
    await act(async () => {
      await result.current.saveField.mutateAsync({ job, field: "notes", value: "hi" });
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/jobs/update",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          company: job.company,
          date_added: job.date_added,
          position_title: job.position_title,
          link: job.link,
          field: "notes",
          value: "hi",
        }),
      }),
    );
  });

  it("reflects a server-backfilled date_applied in the cache without a refetch", async () => {
    const job = makeJob({ status: "Tracking", date_applied: "" });
    const { Wrapper, queryClient } = wrapperWithJobsCache(job);
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(
      jsonResponse({ date_applied: "2026-02-10" }),
    );

    const { result } = renderHook(() => useJobFieldEditing(), { wrapper: Wrapper });
    await act(async () => {
      await result.current.saveField.mutateAsync({ job, field: "status", value: "Applied" });
    });

    const page = queryClient.getQueryData<JobsPage>(["jobs", {}]);
    expect(page?.jobs[0].status).toBe("Applied");
    expect(page?.jobs[0].date_applied).toBe("2026-02-10");
  });

  it("surfaces the server's {error} message on a failed save", async () => {
    const job = makeJob();
    const { Wrapper } = wrapperWithJobsCache(job);
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(
      jsonResponse({ error: "notes is too long" }, 400),
    );

    const { result } = renderHook(() => useJobFieldEditing(), { wrapper: Wrapper });
    await expect(
      act(async () => {
        await result.current.saveField.mutateAsync({ job, field: "notes", value: "x".repeat(10) });
      }),
    ).rejects.toThrow("notes is too long");
  });

  it("deleteJob posts the composite key and removes the job from the cache", async () => {
    const job = makeJob();
    const { Wrapper, queryClient } = wrapperWithJobsCache(job);
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(jsonResponse({}));

    const { result } = renderHook(() => useJobFieldEditing(), { wrapper: Wrapper });
    await act(async () => {
      await result.current.deleteJob.mutateAsync(job);
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/jobs/delete",
      expect.objectContaining({
        body: JSON.stringify({
          company: job.company,
          date_added: job.date_added,
          position_title: job.position_title,
          link: job.link,
        }),
      }),
    );
    const page = queryClient.getQueryData<JobsPage>(["jobs", {}]);
    expect(page?.jobs).toHaveLength(0);
  });

  it("resolves (does not throw) a 409 with a blocked list from setRecruiter", async () => {
    const job = makeJob({ recruiter_id: 1, recruiter_from_triage: false });
    const { Wrapper } = wrapperWithJobsCache(job);
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(
      jsonResponse({ error: "linked to a message", blocked: [{ id: 5 }] }, 409),
    );

    const { result } = renderHook(() => useJobFieldEditing(), { wrapper: Wrapper });
    let outcome;
    await act(async () => {
      outcome = await result.current.setRecruiter.mutateAsync({
        job,
        recruiterId: 2,
        override: false,
      });
    });

    expect(outcome).toEqual({
      ok: false,
      blocked: [{ id: 5 }],
      error: "linked to a message",
    });
  });

  it("patches the job's recruiter fields in the cache on a successful setRecruiter", async () => {
    const job = makeJob();
    const { Wrapper, queryClient } = wrapperWithJobsCache(job);
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(
      jsonResponse({
        recruiter: {
          recruiter_id: 9,
          recruiter_name: "Jane",
          recruiter_agency: "Agency Co",
          message_id: null,
        },
      }),
    );

    const { result } = renderHook(() => useJobFieldEditing(), { wrapper: Wrapper });
    await act(async () => {
      await result.current.setRecruiter.mutateAsync({ job, recruiterId: 9, override: false });
    });

    const page = queryClient.getQueryData<JobsPage>(["jobs", {}]);
    expect(page?.jobs[0].recruiter_id).toBe(9);
    expect(page?.jobs[0].recruiter_name).toBe("Jane");
    expect(page?.jobs[0].recruiter_from_triage).toBe(false);
  });

  it("createRecruiter posts the fields and invalidates the recruiters query", async () => {
    const job = makeJob();
    const { Wrapper, queryClient } = wrapperWithJobsCache(job);
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(
      jsonResponse({ recruiter: { id: 3, name: "Jane", agency: "", email: "j@x.com" } }),
    );

    const { result } = renderHook(() => useJobFieldEditing(), { wrapper: Wrapper });
    await act(async () => {
      await result.current.createRecruiter.mutateAsync({
        name: "Jane",
        agency: "",
        email: "j@x.com",
      });
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/recruiters/add",
      expect.objectContaining({
        body: JSON.stringify({ name: "Jane", agency: "", email: "j@x.com" }),
      }),
    );
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["recruiters"] });
  });
});
