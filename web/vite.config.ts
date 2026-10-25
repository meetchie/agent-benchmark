import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { ENV_PREFIXES, apiProxy, apiUrl, authAlias, devPort, repoRoot } from "./config/vite-helpers";
import { LOOPBACK_V4, loopbackBothAddresses } from "./config/loopback";

export default defineConfig(({ mode }) => {
  // .env at the repository root (also read by the backend) plus the shell.
  const env = loadEnv(mode, repoRoot, ENV_PREFIXES);

  // The browser calls /api/benchmark/*; Vite forwards them to the Python
  // backend (BENCHMARK_API_URL), exactly as the Cloudflare functions did in
  // the hosted setup. Same for `vite preview`.
  //
  // Both http://127.0.0.1:<port> and http://localhost:<port> (which can mean
  // ::1) answer; see config/loopback.ts. The server is never exposed beyond
  // this machine.
  const server = {
    host: LOOPBACK_V4,
    port: devPort(env),
    strictPort: true,
    proxy: apiProxy(apiUrl(env)),
  };

  return {
    plugins: [react(), loopbackBothAddresses()],
    envDir: repoRoot,
    resolve: { alias: authAlias(env) },
    build: { outDir: "dist" },
    server,
    preview: server,
  };
});
