import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FollowupField } from "../src/components/shared/FollowupField";
import { parseFollowupLog, serializeFollowupLog } from "../src/lib/jobFields";

describe("FollowupField", () => {
  it("renders a chip for each token in the followup log", () => {
    render(<FollowupField label="Follow-ups" value="2026-01-01, 2026-02-02" onSave={vi.fn()} />);
    expect(screen.getByText("2026-01-01")).toBeInTheDocument();
    expect(screen.getByText("2026-02-02")).toBeInTheDocument();
  });

  it("adds a chip and round-trips through parse/serializeFollowupLog", () => {
    const onSave = vi.fn();
    render(<FollowupField label="Follow-ups" value="2026-01-01" onSave={onSave} />);

    fireEvent.change(screen.getByLabelText(/follow-ups date/i), {
      target: { value: "2026-03-03" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    const expected = serializeFollowupLog([...parseFollowupLog("2026-01-01"), "2026-03-03"]);
    expect(onSave).toHaveBeenCalledWith(expected);
  });

  it("removes a chip via its remove button", () => {
    const onSave = vi.fn();
    render(<FollowupField label="Follow-ups" value="2026-01-01, 2026-02-02" onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: /remove 2026-01-01/i }));
    expect(onSave).toHaveBeenCalledWith("2026-02-02");
  });

  it("disables Add once the two-followup cap is reached", () => {
    render(<FollowupField label="Follow-ups" value="2026-01-01, 2026-02-02" onSave={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });
});
