import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";

vi.mock("../components/FlickeringGrid", () => ({ FlickeringGrid: () => null }));
vi.mock("../components/HeroFluidGradient", () => ({ HeroFluidGradient: () => null }));
vi.mock("../components/BackgroundGrid", () => ({ BackgroundGrid: () => null }));
vi.mock("../components/StepLog", () => ({ StepLog: () => null }));

// Stand in for the real Clerk package, which needs a live Clerk instance.
const getToken = vi.fn(async () => "clerk-session-token");
vi.mock("@clerk/clerk-react", () => ({
  useAuth: () => ({ isSignedIn: true, getToken }),
  AuthenticateWithRedirectCallback: () => null,
  SignedIn: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  SignedOut: () => null,
  UserButton: () => null,
  useSignIn: () => ({ isLoaded: false }),
  useSignUp: () => ({ isLoaded: false }),
}));

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe("App with a Clerk key", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.stubEnv("VITE_CLERK_PUBLISHABLE_KEY", "pk_test_not-a-real-key");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("sends the Clerk session token as a bearer token", async () => {
    const fetchMock = vi.fn(async (input: string) => {
      if (input.startsWith("/api/benchmark/quota")) return json({ remaining: 2, resets_in: 0, limit: 3 });
      if (input.startsWith("/api/benchmark/generate-tasks")) return json({ tasks: [] });
      throw new Error(`unexpected request to ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Test Your Site/ }));
    const input = await screen.findByPlaceholderText("https://your-site.com");

    await user.type(input, "https://books.example{Enter}");

    await waitFor(() => expect(fetchMock.mock.calls.map((c) => c[0])).toContain("/api/benchmark/generate-tasks"));
    for (const path of ["/api/benchmark/quota", "/api/benchmark/generate-tasks"]) {
      const call = fetchMock.mock.calls.find((c) => c[0] === path) as unknown as [string, RequestInit];
      expect(call[1].headers).toMatchObject({ Authorization: "Bearer clerk-session-token" });
    }
    await waitFor(() => expect(document.body.textContent).toMatch(/2 runs remaining/));
  });
});
