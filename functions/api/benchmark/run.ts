// POST /api/benchmark/run
// Starts a benchmark run on the Python container and returns a run_id.

import type { Env } from "../../env";

interface RunRequest {
  url: string;
  goal: string;
}

export const onRequestPost: PagesFunction<Env> = async (context) => {
  let body: RunRequest;
  try {
    body = await context.request.json();
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  if (!body.url || !body.goal) {
    return Response.json(
      { error: "Missing required fields: url, goal" },
      { status: 400 }
    );
  }

  const containerUrl = context.env.AGENT_CONTAINER_URL;
  if (!containerUrl) {
    return Response.json(
      { error: "AGENT_CONTAINER_URL not configured. Set it in .dev.vars." },
      { status: 503 }
    );
  }

  try {
    const res = await fetch(`${containerUrl}/benchmark/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: body.url, goal: body.goal }),
      signal: AbortSignal.timeout(5000),
    });

    if (!res.ok) {
      const text = await res.text();
      return Response.json(
        { error: "Container error", detail: text },
        { status: 502 }
      );
    }

    const data = await res.json();
    return Response.json(data);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    return Response.json(
      { error: "Failed to reach container", detail: msg },
      { status: 502 }
    );
  }
};
