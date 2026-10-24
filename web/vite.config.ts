import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { ENV_PREFIXES, apiProxy, apiUrl, authAlias, devPort, repoRoot } from "./config/vite-helpers";

export default defineConfig(({ mode }) => {
  // .env at the repository root (also read by the backend) plus the shell.
  const env = loadEnv(mode, repoRoot, ENV_PREFIXES);

  // The browser calls /api/benchmark/*; Vite forwards them to the Python
  // backend (BENCHMARK_API_URL), exactly as the Cloudflare functions did in
  // the hosted setup. Same for `vite preview`.
  const server = {
    port: devPort(env),
    strictPort: true,
    proxy: apiProxy(apiUrl(env)),
  };

  return {
    plugins: [react()],
    envDir: repoRoot,
    resolve: { alias: authAlias(env) },
    build: { outDir: "dist" },
    server,
    preview: server,
  };
});
