import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ResultsOverlay } from "../ResultsOverlay";
import type { SummaryData, StepRecord } from "../../lib/types";

// DemoModal uses @calcom/embed-react which is a DOM-heavy external dependency.
// Mock it to a simple passthrough wrapper.
vi.mock("../DemoModal", () => ({
  DemoModal: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const makeStep = (step: number, description = "Step description", elapsed_ms = 100): StepRecord => ({
  step,
  description,
  elapsed_ms,
});

const makeSummary = (overrides: Partial<SummaryData> = {}): SummaryData => ({
  success: true,
  summary: "The agent completed the task successfully.",
  result_state: "pass",
  total_ms: 12000,
  input_tokens: 10000,
  output_tokens: 2000,
  total_tokens: 12000,
  phases: [],
  ...overrides,
});

const defaultProps = {
  url: "https://www.example.com/shop",
  taskLabel: "Search for shoes",
  summary: null,
  errorMsg: null,
  steps: [],
  isAnalyzing: false,
  analyzingStats: null,
  onClose: vi.fn(),
  onRunAgain: vi.fn(),
  onNewTest: vi.fn(),
};

describe("ResultsOverlay", () => {
  it("renders without crashing", () => {
    render(<ResultsOverlay {...defaultProps} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("shows Benchmark Result header", () => {
    render(<ResultsOverlay {...defaultProps} />);
    expect(screen.getByText("Benchmark Result")).toBeInTheDocument();
  });

  it("shows Pass result state", () => {
    const summary = makeSummary({ result_state: "pass" });
    render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
    expect(screen.getByText("Pass")).toBeInTheDocument();
  });

  it("shows Fail result state", () => {
    const summary = makeSummary({ result_state: "fail", success: false });
    render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
    expect(screen.getByText("Fail")).toBeInTheDocument();
  });

  it("shows Agent Too Slow result state", () => {
    const summary = makeSummary({ result_state: "too_slow", success: false });
    render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
    expect(screen.getByText("Agent Too Slow")).toBeInTheDocument();
  });

  it("shows error state when errorMsg is provided and no summary", () => {
    render(
      <ResultsOverlay
        {...defaultProps}
        errorMsg="Connection timed out"
        steps={[]}
      />
    );
    expect(screen.getByText("Error")).toBeInTheDocument();
    expect(screen.getByText("Connection timed out")).toBeInTheDocument();
  });

  it("shows summary text when result is pass", () => {
    const summary = makeSummary({
      result_state: "pass",
      summary: "Agent found shoes and added them to cart.",
    });
    render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
    expect(screen.getByText("Agent found shoes and added them to cart.")).toBeInTheDocument();
  });

  it("shows domain and task label in subtitle", () => {
    render(<ResultsOverlay {...defaultProps} />);
    expect(screen.getByText(/example\.com/)).toBeInTheDocument();
    expect(screen.getByText(/Search for shoes/)).toBeInTheDocument();
  });

  it("calls onClose when close button clicked", () => {
    const onClose = vi.fn();
    render(<ResultsOverlay {...defaultProps} onClose={onClose} />);
    // The close button is an SVG button; find it by its role
    const closeButtons = screen.getAllByRole("button");
    // First button in the header area is the close X button
    fireEvent.click(closeButtons[0]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when backdrop is clicked", () => {
    const onClose = vi.fn();
    render(<ResultsOverlay {...defaultProps} onClose={onClose} />);
    // The backdrop div has onClick={onClose}
    const backdrop = document.querySelector(".modal-backdrop") as HTMLElement;
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape key", () => {
    const onClose = vi.fn();
    render(<ResultsOverlay {...defaultProps} onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows Evaluating state when isAnalyzing=true", () => {
    render(<ResultsOverlay {...defaultProps} isAnalyzing={true} />);
    expect(screen.getByText("Evaluating...")).toBeInTheDocument();
  });

  it("shows Analyzing run spinner when isAnalyzing=true", () => {
    render(<ResultsOverlay {...defaultProps} isAnalyzing={true} />);
    expect(screen.getByText("Analyzing run...")).toBeInTheDocument();
  });

  it("calls onRunAgain when Run Again button clicked", () => {
    const onRunAgain = vi.fn();
    const summary = makeSummary();
    render(
      <ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} onRunAgain={onRunAgain} />
    );
    fireEvent.click(screen.getByText(/Run Again/));
    expect(onRunAgain).toHaveBeenCalledTimes(1);
  });

  it("calls onNewTest when New Test button clicked", () => {
    const onNewTest = vi.fn();
    const summary = makeSummary();
    render(
      <ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} onNewTest={onNewTest} />
    );
    fireEvent.click(screen.getByText("New Test"));
    expect(onNewTest).toHaveBeenCalledTimes(1);
  });

  it("shows stats when summary is provided", () => {
    const summary = makeSummary({ total_ms: 5000, total_tokens: 12000 });
    render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
    // Stats section should show Time, Steps, Tokens, Cost
    expect(screen.getByText("Time")).toBeInTheDocument();
    expect(screen.getByText("Steps")).toBeInTheDocument();
    expect(screen.getByText("Tokens")).toBeInTheDocument();
    expect(screen.getByText("Cost")).toBeInTheDocument();
  });

  it("shows no steps message for error with no steps", () => {
    render(
      <ResultsOverlay
        {...defaultProps}
        errorMsg="Server error"
        steps={[]}
      />
    );
    expect(screen.getByText("No steps were completed")).toBeInTheDocument();
  });
});
