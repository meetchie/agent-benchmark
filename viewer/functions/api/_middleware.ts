// Middleware that runs before all /api/* routes.
// Useful for auth checks, CORS headers, logging, etc.

export const onRequest: PagesFunction = async (context) => {
  // Add CORS headers for local development
  const response = await context.next();

  response.headers.set("Access-Control-Allow-Origin", "*");
  response.headers.set(
    "Access-Control-Allow-Methods",
    "GET, POST, PUT, DELETE, OPTIONS"
  );
  response.headers.set(
    "Access-Control-Allow-Headers",
    "Content-Type, Authorization"
  );

  // Handle preflight
  if (context.request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: response.headers,
    });
  }

  return response;
};
