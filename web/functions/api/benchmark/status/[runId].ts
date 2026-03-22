// GET /api/benchmark/status/:runId
// Proxies to Python container — no auth required (run IDs are ephemeral UUIDs).

import type { Env } from "../../../env";

export const onRequestGet: PagesFunction<Env> = async (context) => {
  const runId = context.params.runId as string;
  if (!runId) {
    return Response.json({ error: "Missing runId" }, { status: 400 });
  }

  const containerUrl = context.env.AGENT_CONTAINER_URL;
  if (!containerUrl) {
    return Response.json({ error: "AGENT_CONTAINER_URL not configured" }, { status: 503 });
  }

  try {
    const res = await fetch(`${containerUrl}/benchmark/status/${runId}`, {
      headers: {
        "X-Internal-Key": context.env.INTERNAL_API_KEY || "",
      },
      signal: AbortSignal.timeout(5000),
    });

    if (!res.ok) {
      return Response.json({ error: "Service temporarily unavailable" }, { status: 502 });
    }

    const data = await res.json();
    return Response.json(data);
  } catch (err) {
    return Response.json({ error: "Service temporarily unavailable" }, { status: 502 });
  }
};
