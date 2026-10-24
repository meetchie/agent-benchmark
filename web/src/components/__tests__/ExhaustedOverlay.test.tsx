import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ExhaustedOverlay } from "../ExhaustedOverlay";

describe("ExhaustedOverlay", () => {
  it("shows the countdown until runs reset", () => {
    render(<ExhaustedOverlay resetsIn={3725} onClose={vi.fn()} />);
    expect(screen.getByText("01:02:05")).toBeInTheDocument();
  });

  it("has no external links or booking buttons", () => {
    render(<ExhaustedOverlay resetsIn={60} onClose={vi.fn()} />);
    expect(document.querySelector("a[href]")).toBeNull();
    expect(screen.queryByText(/book a demo/i)).not.toBeInTheDocument();
  });

  it("closes from the button, the backdrop and Escape", () => {
    const onClose = vi.fn();
    const { container } = render(<ExhaustedOverlay resetsIn={60} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(container.querySelector(".modal-backdrop")!);
    fireEvent.keyDown(window, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(3);
  });
});
