import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DateField } from "../src/components/shared/DateField";

describe("DateField", () => {
  it("renders an ISO date value directly in the input", () => {
    render(<DateField label="Applied" value="2026-03-01" onSave={vi.fn()} />);
    const input = screen.getByTestId("date-input") as HTMLInputElement;
    expect(input.value).toBe("2026-03-01");
  });

  it("calls onSave with the new value when the date input changes", () => {
    const onSave = vi.fn();
    render(<DateField label="Applied" value="" onSave={onSave} />);
    fireEvent.change(screen.getByTestId("date-input"), { target: { value: "2026-04-05" } });
    expect(onSave).toHaveBeenCalledWith("2026-04-05");
  });

  it("shows the legacy non-ISO value as text with a Replace with date opt-in", () => {
    render(<DateField label="Outreach" value="emailed Tuesday" onSave={vi.fn()} />);
    expect(screen.getByTestId("date-legacy-value")).toHaveTextContent("emailed Tuesday");
    expect(screen.queryByTestId("date-input")).toBeNull();
  });

  it("swaps the legacy value for a real date input after Replace with date", () => {
    render(<DateField label="Outreach" value="emailed Tuesday" onSave={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /replace with date/i }));
    expect(screen.getByTestId("date-input")).toBeInTheDocument();
    expect(screen.queryByTestId("date-legacy-value")).toBeNull();
  });
});
