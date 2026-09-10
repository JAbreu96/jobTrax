import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DetailField } from "../src/components/shared/DetailField";

describe("DetailField", () => {
  it("does not save on blur when the text did not change", () => {
    const onSave = vi.fn();
    render(<DetailField label="Location" value="Remote" onSave={onSave} />);
    fireEvent.blur(screen.getByTestId("detail-editable"));
    expect(onSave).not.toHaveBeenCalled();
  });

  it("saves the trimmed text on blur when it changed", () => {
    const onSave = vi.fn();
    render(<DetailField label="Location" value="Remote" onSave={onSave} />);
    const el = screen.getByTestId("detail-editable");
    el.textContent = "  NYC  ";
    fireEvent.blur(el);
    expect(onSave).toHaveBeenCalledWith("NYC");
  });

  it("reverts to the last-known value and notifies on a failed save", async () => {
    const onSave = vi.fn().mockRejectedValue(new Error("could not save"));
    const notify = vi.fn();
    render(<DetailField label="Location" value="Remote" onSave={onSave} notify={notify} />);
    const el = screen.getByTestId("detail-editable");
    el.textContent = "NYC";
    fireEvent.blur(el);

    await vi.waitFor(() => expect(notify).toHaveBeenCalledWith("could not save"));
    expect(el.textContent).toBe("Remote");
  });
});
