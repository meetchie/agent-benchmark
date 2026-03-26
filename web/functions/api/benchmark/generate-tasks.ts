// POST /api/benchmark/generate-tasks
// Proxies to Python container — no auth required.

import type { Env } from "../../env";

export const onRequestPost: PagesFunction<Env> = async (context) => {
  const containerUrl = context.env.AGENT_CONTAINER_URL;
  if (!containerUrl) {
    return Response.json({ error: "AGENT_CONTAINER_URL not configured" }, { status: 503 });
  }

  try {
    const res = await fetch(`${containerUrl}/benchmark/generate-tasks`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Internal-Key": context.env.INTERNAL_API_KEY || "",
      },
      body: context.request.body,
      signal: AbortSignal.timeout(30000),
    });

    if (!res.ok) {
      const text = await res.text();
      return new Response(text, {
        status: res.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    const data = await res.json();
    return Response.json(data);
  } catch (err) {
    return Response.json({ error: "Service temporarily unavailable" }, { status: 502 });
  }
};
