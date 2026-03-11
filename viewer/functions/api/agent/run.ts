// POST /api/agent/run
//
// Dispatches a complex, multi-step browser agent session to a Python container.
// The container runs the full BrowserUse/Skyvern/Stagehand agent with a real browser.
//
// This Worker acts as a thin proxy: validates the request, forwards it to the
// container, and streams or returns the result.
//
// Request body:
//   {
//     "agent": "browseruse" | "skyvern" | "stagehand",
//     "scenario": "...",
//     "params": { ... }
//   }
//
// Response:
//   { "status": "completed", "result": { ... }, "elapsed_ms": 123 }

import type { Env } from "../../env";

// --------------------------------------------------------------------------
// TODO: Define these once the Python container API contract is finalized
// --------------------------------------------------------------------------

type AgentType = "browseruse" | "skyvern" | "stagehand";

interface AgentRunRequest {
  agent: AgentType;
  scenario: string;
  params?: Record<string, unknown>;
}

interface AgentRunResponse {
  status: "completed" | "failed" | "timeout";
  result: unknown;
  elapsed_ms: number;
}

// --------------------------------------------------------------------------

const VALID_AGENTS: AgentType[] = ["browseruse", "skyvern", "stagehand"];

export const onRequestPost: PagesFunction<Env> = async (context) => {
  const start = Date.now();

  // --- Parse & validate ---
  let body: AgentRunRequest;
  try {
    body = await context.request.json();
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  if (!body.agent || !VALID_AGENTS.includes(body.agent)) {
    return Response.json(
      { error: `Invalid agent. Must be one of: ${VALID_AGENTS.join(", ")}` },
      { status: 400 }
    );
  }

  if (!body.scenario) {
    return Response.json(
      { error: "Missing required field: scenario" },
      { status: 400 }
    );
  }

  // --- Forward to Python container ---
  const containerUrl = context.env.AGENT_CONTAINER_URL;

  if (!containerUrl) {
    // TODO: Remove this once the container is deployed and the secret is set.
    return Response.json(
      {
        error: "Agent container not configured",
        detail:
          "Set AGENT_CONTAINER_URL in .dev.vars (local) or Cloudflare dashboard (prod). " +
          "See TODO list below for next steps.",
        todo: [
          "Choose a container host (Fly.io, Railway, or similar)",
          "Containerize the clean-room Python agents (Dockerfile)",
          "Expose an HTTP API from the container (e.g. FastAPI)",
          "Deploy the container and get its public URL",
          "Set the URL: wrangler pages secret put AGENT_CONTAINER_URL",
        ],
      },
      { status: 503 }
    );
  }

  try {
    const containerResponse = await fetch(`${containerUrl}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agent: body.agent,
        scenario: body.scenario,
        params: body.params ?? {},
      }),
    });

    if (!containerResponse.ok) {
      const errorText = await containerResponse.text();
      return Response.json(
        {
          error: "Agent container returned an error",
          status_code: containerResponse.status,
          detail: errorText,
        },
        { status: 502 }
      );
    }

    const result = await containerResponse.json();

    const response: AgentRunResponse = {
      status: "completed",
      result,
      elapsed_ms: Date.now() - start,
    };

    return Response.json(response);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return Response.json(
      { error: "Failed to reach agent container", detail: message },
      { status: 502 }
    );
  }
};
