/*
 * The job view: identity up top, tabs of detail, a status rail down the side.
 *
 * Replaces buildDetailGrid() in src/templates/jobs.html, which put nine fields
 * into `repeat(3, minmax(160px, 1fr))` inside a table cell -- so the job
 * description, the longest thing on the page, got a ~160px column and a 4.2em
 * clamp. The fix is not smaller gaps: it is giving prose a column of its own
 * and a line length (--measure), and giving everything else somewhere to be
 * that is not beside it.
 *
 * Company sits second because it is the tab you open when preparing rather
 * than when triaging: Overview is the posting, Company is the employer behind
 * every posting from them, People is who you have spoken to, Prep is the
 * rounds. That is also roughly the order you need them in as a job moves.
 *
 * Owns no data fetching -- same convention as every field component it
 * composes. JobViewPage does that and passes it down.
 */
import { useEffect, useRef, useState } from "react";
import type {
  CompanyProfile, CompanySection, Interview, InterviewType, Job, PrepItem,
  PrepKind, Recruiter,
} from "../../api/types";
import type {
  CreateRecruiterFields, SetRecruiterResult,
} from "../../hooks/useJobFieldEditing";
import type { ConfirmFn, NotifyFn } from "../../lib/dialogs";
import { defaultConfirm, defaultNotify } from "../../lib/dialogs";
import { DateField } from "./DateField";
import { DetailField } from "./DetailField";
import { FollowupField } from "./FollowupField";
import { InterviewsField } from "./InterviewsField";
import { CompanyTab } from "./CompanyTab";
import { MarkdownField } from "./MarkdownField";
import { PrepChecklist } from "./PrepChecklist";
import { RecruiterField } from "./RecruiterField";
import { StatusRail } from "./StatusRail";
import styles from "./JobView.module.css";

const TABS = ["Overview", "Company", "People", "Prep"] as const;
export type TabName = (typeof TABS)[number];

export interface JobViewProps {
  job: Job & { job_summary?: string };
  rounds: Interview[];
  interviewTypes: InterviewType[];
  recruiters: Recruiter[];
  onSaveField: (field: string, value: string) => void | Promise<unknown>;
  setRecruiter: (id: number | null, override: boolean) => Promise<SetRecruiterResult>;
  createRecruiter: (fields: CreateRecruiterFields) => Promise<Recruiter>;
  onAddInterview: (fields: {
    interview_type: InterviewType; scheduled_date: string;
    type_label?: string; self_rating?: string; notes?: string;
  }) => Promise<unknown>;
  onDeleteInterview: (id: number) => Promise<unknown>;
  prepItems?: PrepItem[];
  onAddPrepItem: (fields: { kind: PrepKind; body: string }) => Promise<unknown>;
  onSetPrepDone: (id: number, done: boolean) => Promise<unknown>;
  onEditPrepItem: (id: number, body: string) => Promise<unknown>;
  onDeletePrepItem: (id: number) => Promise<unknown>;
  companyProfile?: CompanyProfile | null;
  companyLoading?: boolean;
  onSaveCompanySection: (
    field: CompanySection | "website", value: string,
  ) => void | Promise<unknown>;
  onDelete: () => void | Promise<unknown>;
  /**
   * "page" is the standalone route: a centred card with its own width and
   * margins. "drawer" fills the panel it is handed instead -- no width of its
   * own, no margin, no outer border, since the panel already draws one.
   *
   * This switches the *outer* box only. The internal layout (whether the rail
   * sits beside the content or above it) is not a prop and must not become
   * one: it responds to the width this ends up with, through a container
   * query. See the module CSS.
   */
  layout?: "page" | "drawer";
  onClose?: () => void;
  /** Fires on every tab change, so the page can defer a fetch until the tab
   *  that needs it is actually opened. */
  onTabChange?: (tab: TabName) => void;
  confirm?: ConfirmFn;
  notify?: NotifyFn;
}

export function JobView({
  job, rounds, interviewTypes, recruiters,
  onSaveField, setRecruiter, createRecruiter,
  onAddInterview, onDeleteInterview, onDelete, onClose, onTabChange,
  layout = "page",
  companyProfile = null, companyLoading, onSaveCompanySection,
  prepItems = [], onAddPrepItem, onSetPrepDone, onEditPrepItem, onDeletePrepItem,
  confirm = defaultConfirm, notify = defaultNotify,
}: JobViewProps) {
  // Always Overview on open, never the last tab used. "Readable on a whim"
  // means the page looks the same every time you land on it.
  const [tab, setTab] = useState<TabName>("Overview");
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (!onClose) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Left/Right move between tabs, per the tablist pattern -- the legacy modal
  // had no keyboard affordances at all and closed only on a backdrop click.
  function onTabKey(e: React.KeyboardEvent, i: number) {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    e.preventDefault();
    const next = (i + delta + TABS.length) % TABS.length;
    setTab(TABS[next]);
    onTabChange?.(TABS[next]);
    tabRefs.current[next]?.focus();
  }

  const save = (field: string) => (value: string) => { void onSaveField(field, value); };

  return (
    <article className={`${styles.view} ${layout === "drawer" ? styles.inDrawer : ""}`}>
      <header className={styles.header}>
        <div className={styles.identity}>
          <h1 className={styles.title}>{job.position_title || "Untitled role"}</h1>
          <p className={styles.subtitle}>
            <span className={styles.company}>{job.company}</span>
            {job.location && <> · {job.location}</>}
            {job.date_added && <> · saved {job.date_added}</>}
          </p>
        </div>
        {job.link && (
          <a className={styles.posting} href={job.link} target="_blank" rel="noreferrer">
            View posting ↗
          </a>
        )}
      </header>

      <div className={styles.body}>
        <div className={styles.main}>
          <div className={styles.tabs} role="tablist" aria-label="Job details">
            {TABS.map((name, i) => (
              <button
                key={name}
                ref={(el) => { tabRefs.current[i] = el; }}
                role="tab"
                id={`tab-${name}`}
                aria-selected={tab === name}
                aria-controls={`panel-${name}`}
                tabIndex={tab === name ? 0 : -1}
                className={`${styles.tab} ${tab === name ? styles.tabActive : ""}`}
                onClick={() => { setTab(name); onTabChange?.(name); }}
                onKeyDown={(e) => onTabKey(e, i)}
              >
                {name}
              </button>
            ))}
          </div>

          {/* Panels are mounted only once visited, then kept mounted -- so
              switching back does not refetch or lose a half-typed note. */}
          <Panel name="Overview" active={tab}>
            <div className={styles.fieldRow}>
              <DateField label="Outreach date" value={job.outreach_date || ""}
                         fieldClass={styles.field} onSave={save("outreach_date")} />
              <DateField label="Date applied" value={job.date_applied || ""}
                         fieldClass={styles.field} onSave={save("date_applied")} />
            </div>
            {/* Read-only: `location` is not in EDITABLE_COLUMNS, so
                /api/jobs/update answers 400 for it. */}
            <div className={styles.field}>
              <label>Location</label>
              <p className={styles.static}>{job.location || "—"}</p>
            </div>
            <section className={styles.section}>
              <h3 className={styles.sectionHeading}>Job description</h3>
              {/* expandable={false}: unclamped. The 4.2em clamp existed because
                  the panel lived in a table row and could not push the table
                  around. It has its own scroll region now. */}
              <div className={styles.description}>
                <MarkdownField label="" value={job.job_summary || ""}
                               expandable={false} fieldClass={styles.prose}
                               onSave={save("job_summary")} />
              </div>
            </section>
          </Panel>

          <Panel name="Company" active={tab}>
            <CompanyTab company={job.company} profile={companyProfile}
                        isLoading={companyLoading}
                        onSaveSection={onSaveCompanySection} />
          </Panel>

          <Panel name="People" active={tab}>
            <RecruiterField job={job} recruiters={recruiters}
                            setRecruiter={setRecruiter} createRecruiter={createRecruiter}
                            fieldClass={styles.field} confirm={confirm} notify={notify} />
            <DetailField label="Contacts" value={job.contacts || ""}
                         fieldClass={styles.field} onSave={save("contacts")}
                         notify={notify} />
            <FollowupField label="Follow-ups" value={job.followup_log || ""}
                           fieldClass={styles.field} onSave={save("followup_log")} />
          </Panel>

          {/* Checklist first, rounds last. The rounds are a record of what is
              booked; the checklist is the thing you act on, and only 2 of the
              1,314 tracked jobs have a round still in the future -- so leading
              with the schedule would lead with an empty box on almost every
              job. */}
          <Panel name="Prep" active={tab}>
            <PrepChecklist items={prepItems}
                           onAdd={onAddPrepItem} onSetDone={onSetPrepDone}
                           onEdit={onEditPrepItem} onDelete={onDeletePrepItem}
                           confirm={confirm} />
            {/* styles.prepHeading, not sectionHeading: this sits directly
                under two headings PrepChecklist renders as small uppercase
                labels, and a 15px semibold "Rounds" beneath them reads as a
                different kind of thing rather than the third section. */}
            <section className={styles.section}>
              <h3 className={styles.prepHeading}>Rounds</h3>
              <InterviewsField rounds={rounds} interviewTypes={interviewTypes}
                               onAdd={onAddInterview} onDelete={onDeleteInterview}
                               confirm={confirm} />
            </section>
          </Panel>
        </div>

        <StatusRail job={job} rounds={rounds}
                    onSetStatus={(s) => onSaveField("status", s)}
                    onSaveNotes={save("notes")} />
      </div>

      {/* Destructive, so it is always visible and never prominent. Behind a tab
          it would be both hidden and hunted for. */}
      <footer className={styles.footer}>
        <button type="button" className={styles.delete} onClick={() => void onDelete()}>
          Delete this job
        </button>
      </footer>
    </article>
  );
}

function Panel({ name, active, children }: {
  name: TabName; active: TabName; children: React.ReactNode;
}) {
  const seen = useRef(false);
  if (active === name) seen.current = true;
  if (!seen.current) return null;
  return (
    <div role="tabpanel" id={`panel-${name}`} aria-labelledby={`tab-${name}`}
         hidden={active !== name} className={styles.panel}>
      {children}
    </div>
  );
}

export { TABS };
