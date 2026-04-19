import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PhaseList } from "../PhaseList";
import type { Phase, StepRecord } from "../../lib/types";

const makeStep = (step: number, description: string, elapsed_ms = 100): StepRecord => ({
  step,
  description,
  elapsed_ms,
});

const makePhase = (overrides: Partial<Phase> = {}): Phase => ({
  name: "Test Phase",
  steps: [],
  total_ms: 500,
  failed: false,
  slow: false,
  ...overrides,
});

describe("PhaseList", () => {
  it("renders phase names", () => {
    const phases = [
      makePhase({ name: "Navigate to product" }),
      makePhase({ name: "Add to cart" }),
    ];
    render(<PhaseList phases={phases} steps={[]} />);
    expect(screen.getByText("Navigate to product")).toBeInTheDocument();
    expect(screen.getByText("Add to cart")).toBeInTheDocument();
  });

  it("renders steps list when phases array is empty", () => {
    const steps = [
      makeStep(1, "Opened the page"),
      makeStep(2, "Clicked submit"),
    ];
    render(<PhaseList phases={[]} steps={steps} />);
    expect(screen.getByText("Opened the page")).toBeInTheDocument();
    expect(screen.getByText("Clicked submit")).toBeInTheDocument();
    expect(screen.getByText("All Steps")).toBeInTheDocument();
  });

  it("renders empty steps section when both phases and steps are empty", () => {
    render(<PhaseList phases={[]} steps={[]} />);
    expect(screen.getByText("All Steps")).toBeInTheDocument();
  });

  it("expands phase on click to reveal its steps", () => {
    const steps = [makeStep(1, "Navigate to URL", 120)];
    const phases = [makePhase({ name: "Setup", steps: [1] })];
    render(<PhaseList phases={phases} steps={steps} />);

    // Step should not be visible before expanding
    expect(screen.queryByText("Navigate to URL")).not.toBeInTheDocument();

    // Click the phase button to expand
    fireEvent.click(screen.getByText("Setup"));
    expect(screen.getByText("Navigate to URL")).toBeInTheDocument();
  });

  it("collapses phase on second click", () => {
    const steps = [makeStep(1, "Navigate to URL", 120)];
    const phases = [makePhase({ name: "Setup", steps: [1] })];
    render(<PhaseList phases={phases} steps={steps} />);

    const phaseButton = screen.getByRole("button", { name: /setup/i });
    fireEvent.click(phaseButton);
    expect(screen.getByText("Navigate to URL")).toBeInTheDocument();

    fireEvent.click(phaseButton);
    expect(screen.queryByText("Navigate to URL")).not.toBeInTheDocument();
  });

  it("marks failed phases with red styling", () => {
    const phases = [makePhase({ name: "Checkout", failed: true })];
    render(<PhaseList phases={phases} steps={[]} />);
    const phaseName = screen.getByText("Checkout");
    expect(phaseName).toHaveClass("text-red-600");
  });

  it("marks slow phases with amber styling and warning prefix", () => {
    const phases = [makePhase({ name: "Search", slow: true })];
    render(<PhaseList phases={phases} steps={[]} />);
    // The phase name element contains "⚠ Search"
    const phaseName = screen.getByText(/Search/);
    expect(phaseName).toHaveClass("text-amber-600");
    expect(phaseName.textContent).toContain("⚠");
  });

  it("marks the last incomplete phase with amber styling", () => {
    const phases = [makePhase({ name: "Checkout" })];
    render(<PhaseList phases={phases} steps={[]} isLastPhaseIncomplete={true} />);
    const phaseName = screen.getByText(/Checkout/);
    expect(phaseName).toHaveClass("text-amber-600");
  });

  it("shows Phases section header when phases are provided", () => {
    const phases = [makePhase({ name: "Browse" })];
    render(<PhaseList phases={phases} steps={[]} />);
    expect(screen.getByText("Phases")).toBeInTheDocument();
  });
});
