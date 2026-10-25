import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { RunningView } from "../RunningView";
import type { StepRecord, SummaryData } from "../../lib/types";

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

  describe("cost and agent model", () => {
    const finished = (overrides: Partial<SummaryData> = {}) =>
      render(
        <RunningView
          {...defaultProps}
          isRunning={false}
          summary={{ ...makeSummary(), ...overrides }}
          steps={[makeStep(1), makeStep(2)]}
        />
      );

    it("shows the backend's cost_usd and the agent model", () => {
      finished({ cost_usd: 0.0423, agent_model: "claude-sonnet-5-5" });
      expect(screen.getAllByText("$0.04").length).toBeGreaterThan(0);
      expect(screen.getAllByText("claude-sonnet-5-5").length).toBeGreaterThan(0);
    });

    it("does not recompute the cost from the token counts", () => {
      // 8,000 input + 2,000 output tokens at the old GPT-4o rates would be $0.04.
      finished({ cost_usd: 2.5 });
      expect(screen.getAllByText("$2.50").length).toBeGreaterThan(0);
      expect(screen.queryByText("$0.04")).not.toBeInTheDocument();
    });

    it("shows tokens only when cost_usd is null", () => {
      finished({ cost_usd: null, agent_model: "some-unpriced-model" });
      expect(screen.queryByText("Cost")).not.toBeInTheDocument();
      expect(screen.getAllByText("10,000").length).toBeGreaterThan(0);
      expect(document.body.textContent).not.toMatch(/\$/);
    });

    it("explains in the agent card why there is no cost", () => {
      finished({ cost_usd: null, agent_model: "some-unpriced-model" });
      for (const card of screen.getAllByTestId("agent-card")) {
        expect(card).toHaveTextContent("some-unpriced-model");
        expect(card).toHaveTextContent(/no per-token rate/);
      }
    });

    it("shows tokens only when cost_usd is absent from the payload", () => {
      finished();
      expect(screen.queryByText("Cost")).not.toBeInTheDocument();
      expect(screen.getAllByText("10,000").length).toBeGreaterThan(0);
      expect(document.body.textContent).not.toMatch(/\$/);
    });

    it("shows a placeholder, not an estimate, while the run is in progress", () => {
      render(<RunningView {...defaultProps} steps={[makeStep(1), makeStep(2)]} />);
      expect(screen.getAllByText("Cost").length).toBeGreaterThan(0);
      expect(document.body.textContent).not.toMatch(/\$/);
      // The stats block renders once per layout (desktop and mobile).
      for (const card of screen.getAllByTestId("agent-card")) {
        expect(card).toHaveTextContent("Reported when the run finishes");
      }
    });

    it("shows a placeholder for tokens too while the run is in progress, never a step-count guess", () => {
      // The old estimate was steps x 3000 shown as "~N" (here "~6,000"); it read about 7x low.
      render(<RunningView {...defaultProps} steps={[makeStep(1), makeStep(2)]} />);
      const tokenCells = screen.getAllByText("Tokens").map((label) => label.parentElement);
      expect(tokenCells.length).toBeGreaterThan(0);
      for (const cell of tokenCells) expect(cell).toHaveTextContent(/^Tokens\s*—$/);
      expect(document.body.textContent).not.toMatch(/~/);
      expect(document.body.textContent).not.toMatch(/6,000/);
    });

    it("shows the backend's real token total once the judge phase reports it", () => {
      render(
        <RunningView
          {...defaultProps}
          isRunning={false}
          isAnalyzing
          analyzingStats={{ total_ms: 4000, input_tokens: 41000, output_tokens: 2500, total_tokens: 43500, cost_usd: null }}
          steps={[makeStep(1), makeStep(2)]}
        />
      );
      expect(screen.getAllByText("43,500").length).toBeGreaterThan(0);
      expect(document.body.textContent).not.toMatch(/~/);
    });

    it("shows cost and model as soon as the judge phase reports them", () => {
      render(
        <RunningView
          {...defaultProps}
          isRunning={false}
          isAnalyzing
          analyzingStats={{
            total_ms: 4000,
            input_tokens: 5000,
            output_tokens: 500,
            total_tokens: 5500,
            cost_usd: 0.015,
            agent_model: "claude-haiku-5-5",
          }}
          steps={[makeStep(1)]}
        />
      );
      expect(screen.getAllByText("$0.01").length).toBeGreaterThan(0);
      for (const card of screen.getAllByTestId("agent-card")) {
        expect(card).toHaveTextContent("claude-haiku-5-5");
      }
    });
  });

  describe("demo mode", () => {
    it("shows a persistent banner when the backend plays canned runs", () => {
      render(<RunningView {...defaultProps} demoMode />);
      expect(screen.getByTestId("demo-banner")).toHaveTextContent(
        "Demo mode: canned runs, no real agent or API calls"
      );
    });

    it("keeps the banner after the run finishes", () => {
      render(<RunningView {...defaultProps} demoMode isRunning={false} summary={makeSummary()} steps={[makeStep(1)]} />);
      expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
    });

    it("shows no banner against a real backend", () => {
      render(<RunningView {...defaultProps} />);
      expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();
    });
  });

  it("has no external links or booking buttons", () => {
    render(<RunningView {...defaultProps} />);
    expect(document.querySelector("a[href]")).toBeNull();
    expect(screen.queryByText(/book a demo/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/agent-accessible/i)).not.toBeInTheDocument();
  });
});
