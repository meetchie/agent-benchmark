// POST /api/benchmark/run
// Verifies Clerk JWT, then proxies to the Python container.

import { verifyToken } from "@clerk/backend";
import type { Env } from "../../env";

interface RunRequest {
  url: string;
  goal: string;
  label?: string;
}

export const onRequestPost: PagesFunction<Env> = async (context) => {
  // 1. Extract Bearer token
  const authHeader = context.request.headers.get("Authorization") ?? "";
  const token = authHeader.startsWith("Bearer ") ? authHeader.slice(7) : "";
  if (!token) {
    return Response.json({ error: "Missing Authorization header" }, { status: 401 });
  }

  // 2. Verify Clerk JWT
  let userId: string;
  try {
    const payload = await verifyToken(token, {
      secretKey: context.env.CLERK_SECRET_KEY,
    });
    userId = payload.sub;
  } catch {
    return Response.json({ error: "Invalid or expired token" }, { status: 401 });
  }

  // 3. Parse and validate body
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

  // 4. Proxy to Python container with user ID header
  const containerUrl = context.env.AGENT_CONTAINER_URL;
  if (!containerUrl) {
    return Response.json(
      { error: "AGENT_CONTAINER_URL not configured" },
      { status: 503 }
    );
  }

  try {
    const res = await fetch(`${containerUrl}/benchmark/start`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "X-User-Id": userId,
        "X-Internal-Key": context.env.INTERNAL_API_KEY || "",
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(5000),
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
    return Response.json(
      { error: "Service temporarily unavailable" },
      { status: 502 }
    );
  }
};
