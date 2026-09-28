/*
 * Data wiring for the job view: the one place in this tree that fetches.
 *
 * The job key is the four identity columns, carried in the URL rather than in
 * router state, so the page survives a hard refresh and can be pasted or
 * bookmarked. The link is long and ugly; it is also the only honest key,
 * since company alone is ambiguous for the 174 companies with more than one
 * role.
 */
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useConfig, useJobDetail, useRecruiters } from "../../api/queries";
import { useCompanyEditing } from "../../hooks/useCompanyEditing";
import { usePrepEditing } from "../../hooks/usePrepEditing";
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
  /*
   * Deferred until the People tab is opened. /api/recruiters measured 1,974ms
   * of the ~5.2s this page used to cost, for a list that fills one <select> --
   * the job's own recruiter name comes down with the detail payload, so
   * nothing on screen waits for this.
   */
  const [peopleOpened, setPeopleOpened] = useState(false);
  const recruiters = useRecruiters({ enabled: peopleOpened });
  /*
   * ?job=1 so the row arrives with the summary and the rounds, in one request.
   *
   * The obvious alternative is to read the row out of the cached job list.
   * Now that "/" is React, arriving from a row click does find it there -- but
   * a bookmark, a paste or a hard refresh does not, and the summary, the prep
   * items and the company profile are never in the list payload, so the
   * request happens either way. `job: true` only widens the column list of a
   * SELECT that is already being issued; it costs no extra round trip, and
   * dropping it would trade that for a branch that is wrong on every cold
   * open.
   */
  const detail = useJobDetail(key, { job: true, prep: true, companyProfile: true });
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
  const { saveSection } = useCompanyEditing(key?.company ?? "");
  const prep = usePrepEditing(key ?? ({} as JobKey));

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
      companyProfile={detail.data?.company_profile ?? null}
      companyLoading={detail.isLoading}
      onSaveCompanySection={(field, value) => saveSection.mutateAsync({ field, value })}
      prepItems={detail.data?.prep_items ?? []}
      onAddPrepItem={(fields) => prep.addItem.mutateAsync(fields)}
      onSetPrepDone={(id, done) => prep.setDone.mutateAsync({ id, done })}
      onEditPrepItem={(id, body) => prep.editItem.mutateAsync({ id, body })}
      onDeletePrepItem={(id) => prep.deleteItem.mutateAsync(id)}
      onDelete={() => deleteJob.mutateAsync(job)}
      onTabChange={(tab) => { if (tab === "People") setPeopleOpened(true); }}
    />
  );
}
