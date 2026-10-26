import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ResultsOverlay } from "../ResultsOverlay";
import type { SummaryData, StepRecord } from "../../lib/types";

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

  it("says it is a demo result when the backend plays canned runs", () => {
    render(<ResultsOverlay {...defaultProps} demoMode />);
    expect(screen.getByTestId("demo-banner")).toHaveTextContent("Demo mode: canned runs, no real agent or API calls");
  });

  it("has no demo banner against a real backend", () => {
    render(<ResultsOverlay {...defaultProps} />);
    expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();
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
    const summary = makeSummary({ total_ms: 5000, total_tokens: 12000, cost_usd: 0.0423 });
    render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
    expect(screen.getByText("Time")).toBeInTheDocument();
    expect(screen.getByText("Steps")).toBeInTheDocument();
    expect(screen.getByText("Tokens")).toBeInTheDocument();
    expect(screen.getByText("Cost")).toBeInTheDocument();
  });

  describe("cost and agent model", () => {
    it("shows the backend's cost_usd and agent_model", () => {
      const summary = makeSummary({ cost_usd: 0.0423, agent_model: "claude-sonnet-5-5" });
      render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
      expect(screen.getByText("$0.04")).toBeInTheDocument();
      expect(screen.getByText("claude-sonnet-5-5")).toBeInTheDocument();
    });

    it("does not recompute the cost from the token counts", () => {
      // The backend says $1.23 and that is what shows, not a price worked out from 10,000 input +
      // 2,000 output tokens.
      const summary = makeSummary({ cost_usd: 1.234, agent_model: "claude-opus-5-5" });
      render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
      expect(screen.getByText("$1.23")).toBeInTheDocument();
      expect(screen.queryByText("$0.05")).not.toBeInTheDocument();
    });

    it("shows a sub-cent cost as <$0.01", () => {
      const summary = makeSummary({ cost_usd: 0.004 });
      render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
      expect(screen.getByText("<$0.01")).toBeInTheDocument();
    });

    it("shows tokens only when cost_usd is null", () => {
      const summary = makeSummary({ cost_usd: null, agent_model: "some-unpriced-model" });
      render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
      expect(screen.queryByText("Cost")).not.toBeInTheDocument();
      expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
      expect(screen.getByText("Tokens")).toBeInTheDocument();
      expect(screen.getByText("12.0k")).toBeInTheDocument();
    });

    it("shows tokens only when cost_usd is absent from the payload", () => {
      render(<ResultsOverlay {...defaultProps} summary={makeSummary()} steps={[makeStep(1)]} />);
      expect(screen.queryByText("Cost")).not.toBeInTheDocument();
      expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
      expect(screen.queryByText(/Agent model/)).not.toBeInTheDocument();
      expect(screen.getByText("12.0k")).toBeInTheDocument();
    });

    it("shows the cost while the judge is still analyzing", () => {
      render(
        <ResultsOverlay
          {...defaultProps}
          isAnalyzing
          analyzingStats={{
            total_ms: 9000,
            input_tokens: 20000,
            output_tokens: 1000,
            total_tokens: 21000,
            cost_usd: 0.05,
            agent_model: "claude-sonnet-5-5",
          }}
          steps={[makeStep(1)]}
        />
      );
      expect(screen.getByText("$0.05")).toBeInTheDocument();
    });
  });

  describe("a run that ended as an error after some steps (judged)", () => {
    const judgedError = makeSummary({
      success: false,
      result_state: "error",
      summary: "The agent opened the page and searched, then stopped.",
      total_ms: 9000,
      total_tokens: 20000,
      cost_usd: 0.03,
      phases: [{ name: "Open the site", steps: [1, 2], total_ms: 7000, failed: false, slow: true }],
    });
    const twoSteps = [makeStep(1, "Open Products page", 4000), makeStep(2, "Search top", 3000)];

    it("says why it is an error, what the judge saw and the phases", () => {
      render(
        <ResultsOverlay
          {...defaultProps}
          summary={judgedError}
          errorMsg="The agent model declined to continue this task (safety refusal)."
          steps={twoSteps}
        />
      );
      expect(screen.getByText("Error")).toBeInTheDocument();
      expect(screen.getByText("The agent model declined to continue this task (safety refusal).")).toBeInTheDocument();
      expect(screen.getByText("The agent opened the page and searched, then stopped.")).toBeInTheDocument();
      expect(screen.getByText("Phases")).toBeInTheDocument();
      expect(screen.getByText(/Open the site/)).toBeInTheDocument();
      expect(screen.queryByText("No steps were completed")).not.toBeInTheDocument();
    });

    it("still shows the judge's summary and phases when the backend sent no reason", () => {
      render(<ResultsOverlay {...defaultProps} summary={judgedError} steps={twoSteps} />);
      expect(screen.getByText("Error")).toBeInTheDocument();
      expect(screen.getByText("The agent opened the page and searched, then stopped.")).toBeInTheDocument();
      expect(screen.getByText("Phases")).toBeInTheDocument();
    });
  });

  it("does not list the steps of an error run the judge never saw", () => {
    render(<ResultsOverlay {...defaultProps} errorMsg="Lost connection to server." steps={[makeStep(1, "Open the site")]} />);
    expect(screen.getByText("Lost connection to server.")).toBeInTheDocument();
    expect(screen.queryByText("All Steps")).not.toBeInTheDocument();
    expect(screen.queryByText("Open the site")).not.toBeInTheDocument();
  });

  describe("the agent's final report", () => {
    it("shows the report and that the agent said it did not succeed", () => {
      const summary = makeSummary({
        result_state: "fail",
        success: false,
        final_report: "I could not add 'Quantum Banana Phone 9000' to the cart: there is no such product.",
        agent_reported_success: false,
      });
      render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
      expect(screen.getByTestId("final-report")).toHaveTextContent("Agent's final report · says it did not succeed");
      expect(
        screen.getByText("I could not add 'Quantum Banana Phone 9000' to the cart: there is no such product.")
      ).toBeInTheDocument();
    });

    it("says when the agent reported success", () => {
      const summary = makeSummary({ final_report: 'The first product listed is "Blue Top" (Rs. 500).', agent_reported_success: true });
      render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
      expect(screen.getByTestId("final-report")).toHaveTextContent("· says it succeeded");
      expect(screen.getByText(/Blue Top/)).toBeInTheDocument();
    });

    it("has no report section when the agent gave none", () => {
      const summary = makeSummary({ result_state: "too_slow", success: false, final_report: null });
      render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
      expect(screen.queryByTestId("final-report")).not.toBeInTheDocument();
    });

    it("still shows the report when the judge gave no verdict", () => {
      const summary = makeSummary({
        result_state: "error",
        success: false,
        summary: "Could not analyze the run.",
        final_report: "Cart: 4 x Rs. 799 = Rs. 3196.",
        agent_reported_success: true,
      });
      render(
        <ResultsOverlay
          {...defaultProps}
          summary={summary}
          errorMsg="The judge could not analyze the run: NotFoundError from claude-sonnet-5-5x: model: claude-sonnet-5-5x"
          steps={[makeStep(1)]}
        />
      );
      expect(screen.getByText("Error")).toBeInTheDocument();
      expect(screen.getByText(/The judge could not analyze the run: NotFoundError/)).toBeInTheDocument();
      expect(screen.getByText("Cart: 4 x Rs. 799 = Rs. 3196.")).toBeInTheDocument();
    });

    it("renders the report's bold text as bold, not as asterisks", () => {
      const summary = makeSummary({
        final_report: '**Search:** I searched "top" and opened the first result.',
      });
      render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
      const report = screen.getByTestId("final-report");
      const bold = report.querySelector("strong");
      expect(bold).not.toBeNull();
      expect(bold).toHaveTextContent("Search:");
      expect(report).toHaveTextContent('Search: I searched "top" and opened the first result.');
      expect(report.textContent).not.toContain("**");
    });

    it("renders the report's bullet and numbered lists as list items", () => {
      const summary = makeSummary({
        final_report: [
          "I did the task:",
          '- **Search:** I searched "top".',
          "- **Cart:** 2 x Blue Top, Rs. 1000.",
          "",
          "Then I checked:",
          "1. the quantity",
          "2. the total",
        ].join("\n"),
      });
      render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
      const report = screen.getByTestId("final-report");
      const bullets = report.querySelectorAll("ul > li");
      expect(Array.from(bullets, (li) => li.textContent)).toEqual([
        'Search: I searched "top".',
        "Cart: 2 x Blue Top, Rs. 1000.",
      ]);
      expect(bullets[0].querySelector("strong")).toHaveTextContent("Search:");
      const numbered = report.querySelectorAll("ol > li");
      expect(Array.from(numbered, (li) => li.textContent)).toEqual(["the quantity", "the total"]);
      expect(report.textContent).not.toMatch(/(^|\s)- /);
    });

    it("shows HTML in the report as text and never runs it", () => {
      const html = '<img src="x" onerror="window.__reportRan = 1"> and <script>window.__reportRan = 2</script>';
      const summary = makeSummary({ final_report: `The page said: ${html}` });
      render(<ResultsOverlay {...defaultProps} summary={summary} steps={[makeStep(1)]} />);
      const report = screen.getByTestId("final-report");
      expect(report.querySelector("img")).toBeNull();
      expect(report.querySelector("script")).toBeNull();
      expect(report).toHaveTextContent(`The page said: ${html}`);
      expect((window as unknown as { __reportRan?: number }).__reportRan).toBeUndefined();
    });
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
