import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MarkdownField } from "../src/components/shared/MarkdownField";

/*
 * jsdom does no layout: scrollHeight/clientHeight are always 0 on every
 * element (see tests/js/dom_stub.js's comment on the same fact for the
 * legacy suite, and setupTests.ts's ResizeObserver stub). That means the
 * original vanilla-JS checkMarkdownOverflow was never actually exercised by
 * a real overflow condition in any existing test -- an assertion that just
 * renders long text and expects a button would pass or fail for reasons
 * unrelated to the measurement logic. To test overflow for real we stub the
 * two properties directly on the rendered node.
 */
function stubMeasurements(el: Element, scrollHeight: number, clientHeight: number) {
  Object.defineProperty(el, "scrollHeight", { configurable: true, value: scrollHeight });
  Object.defineProperty(el, "clientHeight", { configurable: true, value: clientHeight });
}

describe("MarkdownField", () => {
  it("shows no expand button when the content fits", () => {
    const { rerender } = render(<MarkdownField label="Notes" value="a" />);
    const rendered = screen.getByTestId("markdown-rendered");
    stubMeasurements(rendered, 40, 40);
    // Changing `value` re-triggers the measurement effect (see the
    // component's useLayoutEffect dependency array) against the stubbed
    // dimensions -- scrollHeight === clientHeight means "fits".
    rerender(<MarkdownField label="Notes" value="a short note that fits" />);
    expect(screen.queryByRole("button", { name: /show more/i })).toBeNull();
  });

  it("shows the expand button when the content overflows", () => {
    const { rerender } = render(<MarkdownField label="Notes" value="a" />);
    const rendered = screen.getByTestId("markdown-rendered");
    stubMeasurements(rendered, 200, 60);
    // Changing `value` re-triggers the measurement effect (see the
    // component's useLayoutEffect dependency array).
    rerender(<MarkdownField label="Notes" value="a very long note that overflows" />);
    expect(screen.getByRole("button", { name: /show more/i })).toBeInTheDocument();
  });

  it("toggles Show more <-> Show less and the expanded class on click", () => {
    const { rerender } = render(<MarkdownField label="Notes" value="a" />);
    const rendered = screen.getByTestId("markdown-rendered");
    stubMeasurements(rendered, 200, 60);
    rerender(<MarkdownField label="Notes" value="a very long note that overflows" />);

    const toggle = screen.getByRole("button", { name: /show more/i });
    expect(rendered.className).not.toMatch(/expanded/);

    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: /show less/i })).toBeInTheDocument();
    expect(screen.getByTestId("markdown-rendered").className).toMatch(/expanded/);

    fireEvent.click(screen.getByRole("button", { name: /show less/i }));
    expect(screen.getByRole("button", { name: /show more/i })).toBeInTheDocument();
  });

  it("Edit swaps the rendered view for a textarea carrying the raw source", () => {
    render(<MarkdownField label="Notes" value="**raw** markdown source" />);
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    const textarea = screen.getByTestId("markdown-textarea") as HTMLTextAreaElement;
    expect(textarea.value).toBe("**raw** markdown source");
    expect(screen.queryByTestId("markdown-rendered")).toBeNull();
  });

  it("does NOT call onSave on blur when the value is unchanged", () => {
    const onSave = vi.fn();
    render(<MarkdownField label="Notes" value="unchanged" onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    const textarea = screen.getByTestId("markdown-textarea");
    fireEvent.blur(textarea);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("calls onSave with the trimmed value on blur when it changed", () => {
    const onSave = vi.fn();
    render(<MarkdownField label="Notes" value="old value" onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    const textarea = screen.getByTestId("markdown-textarea");
    fireEvent.change(textarea, { target: { value: "  new value  " } });
    fireEvent.blur(textarea);
    expect(onSave).toHaveBeenCalledWith("new value");
  });

  it("returns to the rendered view after blur", () => {
    render(<MarkdownField label="Notes" value="old" />);
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    fireEvent.blur(screen.getByTestId("markdown-textarea"));
    expect(screen.getByTestId("markdown-rendered")).toBeInTheDocument();
  });
});
