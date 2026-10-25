import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";

// Canvas animations and ResizeObserver do not exist in jsdom.
vi.mock("../components/FlickeringGrid", () => ({ FlickeringGrid: () => null }));
vi.mock("../components/HeroFluidGradient", () => ({ HeroFluidGradient: () => null }));
vi.mock("../components/BackgroundGrid", () => ({ BackgroundGrid: () => null }));
vi.mock("../components/StepLog", () => ({ StepLog: () => null }));

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

type Route = () => Response;

function stubBackend(routes: Record<string, Route>) {
  const fetchMock = vi.fn(async (input: string) => {
    const prefix = Object.keys(routes).find((p) => input.startsWith(p));
    if (!prefix) throw new Error(`unexpected request to ${input}`);
    return routes[prefix]();
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function headersSentTo(fetchMock: ReturnType<typeof stubBackend>, path: string): Record<string, string> {
  const call = fetchMock.mock.calls.find((c) => c[0] === path) as unknown as [string, RequestInit] | undefined;
  expect(call, `a request to ${path}`).toBeDefined();
  return (call![1]?.headers ?? {}) as Record<string, string>;
}

const TASK = { id: 1, label: "Add a book to the cart", goal: "Add any book to the cart." };

// The tests run with no Clerk key, so "@clerk/clerk-react" is the local shim.
describe("App in local mode (no Clerk key)", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  async function openSetup() {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Test Your Site/ }));
    return { user, input: await screen.findByPlaceholderText("https://your-site.com") };
  }

  it("shows no sign-in controls and does not throw without a Clerk key", async () => {
    stubBackend({ "/api/benchmark/quota": () => json({ remaining: 0, resets_in: 0, limit: 0 }) });
    render(<App />);

    expect(screen.getByRole("heading", { name: /The AI economy/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign in/i })).not.toBeInTheDocument();
  });

  it("makes no backend request while on the landing page", async () => {
    const fetchMock = stubBackend({});
    const user = userEvent.setup();
    render(<App />);
    await Promise.resolve();

    expect(fetchMock).not.toHaveBeenCalled();

    // Leaving the landing page is what asks the backend for the quota.
    stubBackend({ "/api/benchmark/quota": () => json({ remaining: 0, resets_in: 0, limit: 0 }) });
    await user.click(screen.getByRole("button", { name: /Test Your Site/ }));
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/benchmark/quota", expect.anything()));
  });

  it("generates tasks and starts a run without an Authorization header", async () => {
    const fetchMock = stubBackend({
      "/api/benchmark/quota": () => json({ remaining: 0, resets_in: 0, limit: 0 }),
      "/api/benchmark/generate-tasks": () => json({ tasks: [TASK] }),
      "/api/benchmark/run": () => json({ run_id: "run-1", remaining: 0, resets_in: 0 }),
      "/api/benchmark/status": () => json({ status: "running", steps: [] }),
    });
    const { user, input } = await openSetup();

    expect(screen.queryByRole("button", { name: /sign in/i })).not.toBeInTheDocument();

    await user.type(input, "https://books.example{Enter}");
    await user.click(await screen.findByText(TASK.label));
    await user.click(screen.getByRole("button", { name: "Run Benchmark" }));

    await waitFor(() => expect(fetchMock.mock.calls.map((c) => c[0])).toContain("/api/benchmark/run"));
    for (const path of ["/api/benchmark/quota", "/api/benchmark/generate-tasks", "/api/benchmark/run"]) {
      expect(headersSentTo(fetchMock, path)).not.toHaveProperty("Authorization");
    }
    const runCall = fetchMock.mock.calls.find((c) => c[0] === "/api/benchmark/run") as unknown as [string, RequestInit];
    expect(JSON.parse(runCall[1].body as string)).toMatchObject({
      url: "https://books.example",
      goal: TASK.goal,
      label: TASK.label,
    });
  });

  describe("a finished run", () => {
    const COMPLETE = {
      status: "complete",
      steps: [{ step: 1, description: "Open the site", elapsed_ms: 400 }],
      success: true,
      summary: "Added a book to the cart.",
      result_state: "pass",
      total_ms: 5000,
      input_tokens: 9000,
      output_tokens: 1000,
      total_tokens: 10000,
      phases: [],
    };

    async function runToCompletion(statusBody: object, shownWhenDone = "Added a book to the cart.") {
      stubBackend({
        "/api/benchmark/quota": () => json({ remaining: 0, resets_in: 0, limit: 0 }),
        "/api/benchmark/generate-tasks": () => json({ tasks: [TASK] }),
        "/api/benchmark/run": () => json({ run_id: "run-1" }),
        "/api/benchmark/status": () => json(statusBody),
      });
      const { user, input } = await openSetup();
      await user.type(input, "https://books.example{Enter}");
      await user.click(await screen.findByText(TASK.label));
      await user.click(screen.getByRole("button", { name: "Run Benchmark" }));
      // The first status poll fires after one second.
      await screen.findByText(shownWhenDone, {}, { timeout: 4000 });
    }

    it("says why a run that ended as an error after some steps is an error", async () => {
      // What the backend sends for a run the model refused part-way: the steps
      // were judged, so the status is complete with result_state "error".
      const judgedError = {
        status: "complete",
        steps: [
          { step: 1, description: "Open Products page", elapsed_ms: 4000 },
          { step: 2, description: "Search top", elapsed_ms: 3000 },
        ],
        success: false,
        summary: "The agent opened the page and searched, then stopped.",
        result_state: "error",
        total_ms: 9000,
        input_tokens: 19000,
        output_tokens: 1000,
        total_tokens: 20000,
        cost_usd: 0.03,
        agent_model: "claude-sonnet-5-5",
        phases: [{ name: "Open the site", steps: [1, 2], total_ms: 7000, failed: false, slow: true }],
        message: "The agent model declined to continue this task (safety refusal).",
      };
      await runToCompletion(judgedError, "The agent opened the page and searched, then stopped.");

      const card = screen.getByRole("dialog");
      expect(card).toHaveTextContent("Error");
      expect(card).toHaveTextContent("The agent model declined to continue this task (safety refusal).");
      expect(card).toHaveTextContent("Phases");
      expect(card).toHaveTextContent("Open the site");
      expect(card).toHaveTextContent("$0.03");
    });

    it("shows the agent's final report", async () => {
      await runToCompletion({
        ...COMPLETE,
        final_report: "Basket: 1 item, A Light in the Attic, £51.77.",
        agent_reported_success: true,
      });
      expect(screen.getByTestId("final-report")).toHaveTextContent("Basket: 1 item, A Light in the Attic, £51.77.");
    });

    it("shows the backend's cost_usd and agent_model", async () => {
      await runToCompletion({ ...COMPLETE, cost_usd: 0.0423, agent_model: "claude-sonnet-5-5" });

      expect(screen.getAllByText("$0.04").length).toBeGreaterThan(0);
      expect(screen.getAllByText("claude-sonnet-5-5").length).toBeGreaterThan(0);
    });

    it("shows tokens only when the backend sends a null cost", async () => {
      await runToCompletion({ ...COMPLETE, cost_usd: null, agent_model: "claude-sonnet-5-5" });

      expect(screen.queryByText("Cost")).not.toBeInTheDocument();
      expect(document.body.textContent).not.toMatch(/\$/);
      expect(screen.getAllByText("10,000").length).toBeGreaterThan(0);
    });

    it("shows the same token total in the run view and on the results card when there are cache writes", async () => {
      // Real run 21df242f: input 227,454 + cache writes 18,638 + output 3,053 = 249,145.
      // The status reply has no cache-write field; only total_tokens includes them.
      await runToCompletion({
        ...COMPLETE,
        input_tokens: 227454,
        output_tokens: 3053,
        total_tokens: 249145,
        cost_usd: 0.9,
        agent_model: "claude-sonnet-5-5",
      });

      const values = screen.getAllByText("Tokens").map((label) => label.nextElementSibling?.textContent);
      // The results card comes last in the page and rounds to thousands; every cell
      // of the run view before it shows the full number.
      const card = values.pop();
      expect(card).toBe("249.1k");
      expect(values.length).toBeGreaterThan(0);
      expect(values).toEqual(values.map(() => "249,145"));
      expect(document.body.textContent).not.toMatch(/230,507/);
    });
  });

  it("shows no run counter when the backend enforces no limit", async () => {
    const fetchMock = stubBackend({
      "/api/benchmark/quota": () => json({ remaining: 0, resets_in: 0, limit: 0 }),
    });
    await openSetup();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/benchmark/quota", expect.anything()));

    expect(screen.queryByText(/runs? remaining/)).not.toBeInTheDocument();
    expect(screen.queryByText(/No runs remaining/)).not.toBeInTheDocument();
  });

  it("tells the user to start the backend when nothing answers", async () => {
    stubBackend({
      "/api/benchmark/quota": () => new Response("", { status: 500 }),
      "/api/benchmark/generate-tasks": () => new Response("", { status: 500 }),
    });
    const { user, input } = await openSetup();

    await user.type(input, "https://books.example{Enter}");

    expect(await screen.findByText(/Can't reach the benchmark server/)).toBeInTheDocument();
  });

  it("explains a 401 as an auth-mode mismatch instead of opening a sign-in modal", async () => {
    stubBackend({
      "/api/benchmark/quota": () => json({}, 401),
      "/api/benchmark/generate-tasks": () => json({ detail: "Not authenticated" }, 401),
    });
    const { user, input } = await openSetup();

    await user.type(input, "https://books.example{Enter}");

    expect(await screen.findByText(/AUTH_MODE=none/)).toBeInTheDocument();
    expect(screen.queryByText(/Sign in to Rindler/)).not.toBeInTheDocument();
  });

  describe("what the backend says about itself (GET /health)", () => {
    const HEALTH_DEMO = { ok: true, demo_mode: true, timeout_s: 180 };
    const HEALTH_REAL = { ok: true, demo_mode: false, timeout_s: 180 };
    const DONE = {
      status: "complete",
      steps: [{ step: 1, description: "Open the site", elapsed_ms: 400 }],
      success: true,
      summary: "Added a book to the cart.",
      result_state: "pass",
      total_ms: 5000,
      input_tokens: 9000,
      output_tokens: 1000,
      total_tokens: 10000,
      phases: [],
    };

    function routesFor(health: Route, status: Route = () => json(DONE)) {
      return {
        "/api/benchmark/health": health,
        "/api/benchmark/quota": () => json({ remaining: 0, resets_in: 0, limit: 0 }),
        "/api/benchmark/generate-tasks": () => json({ tasks: [TASK] }),
        "/api/benchmark/run": () => json({ run_id: "run-1" }),
        "/api/benchmark/status": status,
      };
    }

    async function pickTask() {
      const { user, input } = await openSetup();
      await user.type(input, "https://books.example{Enter}");
      await user.click(await screen.findByText(TASK.label));
      return user;
    }

    it("asks for health once, when the visitor leaves the landing page, not before", async () => {
      const fetchMock = stubBackend(routesFor(() => json(HEALTH_REAL)));
      const user = userEvent.setup();
      render(<App />);
      await Promise.resolve();
      expect(fetchMock).not.toHaveBeenCalled();

      await user.click(screen.getByRole("button", { name: /Test Your Site/ }));
      await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/benchmark/health"));
      expect(fetchMock.mock.calls.filter((c) => c[0] === "/api/benchmark/health")).toHaveLength(1);
    });

    it("shows the demo banner on the setup, running and results screens of a demo backend", async () => {
      stubBackend(routesFor(() => json(HEALTH_DEMO)));
      const user = await pickTask();

      expect(await screen.findByTestId("demo-banner")).toHaveTextContent(
        "Demo mode: canned runs, no real agent or API calls"
      );

      await user.click(screen.getByRole("button", { name: "Run Benchmark" }));
      // Running view, then (after the first status poll) the results card as well.
      await screen.findByText("Added a book to the cart.", {}, { timeout: 4000 });
      expect(screen.getAllByTestId("demo-banner")).toHaveLength(2);
    });

    it("shows no banner anywhere against a real backend", async () => {
      const fetchMock = stubBackend(routesFor(() => json(HEALTH_REAL)));
      const user = await pickTask();
      await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/benchmark/health"));
      expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Run Benchmark" }));
      await screen.findByText("Added a book to the cart.", {}, { timeout: 4000 });
      expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();
    });

    it("asks again when a run starts if the backend was not up the first time", async () => {
      let up = false;
      const health: Route = () => (up ? json(HEALTH_DEMO) : new Response("", { status: 500 }));
      const fetchMock = stubBackend(routesFor(health));
      const user = await pickTask();
      expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();

      up = true;
      await user.click(screen.getByRole("button", { name: "Run Benchmark" }));
      await screen.findByText("Added a book to the cart.", {}, { timeout: 4000 });
      expect(screen.getAllByTestId("demo-banner").length).toBeGreaterThan(0);
      expect(fetchMock.mock.calls.filter((c) => c[0] === "/api/benchmark/health")).toHaveLength(2);
    });
  });

  // A run that ends with status "error" (a rejected API key, the judge failing, the
  // server stopping) is over: its clock must stop, and show the run's real duration
  // when the backend reports one. These run on fake timers, like the next block.
  describe("the clock of a run that ends as an error", () => {
    const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) });
    const step = (n: number) => ({ step: n, description: "Processing...", elapsed_ms: 1000 });
    const steps = (n: number) => Array.from({ length: n }, (_, i) => step(i + 1));

    // What the backend sends for a run whose six steps all failed on a rejected
    // API key (run 8957c762): status "error", with the steps, time and usage.
    const BAD_KEY = {
      status: "error",
      message: "The agent could not complete a single step: the API key was rejected (check ANTHROPIC_API_KEY).",
      steps: steps(6),
      total_ms: 7532,
      input_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
      cost_usd: 0,
      agent_model: "claude-sonnet-5-5",
    };

    async function startRun(statusReplies: Array<unknown | Error>) {
      let polls = 0;
      const fetchMock = vi.fn(async (input: string) => {
        if (input.startsWith("/api/benchmark/health")) return reply({ ok: true, demo_mode: false, timeout_s: 180 });
        if (input.startsWith("/api/benchmark/quota")) return reply({ remaining: 0, resets_in: 0, limit: 0 });
        if (input.startsWith("/api/benchmark/generate-tasks")) return reply({ tasks: [TASK] });
        if (input.startsWith("/api/benchmark/run")) return reply({ run_id: "run-1" });
        if (input.startsWith("/api/benchmark/status")) {
          const next = statusReplies[Math.min(polls++, statusReplies.length - 1)];
          if (next instanceof Error) throw next;
          return reply(next);
        }
        throw new Error(`unexpected request to ${input}`);
      });
      vi.stubGlobal("fetch", fetchMock);
      const { user, input } = await openSetup();
      await user.type(input, "https://books.example{Enter}");
      await user.click(await screen.findByText(TASK.label));

      vi.useFakeTimers();
      fireEvent.click(screen.getByRole("button", { name: "Run Benchmark" }));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
    }

    // A second at a time, so React renders each poll's reply before the next timer fires.
    async function advance(seconds: number) {
      for (let s = 0; s < seconds; s++) {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(1000);
        });
      }
    }

    // Every Time cell: the stats (one per layout) and, once it is open, the results card.
    const timeCells = () => screen.getAllByText("Time").map((label) => label.nextElementSibling?.textContent);
    const headerTime = () => screen.getByRole("banner").textContent;

    afterEach(() => {
      vi.useRealTimers();
    });

    it("stops at the backend's total_ms and keeps it", async () => {
      // One poll a second: five running replies with a growing step list, then the error.
      await startRun([
        { status: "running", steps: steps(1) },
        { status: "running", steps: steps(2) },
        { status: "running", steps: steps(3) },
        { status: "running", steps: steps(4) },
        { status: "running", steps: steps(5) },
        BAD_KEY,
      ]);
      await advance(6);
      expect(screen.getAllByText(/could not complete a single step/).length).toBeGreaterThan(0);
      expect(timeCells()).toEqual(timeCells().map(() => "0:07"));
      expect(headerTime()).toContain("0:07");

      await advance(10);
      const cells = timeCells();
      expect(cells.length).toBeGreaterThan(2);
      expect(cells).toEqual(cells.map(() => "0:07"));
      expect(headerTime()).toContain("0:07");
      expect(headerTime()).not.toContain("RUNNING");
    });

    it("shows the error reply's steps and the usage it reports", async () => {
      await startRun([{ status: "running", steps: steps(2) }, BAD_KEY]);
      await advance(2);
      const stepCells = screen.getAllByText("Steps").map((label) => label.nextElementSibling?.textContent);
      expect(stepCells.length).toBeGreaterThan(0);
      expect(stepCells).toEqual(stepCells.map(() => "6"));
      for (const card of screen.getAllByTestId("agent-card")) {
        expect(card).toHaveTextContent("claude-sonnet-5-5");
      }
    });

    it("stops where it was when the server stops answering", async () => {
      const down = new TypeError("Failed to fetch");
      await startRun([
        { status: "running", steps: steps(1) },
        { status: "running", steps: steps(2) },
        down,
      ]);
      // Steps at 1 s and 2 s, then three failed polls: "Lost connection" at 5 s,
      // about four seconds after the clock started at the first step.
      await advance(5);
      expect(screen.getAllByText(/Lost connection/).length).toBeGreaterThan(0);
      const shown = timeCells()[0];
      expect(shown).toMatch(/^0:0[34]$/);
      expect(headerTime()).toContain(shown);

      await advance(10);
      expect(headerTime()).toContain(shown);
      expect(headerTime()).not.toContain("RUNNING");
      const stats = timeCells();
      expect(stats).toEqual(stats.map(() => shown));
    });
  });

  // The UI gives up on a run after the backend's agent time limit plus 3 minutes
  // for judging (at least 5, and 10 when it does not know the limit). These run
  // on fake timers, with the status endpoint answering "running" forever.
  describe("how long a run is polled before 'Lost connection'", () => {
    // Fake timers also fake the timers undici uses to read a Response body, so
    // these tests answer with plain objects.
    const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) });

    async function startForeverRun(health: unknown | null) {
      const fetchMock = vi.fn(async (input: string) => {
        if (input.startsWith("/api/benchmark/health")) {
          if (health === null) throw new TypeError("Failed to fetch");
          return reply(health);
        }
        if (input.startsWith("/api/benchmark/quota")) return reply({ remaining: 0, resets_in: 0, limit: 0 });
        if (input.startsWith("/api/benchmark/generate-tasks")) return reply({ tasks: [TASK] });
        if (input.startsWith("/api/benchmark/run")) return reply({ run_id: "run-1" });
        if (input.startsWith("/api/benchmark/status")) return reply({ status: "running", steps: [] });
        throw new Error(`unexpected request to ${input}`);
      });
      vi.stubGlobal("fetch", fetchMock);
      const { user, input } = await openSetup();
      await user.type(input, "https://books.example{Enter}");
      await user.click(await screen.findByText(TASK.label));

      vi.useFakeTimers();
      fireEvent.click(screen.getByRole("button", { name: "Run Benchmark" }));
      await advance(0);
    }

    async function advance(seconds: number) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(seconds * 1000);
      });
    }

    const lost = () => screen.queryAllByText(/Lost connection/);

    afterEach(() => {
      vi.useRealTimers();
    });

    // A few hundred one-second polls each, so allow more than the 5 s default.
    const SLOW = 60_000;

    it("keeps polling past 5 minutes when the backend's limit is 400 s, and gives up at 400 + 180", async () => {
      await startForeverRun({ ok: true, demo_mode: false, timeout_s: 400 });
      await advance(570);
      expect(lost()).toHaveLength(0);
      await advance(20);
      expect(lost()).toHaveLength(1);
    }, SLOW);

    it("uses limit + 180 s for the default 180 s limit (6 minutes, not 5)", async () => {
      await startForeverRun({ ok: true, demo_mode: false, timeout_s: 180 });
      await advance(350);
      expect(lost()).toHaveLength(0);
      await advance(20);
      expect(lost()).toHaveLength(1);
    }, SLOW);

    it("waits 10 minutes when it cannot learn the backend's limit", async () => {
      await startForeverRun(null);
      await advance(590);
      expect(lost()).toHaveLength(0);
      await advance(20);
      expect(lost()).toHaveLength(1);
    }, SLOW);
  });
});
