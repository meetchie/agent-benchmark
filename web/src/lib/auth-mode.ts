/**
 * Whether the app talks to a real Clerk instance.
 *
 * Without VITE_CLERK_PUBLISHABLE_KEY the build aliases "@clerk/clerk-react" to
 * ./auth-local.tsx (see config/vite-helpers.ts): the visitor is always signed
 * in, there is no token, and no Authorization header is sent. The backend
 * must then run with AUTH_MODE=none. A function rather than a constant so a
 * test can flip the mode with vi.stubEnv.
 */
export function isClerkMode(): boolean {
  return Boolean((import.meta.env.VITE_CLERK_PUBLISHABLE_KEY ?? "").trim());
}
