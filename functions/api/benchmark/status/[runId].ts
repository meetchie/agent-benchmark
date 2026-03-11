// GET /api/benchmark/status/:runId
// Polls the Python container for the current run state.
// Dynamic segment accessed via context.params.runId

import type { Env } from "../../../env";

export const onRequestGet: PagesFunction<Env> = async (context) => {
  const runId = context.params.runId as string;

  if (!runId) {
    return Response.json({ error: "Missing runId" }, { status: 400 });
  }

  const containerUrl = context.env.AGENT_CONTAINER_URL;
  if (!containerUrl) {
    return Response.json(
      { error: "AGENT_CONTAINER_URL not configured" },
      { status: 503 }
    );
  }

  try {
    const res = await fetch(`${containerUrl}/benchmark/status/${runId}`, {
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
