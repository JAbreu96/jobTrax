import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { StatusField } from "../src/components/shared/StatusField";
import type { JobStatus } from "../src/api/types";

const OPTIONS: JobStatus[] = ["", "Tracking", "Applied", "Phone Screen", "Rejected"];

describe("StatusField", () => {
  it("renders the current value as the selected option", () => {
    render(<StatusField value="Applied" options={OPTIONS} onSave={vi.fn()} />);
    expect(screen.getByTestId("status-select")).toHaveValue("Applied");
  });

  it("renders every option, including the blank/unset one", () => {
    render(<StatusField value="" options={OPTIONS} onSave={vi.fn()} />);
    expect(screen.getAllByRole("option")).toHaveLength(OPTIONS.length);
  });

  it("calls onSave with the new value when changed", () => {
    const onSave = vi.fn();
    render(<StatusField value="Tracking" options={OPTIONS} onSave={onSave} />);
    fireEvent.change(screen.getByTestId("status-select"), { target: { value: "Applied" } });
    expect(onSave).toHaveBeenCalledWith("Applied");
  });

  it("does not call onSave when the selected value is unchanged", () => {
    const onSave = vi.fn();
    render(<StatusField value="Applied" options={OPTIONS} onSave={onSave} />);
    fireEvent.change(screen.getByTestId("status-select"), { target: { value: "Applied" } });
    expect(onSave).not.toHaveBeenCalled();
  });

  it("uses a custom label when one is provided", () => {
    render(<StatusField label="Job Status" value="" options={OPTIONS} onSave={vi.fn()} />);
    expect(screen.getByText("Job Status")).toBeInTheDocument();
  });
});
