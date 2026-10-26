import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StepLog } from "../StepLog";

// jsdom has neither ResizeObserver nor element scrolling.
beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollTo = vi.fn() as unknown as typeof Element.prototype.scrollTo;
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("StepLog before the first step", () => {
  it("says what the run is doing when the backend says", () => {
    render(<StepLog steps={[]} isRunning startingLabel="Starting the browser" />);
    expect(screen.getByText("Starting the browser…")).toBeInTheDocument();
  });

  it("keeps the generic line when it does not", () => {
    render(<StepLog steps={[]} isRunning />);
    expect(screen.getByText("Starting agent...")).toBeInTheDocument();
  });

  it("lists the steps once there are some", () => {
    render(<StepLog steps={[{ step: 1, description: "Open Products", elapsed_ms: 4200 }]} isRunning startingLabel="Deciding step 2" />);
    expect(screen.getByText("Open Products")).toBeInTheDocument();
    expect(screen.queryByText("Deciding step 2…")).not.toBeInTheDocument();
  });
});
