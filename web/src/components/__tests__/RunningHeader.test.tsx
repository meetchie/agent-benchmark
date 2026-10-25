import { fireEvent, render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { RunningHeader } from "../RunningHeader";

const baseProps = {
  isRunning: true,
  elapsedMs: 1000,
  onNewTest: vi.fn(),
};

describe("RunningHeader cancel dialog", () => {
  it("warns that the tokens used so far are still billed and kept in the run record", () => {
    render(<RunningHeader {...baseProps} />);
    fireEvent.click(screen.getByRole("button", { name: "New Test" }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Cancel this run?");
    expect(dialog).toHaveTextContent("If you leave now, you won't see the results.");
    expect(dialog).toHaveTextContent("Tokens already used are still billed and kept in the run record.");
  });

  it("says nothing about billing in demo mode, where no model is called", () => {
    render(<RunningHeader {...baseProps} demoMode />);
    fireEvent.click(screen.getByRole("button", { name: "New Test" }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("you won't see the results");
    expect(dialog).not.toHaveTextContent(/billed/);
  });

  it("asks nothing once the run is over", () => {
    const onNewTest = vi.fn();
    render(<RunningHeader {...baseProps} isRunning={false} onNewTest={onNewTest} />);
    fireEvent.click(screen.getByRole("button", { name: "New Test" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onNewTest).toHaveBeenCalledTimes(1);
  });

  it("leaves only after Cancel Run is pressed", () => {
    const onNewTest = vi.fn();
    render(<RunningHeader {...baseProps} onNewTest={onNewTest} />);
    fireEvent.click(screen.getByRole("button", { name: "New Test" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep Running" }));
    expect(onNewTest).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "New Test" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel Run" }));
    expect(onNewTest).toHaveBeenCalledTimes(1);
  });
});
