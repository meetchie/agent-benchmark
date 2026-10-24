import { cleanup, render, screen, waitFor } from "@testing-library/react";
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

    async function runToCompletion(statusBody: object) {
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
      await screen.findByText("Added a book to the cart.", {}, { timeout: 4000 });
    }

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
});
