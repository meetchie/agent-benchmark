import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { authAlias } from "./config/vite-helpers";

export default defineConfig({
  plugins: [react()],
  // Tests always run in local mode (no Clerk key), whatever the shell or a
  // .env file says; a test that needs Clerk mode stubs the env itself.
  envDir: false,
  resolve: { alias: authAlias({}) },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    exclude: ["**/node_modules/**", "**/dist/**"],
    env: { VITE_CLERK_PUBLISHABLE_KEY: "" },
  },
});
