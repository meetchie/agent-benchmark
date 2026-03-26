// GET /api/benchmark/quota
// Returns remaining runs and reset timer for the authenticated user.

import { verifyToken } from "@clerk/backend";
import type { Env } from "../../env";

export const onRequestGet: PagesFunction<Env> = async (context) => {
  const authHeader = context.request.headers.get("Authorization") ?? "";
  const token = authHeader.startsWith("Bearer ") ? authHeader.slice(7) : "";
  if (!token) {
    return Response.json({ error: "Missing Authorization header" }, { status: 401 });
  }

  let userId: string;
  try {
    const payload = await verifyToken(token, {
      secretKey: context.env.CLERK_SECRET_KEY,
    });
    userId = payload.sub;
  } catch {
    return Response.json({ error: "Invalid or expired token" }, { status: 401 });
  }

  const containerUrl = context.env.AGENT_CONTAINER_URL;
  if (!containerUrl) {
    return Response.json({ error: "AGENT_CONTAINER_URL not configured" }, { status: 503 });
  }

  try {
    const res = await fetch(`${containerUrl}/benchmark/quota`, {
      headers: {
        Authorization: `Bearer ${token}`,
        "X-User-Id": userId,
        "X-Internal-Key": context.env.INTERNAL_API_KEY || "",
      },
      signal: AbortSignal.timeout(5000),
    });

    if (!res.ok) {
      const text = await res.text();
      return new Response(text, { status: res.status, headers: { "Content-Type": "application/json" } });
    }

    return Response.json(await res.json());
  } catch {
    return Response.json({ error: "Service temporarily unavailable" }, { status: 502 });
  }
};
