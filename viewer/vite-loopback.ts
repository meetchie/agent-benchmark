// Make the dev and preview servers answer on BOTH loopback addresses.
//
// Vite's default host, "localhost", resolves to a single address, and on macOS
// that is ::1: http://localhost:5180 worked but http://127.0.0.1:5180 was
// refused. A server can only listen on one host per socket, and the usual
// fixes ("::" or 0.0.0.0) would also open the dev server, and through its
// proxy the unauthenticated local backend, to the whole network. So the server
// is pinned to 127.0.0.1 (LOOPBACK_V4) and this plugin adds a second listener
// on ::1 that hands every request and WebSocket upgrade (Vite's hot reload)
// to the same server. Nothing outside this machine can reach either.
//
// The web UI has the same plugin (web/config/loopback.ts, same code).
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import type { Plugin } from "vite";

export const LOOPBACK_V4 = "127.0.0.1";
export const LOOPBACK_V6 = "::1";

type Warn = (message: string) => void;

/** Listen on ::1 at the port `primary` got, forwarding to it. Does nothing unless primary is on 127.0.0.1. */
export function mirrorOnIpv6(primary: Server, warn: Warn): void {
  primary.once("listening", () => {
    const addr = primary.address() as AddressInfo | string | null;
    if (!addr || typeof addr === "string" || addr.address !== LOOPBACK_V4) return;

    const mirror = createServer();
    mirror.on("request", (req, res) => primary.emit("request", req, res));
    mirror.on("upgrade", (req, socket, head) => primary.emit("upgrade", req, socket, head));
    mirror.on("error", (err: NodeJS.ErrnoException) => {
      // No IPv6 on this machine: 127.0.0.1 is all there is, which is fine.
      if (err.code === "EADDRNOTAVAIL" || err.code === "EAFNOSUPPORT") return;
      if (err.code === "EADDRINUSE") {
        warn(
          `Port ${addr.port} is already in use on [${LOOPBACK_V6}]. ` +
            `http://localhost:${addr.port} may reach that other server; use http://${LOOPBACK_V4}:${addr.port}.`
        );
        return;
      }
      warn(`Could not also listen on [${LOOPBACK_V6}]:${addr.port}: ${err.message}`);
    });
    mirror.listen(addr.port, LOOPBACK_V6);
    primary.once("close", () => {
      mirror.close();
      mirror.closeAllConnections();
    });
  });
}

/** Vite plugin: add the ::1 listener to the dev server and to `vite preview`. */
export function loopbackBothAddresses(): Plugin {
  return {
    name: "agent-benchmark:loopback-both",
    configureServer(server) {
      if (server.httpServer) mirrorOnIpv6(server.httpServer as Server, (m) => server.config.logger.warn(m));
    },
    configurePreviewServer(server) {
      mirrorOnIpv6(server.httpServer as Server, (m) => server.config.logger.warn(m));
    },
  };
}
