import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
  server: {
    // Local dev: Vite proxies API calls directly to the Python FastAPI container (http://localhost:8000).
    // This bypasses the Cloudflare Functions (functions/api/benchmark/) which are used in production only.
    // Reason: wrangler v3.114.17 conflicts when wrangler.toml has pages_build_output_dir set + proxy command.
    proxy: {
      // Auth routes
      "/api/auth": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path: string) => path.replace("/api/auth", "/auth"),
      },
      // Rewrite Cloudflare function paths to Python container paths for local dev
      "/api/benchmark/status": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) =>
          path.replace("/api/benchmark/status", "/benchmark/status"),
      },
      "/api/benchmark/run": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: () => "/benchmark/start",
      },
      "/api/benchmark/generate-tasks": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: () => "/benchmark/generate-tasks",
      },
    },
  },
});
