/*
 * Data wiring for the job view: the one place in this tree that fetches.
 *
 * The job key is the four identity columns, carried in the URL rather than in
 * router state, so the page survives a hard refresh and can be linked to from
 * the Jinja table -- which is how it is reached at all until the table is cut
 * over. The link is long and ugly; it is also the only honest key, since
 * company alone is ambiguous for the 174 companies with more than one role.
 */
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  useCompanyProfile, useConfig, useJobDetail, useRecruiters,
} from "../../api/queries";
import { useCompanyEditing } from "../../hooks/useCompanyEditing";
import { useInterviewEditing } from "../../hooks/useInterviewEditing";
import { useJobFieldEditing } from "../../hooks/useJobFieldEditing";
import type { Job, JobKey } from "../../api/types";
import { JobView } from "../shared/JobView";
import styles from "./JobViewPage.module.css";

function keyFromParams(params: URLSearchParams): JobKey | undefined {
  const company = params.get("company");
  if (!company) return undefined;
  return {
    company,
    date_added: params.get("date_added") || "",
    position_title: params.get("position_title") || "",
    link: params.get("link") || "",
  };
}

export function jobViewPath(job: JobKey): string {
  const params = new URLSearchParams({
    company: job.company,
    date_added: job.date_added,
    position_title: job.position_title,
    link: job.link,
  });
  return `/job?${params.toString()}`;
}

export default function JobViewPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const key = keyFromParams(params);

  const config = useConfig();
  const recruiters = useRecruiters();
  /*
   * ?job=1 so the row arrives with the summary and the rounds, in one request.
   *
   * The obvious alternative is to read it out of the cached job list, which is
   * what this did first -- and it is wrong here in a way it would not be inside
   * a single-page app: this view is reached by a full page load out of the
   * Jinja table, so the cache is always empty on arrival and "already cached"
   * never happens. Every open paid 1.5MB and ~1.2s to find fifteen fields.
   */
  const detail = useJobDetail(key, { job: true });
  const job = detail.data?.job;

  const { saveField, deleteJob, setRecruiter, createRecruiter } = useJobFieldEditing({
    onDeleted: () => navigate("/"),
  });
  const { addInterview, deleteInterview } = useInterviewEditing(key ?? ({} as JobKey));
  /*
   * Keyed on the company, so it is fetched alongside the job rather than out of
   * it: the profile belongs to the employer and is shared by every role tracked
   * there. Its own request, because it has its own cache lifetime -- the job
   * detail is re-read on every open, the research is not.
   */
  const companyProfile = useCompanyProfile(key?.company);
  const { saveSection } = useCompanyEditing(key?.company ?? "");

  if (!key) return <p className={styles.state}>No job specified.</p>;
  if (detail.isLoading) return <p className={styles.state}>Loading…</p>;
  if (detail.isError) return <p className={styles.state}>Could not load this job.</p>;
  if (!job) {
    return (
      <p className={styles.state}>
        No tracked job matches that link — it may have been renamed or deleted.
      </p>
    );
  }

  return (
    <JobView
      job={{ ...(job as Job), job_summary: detail.data?.job_summary }}
      rounds={detail.data?.interviews ?? []}
      interviewTypes={config.data?.interview_types ?? []}
      recruiters={recruiters.data?.recruiters ?? []}
      onSaveField={(field, value) => saveField.mutateAsync({ job, field, value })}
      setRecruiter={(id, override) => setRecruiter.mutateAsync({ job, recruiterId: id, override })}
      createRecruiter={(fields) =>
        createRecruiter.mutateAsync(fields).then((r) => r.recruiter)}
      onAddInterview={(fields) => addInterview.mutateAsync(fields)}
      onDeleteInterview={(id) => deleteInterview.mutateAsync(id)}
      companyProfile={companyProfile.data?.profile ?? null}
      companyLoading={companyProfile.isLoading}
      onSaveCompanySection={(field, value) => saveSection.mutateAsync({ field, value })}
      onDelete={() => deleteJob.mutateAsync(job)}
    />
  );
}
