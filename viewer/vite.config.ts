import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { LOOPBACK_V4, loopbackBothAddresses } from "./vite-loopback";

// Dev and preview servers answer on both http://127.0.0.1:<port> and
// http://localhost:<port> (which can mean ::1), and only on this machine.
// See vite-loopback.ts.
const server = { host: LOOPBACK_V4 };

export default defineConfig({
  plugins: [react(), loopbackBothAddresses()],
  build: {
    outDir: "dist",
  },
  server,
  preview: server,
});
