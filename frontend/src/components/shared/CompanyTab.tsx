/*
 * The company research notebook.
 *
 * What it is NOT: a "Research this company" button. Flask cannot invoke a
 * Claude skill, so a button here could only ever spin. Claude writes the
 * sections through the MCP tool set_company_profile when asked to; this tab
 * reads them and lets you correct anything that is wrong. The empty state says
 * so out loud, because a blank tab with no explanation reads as broken.
 *
 * Sections are fixed, not freeform. Six headings that are the same on every
 * company are what makes two profiles comparable the night before an
 * interview -- and what lets the research skill fill them without inventing a
 * structure per employer.
 */
import { MarkdownField } from "./MarkdownField";
import { COMPANY_SECTIONS, type CompanyProfile, type CompanySection } from "../../api/types";
import styles from "./CompanyTab.module.css";

const HEADINGS: Record<CompanySection, string> = {
  about: "About",
  product: "Product",
  team: "Team",
  funding: "Funding",
  recent_news: "Recent news",
  why_me: "Why me",
};

// Shown in place of an empty section, so the gap between "nothing is known"
// and "nothing was worth writing" is visible rather than guessed at. These go
// through MarkdownField's `placeholder` rather than being rendered beside it:
// its own empty state is the literal string "(empty)", and both at once read
// as a rendering fault.
const PROMPTS: Record<CompanySection, string> = {
  about: "What the company is, its stage, its market.",
  product: "What they build, and how it works.",
  team: "Founders, the hiring team, anyone you have spoken to.",
  funding: "Rounds, investors, amounts, dates.",
  recent_news: "Launches, raises, press from the last few months.",
  why_me: "The honest case for you at this company.",
};

export interface CompanyTabProps {
  company: string;
  profile: CompanyProfile | null;
  isLoading?: boolean;
  onSaveSection: (field: CompanySection | "website", value: string) => void | Promise<unknown>;
}

export function CompanyTab({ company, profile, isLoading, onSaveSection }: CompanyTabProps) {
  if (isLoading) return <p className={styles.state}>Loading research…</p>;

  const researched = profile?.researched_at || "";
  const anything = COMPANY_SECTIONS.some((s) => (profile?.[s] || "").trim());

  return (
    <div className={styles.notebook}>
      <header className={styles.meta}>
        <div>
          <h2 className={styles.companyName}>{profile?.display_name || company}</h2>
          {researched
            ? <p className={styles.researched}>Researched {researched}</p>
            : <p className={styles.researched}>Not researched yet</p>}
        </div>
        {profile?.website && (
          <a className={styles.website} href={profile.website}
             target="_blank" rel="noreferrer">
            {hostOf(profile.website)} ↗
          </a>
        )}
      </header>

      {!anything && (
        <p className={styles.empty}>
          Nothing stored for {company} yet. Ask Claude to research this company
          and it will fill these sections — or write them yourself, they are all
          editable.
        </p>
      )}

      {COMPANY_SECTIONS.map((section) => (
        <section key={section} className={styles.section}>
          {/* expandable={false}: unclamped. Six sections each clipped to three
              lines behind its own "Show more" is six clicks to read one page,
              which is the opposite of the thing this view was built for. The
              sections are short by construction -- fixed prompts, one topic
              each -- and the panel scrolls. */}
          <MarkdownField label={HEADINGS[section]} labelAs="h3"
                         value={profile?.[section] || ""}
                         expandable={false} fieldClass={styles.prose}
                         placeholder={PROMPTS[section]}
                         onSave={(value) => { void onSaveSection(section, value); }} />
        </section>
      ))}
    </div>
  );
}

/** Bare host for display, falling back to the raw string when it will not
 *  parse -- a half-typed URL should still show what was typed. */
function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}
