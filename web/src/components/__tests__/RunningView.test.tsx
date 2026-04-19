import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { RunningView } from "../RunningView";
import type { StepRecord, SummaryData } from "../../lib/types";

// DemoModal uses @calcom/embed-react which is a DOM-heavy external dependency.
vi.mock("../DemoModal", () => ({
  DemoModal: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// ResultsOverlay is complex and tested separately; mock it to a lightweight stub.
vi.mock("../ResultsOverlay", () => ({
  ResultsOverlay: () => <div data-testid="results-overlay-mock">ResultsOverlay</div>,
}));

// StepLog uses ResizeObserver which is not available in jsdom.
vi.mock("../StepLog", () => ({
  StepLog: () => <div data-testid="step-log-mock" />,
}));

// RunningHeader is simple enough to render for real — no mocking needed.

const makeStep = (step: number, description = "Click button", elapsed_ms = 200): StepRecord => ({
  step,
  description,
  elapsed_ms,
});

const makeSummary = (): SummaryData => ({
  success: true,
  summary: "Task completed.",
  result_state: "pass",
  total_ms: 8000,
  input_tokens: 8000,
  output_tokens: 2000,
  total_tokens: 10000,
  phases: [],
});

const defaultProps = {
  url: "https://www.shipt.com",
  taskLabel: "Search groceries",
  isRunning: true,
  isAnalyzing: false,
  analyzingStats: null,
  steps: [],
  screenshot: null,
  summary: null,
  errorMsg: null,
  onRunAgain: vi.fn(),
  onNewTest: vi.fn(),
};

describe("RunningView", () => {
  it("renders without crashing", () => {
    render(<RunningView {...defaultProps} />);
    // The running view should mount with no errors
    expect(document.body).toBeTruthy();
  });

  it("shows a spinner when no screenshot is available", () => {
    render(<RunningView {...defaultProps} screenshot={null} />);
    // SVG spinners are present; check there is at least one spin animation element
    const spinners = document.querySelectorAll(".animate-spin");
    expect(spinners.length).toBeGreaterThan(0);
  });

  it("shows a screenshot image when screenshot is provided", () => {
    render(<RunningView {...defaultProps} screenshot="data:image/png;base64,abc" />);
    // RunningView renders both desktop and mobile layouts, so there are two img elements.
    const imgs = screen.getAllByAltText("Agent screenshot");
    expect(imgs.length).toBeGreaterThan(0);
    expect(imgs[0]).toHaveAttribute("src", "data:image/png;base64,abc");
  });

  it("shows 'Benchmark complete' banner and ResultsOverlay when summary is provided", () => {
    const summary = makeSummary();
    render(
      <RunningView
        {...defaultProps}
        isRunning={false}
        isAnalyzing={false}
        summary={summary}
        steps={[makeStep(1)]}
      />
    );
    // Desktop + mobile both render the banner, so use getAllByText
    const banners = screen.getAllByText("Benchmark complete");
    expect(banners.length).toBeGreaterThan(0);
    expect(screen.getByTestId("results-overlay-mock")).toBeInTheDocument();
  });

  it("shows 'Benchmark complete' banner when errorMsg is present and run is done", () => {
    render(
      <RunningView
        {...defaultProps}
        isRunning={false}
        isAnalyzing={false}
        errorMsg="Something went wrong"
        steps={[]}
      />
    );
    const banners = screen.getAllByText("Benchmark complete");
    expect(banners.length).toBeGreaterThan(0);
  });

  it("does not show ResultsOverlay while actively running", () => {
    render(
      <RunningView
        {...defaultProps}
        isRunning={true}
        isAnalyzing={false}
        summary={null}
        errorMsg={null}
      />
    );
    expect(screen.queryByTestId("results-overlay-mock")).not.toBeInTheDocument();
  });

  it("shows steps count in completed banner", () => {
    const summary = makeSummary();
    render(
      <RunningView
        {...defaultProps}
        isRunning={false}
        summary={summary}
        steps={[makeStep(1), makeStep(2), makeStep(3)]}
      />
    );
    // Desktop + mobile both render the step count; use getAllByText
    const stepCountEls = screen.getAllByText(/3 steps/);
    expect(stepCountEls.length).toBeGreaterThan(0);
  });

  it("renders CTA content promoting Rindler", () => {
    render(<RunningView {...defaultProps} />);
    expect(screen.getAllByText(/Make your site agent-accessible/).length).toBeGreaterThan(0);
  });
});
