/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional. Unset = local mode (always signed in, no Authorization header). */
  readonly VITE_CLERK_PUBLISHABLE_KEY?: string;
}
