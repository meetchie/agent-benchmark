// POST /api/benchmark/cancel/:runId
// Proxies cancellation to the Python container. Run IDs are ephemeral UUIDs.

import type { Env } from "../../../env";

export const onRequestPost: PagesFunction<Env> = async (context) => {
  const runId = context.params.runId as string;
  if (!runId) {
    return Response.json({ error: "Missing runId" }, { status: 400 });
  }

  const containerUrl = context.env.AGENT_CONTAINER_URL;
  if (!containerUrl) {
    return Response.json({ error: "AGENT_CONTAINER_URL not configured" }, { status: 503 });
  }

  try {
    const res = await fetch(`${containerUrl}/benchmark/cancel/${runId}`, {
      method: "POST",
      headers: {
        "X-Internal-Key": context.env.INTERNAL_API_KEY || "",
      },
      signal: AbortSignal.timeout(5000),
    });

    if (!res.ok) {
      const text = await res.text();
      return new Response(text, {
        status: res.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    return Response.json(await res.json());
  } catch {
    return Response.json({ error: "Service temporarily unavailable" }, { status: 502 });
  }
};
