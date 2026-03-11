// GET /api/health
// Returns the status of all backend services.

import type { Env } from "../env";

export const onRequestGet: PagesFunction<Env> = async (context) => {
  return Response.json({
    status: "ok",
    timestamp: new Date().toISOString(),
    services: {
      browser_rendering: !!context.env.BROWSER,
      agent_container: !!context.env.AGENT_CONTAINER_URL,
    },
  });
};
