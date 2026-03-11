// GET /api/agent/status
//
// Checks if the Python agent container is reachable.
// Useful for health monitoring and debugging connectivity.

import type { Env } from "../../env";

export const onRequestGet: PagesFunction<Env> = async (context) => {
  const containerUrl = context.env.AGENT_CONTAINER_URL;

  if (!containerUrl) {
    return Response.json({
      configured: false,
      message: "AGENT_CONTAINER_URL is not set. Container integration is pending.",
      todo: [
        "Choose a container host (Fly.io, Railway, or similar)",
        "Containerize the clean-room Python agents",
        "Deploy and set AGENT_CONTAINER_URL secret",
      ],
    });
  }

  try {
    const start = Date.now();
    const res = await fetch(`${containerUrl}/health`, {
      signal: AbortSignal.timeout(5000),
    });
    const latency = Date.now() - start;

    return Response.json({
      configured: true,
      reachable: res.ok,
      container_url: containerUrl,
      latency_ms: latency,
      container_status: res.status,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return Response.json({
      configured: true,
      reachable: false,
      container_url: containerUrl,
      error: message,
    });
  }
};
