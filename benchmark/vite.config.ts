import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import yaml from "@rollup/plugin-yaml";

export default defineConfig({
  plugins: [react(), yaml()],
  build: {
    outDir: "dist",
  },
  server: {
    proxy: {
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
    },
  },
});
