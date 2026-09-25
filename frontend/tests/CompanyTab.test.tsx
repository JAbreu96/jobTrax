/*
 * The company research notebook.
 *
 * The cases worth pinning are the ones about what an *unwritten* profile looks
 * like. A company nobody has researched is the normal state for almost every
 * row in the tracker -- 1,314 jobs, and this table starts empty -- so the empty
 * rendering is the one most people will see most often, and a blank panel would
 * read as a bug.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CompanyTab } from "../src/components/shared/CompanyTab";
import { COMPANY_SECTIONS, type CompanyProfile } from "../src/api/types";

function makeProfile(overrides: Partial<CompanyProfile> = {}): CompanyProfile {
  return {
    company_key: "physical intelligence",
    display_name: "Physical Intelligence",
    about: "", product: "", team: "", funding: "", recent_news: "", why_me: "",
    website: "", researched_at: "", updated_at: "2026-09-25",
    ...overrides,
  };
}

function renderTab(profile: CompanyProfile | null, company = "Physical Intelligence") {
  const onSaveSection = vi.fn();
  render(<CompanyTab company={company} profile={profile}
                     onSaveSection={onSaveSection} />);
  return { onSaveSection };
}

describe("CompanyTab", () => {
  it("renders every section even when the profile is empty", () => {
    // All six headings, always. A notebook that hides its blank pages gives no
    // hint what research is supposed to cover.
    renderTab(null);

    for (const heading of ["About", "Product", "Team", "Funding",
                           "Recent news", "Why me"]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
  });

  it("prompts what belongs in an empty section instead of showing '(empty)'", () => {
    // parseMarkdown renders blank input as the literal "(empty)", which is
    // right for a field that is normally filled and wrong for six that start
    // that way -- six "(empty)" lines read as a broken tab.
    renderTab(null);

    expect(screen.getByText("Rounds, investors, amounts, dates.")).toBeInTheDocument();
    expect(screen.queryByText("(empty)")).toBeNull();
  });

  it("says how to fill an unresearched company rather than showing a blank tab", () => {
    renderTab(null);

    expect(screen.getByText(/Ask Claude to research this company/))
      .toBeInTheDocument();
    expect(screen.getByText("Not researched yet")).toBeInTheDocument();
  });

  it("falls back to the job's company name when no profile row exists", () => {
    renderTab(null, "Turing");

    expect(screen.getByRole("heading", { name: "Turing" })).toBeInTheDocument();
  });

  it("drops the empty-state notice once any section has content", () => {
    renderTab(makeProfile({ about: "An embodied AI lab." }));

    expect(screen.queryByText(/Ask Claude to research this company/)).toBeNull();
    expect(screen.getByText("An embodied AI lab.")).toBeInTheDocument();
  });

  it("shows when the research was last refreshed", () => {
    renderTab(makeProfile({ about: "x", researched_at: "2026-09-20" }));

    expect(screen.getByText("Researched 2026-09-20")).toBeInTheDocument();
  });

  it("saves the section that was edited, not the whole profile", async () => {
    // The write path is per-section on purpose: the research skill and a hand
    // edit routinely touch different sections minutes apart, and a whole-row
    // save would make each clobber the other.
    const { onSaveSection } = renderTab(makeProfile({ about: "Old text" }));

    const edit = screen.getAllByRole("button", { name: /edit/i })[0];
    await userEvent.click(edit);
    const box = screen.getByRole("textbox");
    await userEvent.clear(box);
    await userEvent.type(box, "New text");
    await userEvent.tab();

    expect(onSaveSection).toHaveBeenCalledWith("about", "New text");
  });

  it("shows the website as a bare host, not the raw URL", () => {
    renderTab(makeProfile({ about: "x", website: "https://www.example.com/careers" }));

    expect(screen.getByRole("link", { name: /example\.com/ }))
      .toHaveAttribute("href", "https://www.example.com/careers");
  });

  it("shows an unparseable website string as typed instead of throwing", () => {
    // Hand-edited field; a half-typed URL must not take the tab down with it.
    renderTab(makeProfile({ about: "x", website: "example dot com" }));

    expect(screen.getByRole("link", { name: /example dot com/ })).toBeInTheDocument();
  });

  it("keeps the rendered order stable so two companies read the same way", () => {
    renderTab(makeProfile({ about: "x" }));

    const headings = screen.getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent);
    expect(headings).toEqual(
      ["About", "Product", "Team", "Funding", "Recent news", "Why me"]);
    expect(headings).toHaveLength(COMPANY_SECTIONS.length);
  });
});
