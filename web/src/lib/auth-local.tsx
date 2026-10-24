/**
 * Local stand-in for the parts of @clerk/clerk-react this app uses.
 *
 * vite.config.ts aliases "@clerk/clerk-react" to this file when
 * VITE_CLERK_PUBLISHABLE_KEY is not set, so the app runs as an always
 * signed-in local user with no account, no network call and no token.
 * Components keep importing from "@clerk/clerk-react" unchanged.
 */
import type { ReactNode } from "react";

export const LOCAL_USER_ID = "local";

// Module-level and stable: App puts getToken in effect dependency lists, so a
// new function on every render would re-run those effects forever.
const getToken = async (): Promise<string | null> => null;

const localAuth = {
  isLoaded: true,
  isSignedIn: true,
  userId: LOCAL_USER_ID,
  getToken,
} as const;

export function useAuth() {
  return localAuth;
}

export function ClerkProvider({ children }: { children?: ReactNode; publishableKey?: string }) {
  return <>{children}</>;
}

export function SignedIn({ children }: { children?: ReactNode }) {
  return <>{children}</>;
}

export function SignedOut(_props: { children?: ReactNode }) {
  return null;
}

export function UserButton(_props: Record<string, unknown>) {
  return null;
}

export function AuthenticateWithRedirectCallback() {
  return null;
}

// The sign-in / sign-up forms are never mounted while signed in. These are
// inert so that a stray render does nothing rather than throw.
const inertSignIn = { isLoaded: false, signIn: undefined, setActive: undefined } as const;
const inertSignUp = { isLoaded: false, signUp: undefined, setActive: undefined } as const;

export function useSignIn() {
  return inertSignIn;
}

export function useSignUp() {
  return inertSignUp;
}
