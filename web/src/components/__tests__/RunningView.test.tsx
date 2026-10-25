import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
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

  describe("screenshot pane without a screenshot", () => {
    const NOTE = "No screenshot for this run";

    it("keeps the spinner and no note while the agent is working", () => {
      render(<RunningView {...defaultProps} />);
      expect(document.querySelectorAll(".animate-spin").length).toBeGreaterThan(0);
      expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
    });

    it("shows a calm note, not a spinner, once the run is complete", () => {
      render(<RunningView {...defaultProps} isRunning={false} summary={makeSummary()} steps={[makeStep(1)]} />);
      // Desktop and mobile each have a screenshot pane.
      expect(screen.getAllByText(NOTE)).toHaveLength(2);
      expect(document.querySelectorAll(".animate-spin")).toHaveLength(0);
    });

    it("shows the note, not a spinner, while the judge is analyzing", () => {
      render(
        <RunningView
          {...defaultProps}
          isRunning={false}
          isAnalyzing
          analyzingStats={{ total_ms: 4000, input_tokens: 5000, output_tokens: 500, total_tokens: 5500, cost_usd: null }}
          steps={[makeStep(1)]}
        />
      );
      expect(screen.getAllByText(NOTE)).toHaveLength(2);
      expect(document.querySelectorAll(".animate-spin")).toHaveLength(0);
    });

    it("shows the note, not a spinner, when the run ended in an error", () => {
      render(<RunningView {...defaultProps} isRunning={false} errorMsg="Something went wrong" />);
      expect(screen.getAllByText(NOTE)).toHaveLength(2);
      expect(document.querySelectorAll(".animate-spin")).toHaveLength(0);
    });

    it("shows the note in a finished demo run too", () => {
      render(<RunningView {...defaultProps} demoMode isRunning={false} summary={makeSummary()} steps={[makeStep(1)]} />);
      expect(screen.getAllByText(NOTE)).toHaveLength(2);
      expect(document.querySelectorAll(".animate-spin")).toHaveLength(0);
    });

    it("shows the picture, and no note, when there is a screenshot", () => {
      render(
        <RunningView
          {...defaultProps}
          isRunning={false}
          summary={makeSummary()}
          steps={[makeStep(1)]}
          screenshot="data:image/png;base64,abc"
        />
      );
      expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
      expect(screen.getAllByAltText("Agent screenshot").length).toBeGreaterThan(0);
    });
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

  it("does not call a run that ended in an error complete", () => {
    render(
      <RunningView
        {...defaultProps}
        isRunning={false}
        isAnalyzing={false}
        errorMsg="Something went wrong"
        steps={[]}
      />
    );
    expect(screen.getAllByText("Run ended in an error")).toHaveLength(2);
    expect(screen.queryByText("Benchmark complete")).not.toBeInTheDocument();
  });

  it("shows the backend's duration of an error run in the banner", () => {
    render(
      <RunningView
        {...defaultProps}
        isRunning={false}
        errorMsg="The agent could not complete a single step."
        analyzingStats={{ total_ms: 7532, input_tokens: 0, output_tokens: 0, total_tokens: 0, cost_usd: 0 }}
        steps={[makeStep(1), makeStep(2), makeStep(3)]}
      />
    );
    expect(screen.getAllByText("3 steps · 0:07")).toHaveLength(2);
  });

  it("keeps 'Benchmark complete' for an error run the judge read", () => {
    render(
      <RunningView
        {...defaultProps}
        isRunning={false}
        summary={{ ...makeSummary(), success: false, result_state: "error" }}
        errorMsg="The agent model declined to continue this task (safety refusal)."
        steps={[makeStep(1)]}
      />
    );
    expect(screen.getAllByText("Benchmark complete")).toHaveLength(2);
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

    // Every Tokens cell (the stats render once per layout and screen size) shows `value`.
    const expectEveryTokenCell = (value: string) => {
      const values = screen.getAllByText("Tokens").map((label) => label.nextElementSibling?.textContent);
      expect(values.length).toBeGreaterThan(0);
      expect(values).toEqual(values.map(() => value));
    };

    // total_tokens includes the cache writes, which input_tokens + output_tokens leaves
    // out, so the next two fixtures make it larger than that sum (41,000 + 2,500 = 43,500).
    it("shows the backend's real token total once the judge phase reports it", () => {
      render(
        <RunningView
          {...defaultProps}
          isRunning={false}
          isAnalyzing
          analyzingStats={{ total_ms: 4000, input_tokens: 41000, output_tokens: 2500, total_tokens: 50000, cost_usd: null }}
          steps={[makeStep(1), makeStep(2)]}
        />
      );
      expectEveryTokenCell("50,000");
      expect(document.body.textContent).not.toMatch(/43,500/);
      expect(document.body.textContent).not.toMatch(/~/);
    });

    it("shows the finished run's total_tokens, cache writes included, not input + output", () => {
      // Real run 21df242f: input 227,454 + cache writes 18,638 + output 3,053 = 249,145.
      finished({ input_tokens: 227454, output_tokens: 3053, total_tokens: 249145, cost_usd: 0.9 });
      expectEveryTokenCell("249,145");
      expect(document.body.textContent).not.toMatch(/230,507/);
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

    it("shows tokens only, and says why, for a canned run with no cost", () => {
      render(
        <RunningView
          {...defaultProps}
          demoMode
          isRunning={false}
          summary={{ ...makeSummary(), cost_usd: null, agent_model: "claude-sonnet-5-5" }}
          steps={[makeStep(1)]}
        />
      );
      expect(screen.queryByText("Cost")).not.toBeInTheDocument();
      expect(screen.getAllByText("10,000").length).toBeGreaterThan(0);
      expect(document.body.textContent).not.toMatch(/\$/);
      for (const card of screen.getAllByTestId("agent-card")) {
        expect(card).toHaveTextContent(/no model was called/);
        expect(card).not.toHaveTextContent(/per-token rate/);
      }
    });

    it("shows no banner against a real backend", () => {
      render(<RunningView {...defaultProps} />);
      expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();
    });
  });

  describe("clock", () => {
    // The Time cell of every layout.
    const timeCells = () => screen.getAllByText("Time").map((label) => label.nextElementSibling?.textContent);
    const tick = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });

    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("counts while the agent works", () => {
      render(<RunningView {...defaultProps} steps={[makeStep(1)]} />);
      tick(3000);
      expect(timeCells()).toEqual(timeCells().map(() => "0:03"));
    });

    it("starts when the first poll already brings several steps", () => {
      render(<RunningView {...defaultProps} steps={[makeStep(1), makeStep(2)]} />);
      tick(3000);
      expect(timeCells()).toEqual(timeCells().map(() => "0:03"));
    });

    it("stops where it was when the run ends in an error with no duration", () => {
      const { rerender } = render(<RunningView {...defaultProps} steps={[makeStep(1)]} />);
      tick(4000);
      rerender(<RunningView {...defaultProps} isRunning={false} errorMsg="Lost connection to server." steps={[makeStep(1)]} />);
      tick(10000);
      expect(timeCells()).toEqual(timeCells().map(() => "0:04"));
      expect(vi.getTimerCount()).toBe(0);
    });

    it("shows the backend's duration of an error run that reports one", () => {
      const { rerender } = render(<RunningView {...defaultProps} steps={[makeStep(1)]} />);
      tick(5000);
      rerender(
        <RunningView
          {...defaultProps}
          isRunning={false}
          errorMsg="The agent could not complete a single step."
          analyzingStats={{ total_ms: 7532, input_tokens: 0, output_tokens: 0, total_tokens: 0, cost_usd: 0 }}
          steps={[makeStep(1), makeStep(2)]}
        />
      );
      tick(10000);
      expect(timeCells()).toEqual(timeCells().map(() => "0:07"));
    });

    it("leaves no timer behind when it unmounts mid-run", () => {
      const { unmount } = render(<RunningView {...defaultProps} steps={[makeStep(1)]} />);
      expect(vi.getTimerCount()).toBeGreaterThan(0);
      unmount();
      expect(vi.getTimerCount()).toBe(0);
    });
  });

  it("has no external links or booking buttons", () => {
    render(<RunningView {...defaultProps} />);
    expect(document.querySelector("a[href]")).toBeNull();
    expect(screen.queryByText(/book a demo/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/agent-accessible/i)).not.toBeInTheDocument();
  });
});
