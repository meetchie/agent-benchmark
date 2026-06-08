// POST /api/benchmark/generate-tasks
// Proxies to the Python container. BENCH-1: requires a signed-in caller (the
// container Clerk-verifies the forwarded token) so this LLM-spend endpoint is
// not anonymously reachable.

import type { Env } from "../../env";

export const onRequestPost: PagesFunction<Env> = async (context) => {
  const containerUrl = context.env.AGENT_CONTAINER_URL;
  if (!containerUrl) {
    return Response.json({ error: "AGENT_CONTAINER_URL not configured" }, { status: 503 });
  }

  // BENCH-1: require a Bearer token; the container verifies the Clerk JWT.
  const authHeader = context.request.headers.get("Authorization") ?? "";
  const token = authHeader.startsWith("Bearer ") ? authHeader.slice(7) : "";
  if (!token) {
    return Response.json({ error: "Missing Authorization header" }, { status: 401 });
  }

  try {
    const res = await fetch(`${containerUrl}/benchmark/generate-tasks`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
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
