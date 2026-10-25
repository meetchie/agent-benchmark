// @vitest-environment node
//
// The dev server answers on 127.0.0.1 and on ::1 (so http://127.0.0.1:<port> and
// http://localhost:<port> both work, whichever one localhost resolves to), and
// nowhere else. Needs IPv6 loopback to assert the ::1 half; without it those
// tests are skipped.
import { createServer as createHttpServer, request, type Server } from "node:http";
import { createServer as createNetServer, type AddressInfo } from "node:net";
import { createServer, type ViteDevServer } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { LOOPBACK_V4, loopbackBothAddresses, mirrorOnIpv6 } from "../loopback";

async function ipv6LoopbackWorks(): Promise<boolean> {
  return new Promise((resolve) => {
    const probe = createNetServer();
    probe.once("error", () => resolve(false));
    probe.listen(0, "::1", () => probe.close(() => resolve(true)));
  });
}

const hasIpv6 = await ipv6LoopbackWorks();
const listening = (server: Server) => new Promise<void>((resolve) => server.once("listening", () => resolve()));
const closed = (server: Server) => new Promise<void>((resolve) => server.close(() => resolve()));

describe("dev server on both loopback addresses", () => {
  let vite: ViteDevServer;
  let port: number;

  beforeAll(async () => {
    vite = await createServer({
      configFile: false,
      root: new URL("../..", import.meta.url).pathname,
      logLevel: "silent",
      plugins: [loopbackBothAddresses()],
      server: { port: 0, host: LOOPBACK_V4 },
    });
    await vite.listen();
    port = (vite.httpServer!.address() as AddressInfo).port;
  });

  afterAll(async () => {
    await vite?.close();
  });

  it("answers on 127.0.0.1", async () => {
    const res = await fetch(`http://127.0.0.1:${port}/`);
    expect(res.status).toBe(200);
    expect(await res.text()).toContain('<div id="root">');
  });

  it.skipIf(!hasIpv6)("answers on [::1] with the same page", async () => {
    const v4 = await (await fetch(`http://127.0.0.1:${port}/`)).text();
    const res = await fetch(`http://[::1]:${port}/`);
    expect(res.status).toBe(200);
    expect(await res.text()).toBe(v4);
  });

  it.skipIf(!hasIpv6)("carries hot-reload WebSocket upgrades over [::1] too", async () => {
    const status = await new Promise<number>((resolve, reject) => {
      const req = request({
        host: "::1",
        port,
        headers: {
          Connection: "Upgrade",
          Upgrade: "websocket",
          "Sec-WebSocket-Version": "13",
          "Sec-WebSocket-Key": Buffer.from("0123456789abcdef").toString("base64"),
          "Sec-WebSocket-Protocol": "vite-hmr",
        },
      });
      req.on("upgrade", (res, socket) => {
        socket.destroy();
        resolve(res.statusCode ?? 0);
      });
      req.on("response", (res) => resolve(res.statusCode ?? 0));
      req.on("error", reject);
      req.end();
    });
    expect(status).toBe(101);
  });

  it("is not reachable on any other interface address", () => {
    // Bound to loopback only: the primary server's address is 127.0.0.1, not 0.0.0.0 or ::.
    expect((vite.httpServer!.address() as AddressInfo).address).toBe(LOOPBACK_V4);
  });
});

describe("mirrorOnIpv6", () => {
  it.skipIf(!hasIpv6)("stops listening on [::1] when the primary closes", async () => {
    const primary = createHttpServer((_req, res) => res.end("ok"));
    mirrorOnIpv6(primary, () => {});
    primary.listen(0, LOOPBACK_V4);
    await listening(primary);
    const port = (primary.address() as AddressInfo).port;
    // Wait for the mirror to come up.
    for (let i = 0; i < 50; i++) {
      const up = await fetch(`http://[::1]:${port}/`).then(() => true, () => false);
      if (up) break;
      await new Promise((r) => setTimeout(r, 20));
    }
    expect(await (await fetch(`http://[::1]:${port}/`)).text()).toBe("ok");

    primary.closeAllConnections();
    await closed(primary);
    await new Promise((r) => setTimeout(r, 50));
    await expect(fetch(`http://[::1]:${port}/`)).rejects.toThrow();
  });

  it.skipIf(!hasIpv6)("warns, and keeps serving on 127.0.0.1, when [::1] is taken by another server", async () => {
    const blocker = createHttpServer((_req, res) => res.end("someone else"));
    blocker.listen(0, "::1");
    await listening(blocker);
    const port = (blocker.address() as AddressInfo).port;

    const warnings: string[] = [];
    const primary = createHttpServer((_req, res) => res.end("ok"));
    mirrorOnIpv6(primary, (m) => warnings.push(m));
    primary.listen(port, LOOPBACK_V4);
    await listening(primary);
    for (let i = 0; i < 50 && warnings.length === 0; i++) await new Promise((r) => setTimeout(r, 20));

    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toMatch(new RegExp(`Port ${port} is already in use on \\[::1\\]`));
    expect(await (await fetch(`http://127.0.0.1:${port}/`)).text()).toBe("ok");
    expect(await (await fetch(`http://[::1]:${port}/`)).text()).toBe("someone else");

    primary.closeAllConnections();
    blocker.closeAllConnections();
    await Promise.all([closed(primary), closed(blocker)]);
  });

  it("does nothing when the primary is not on 127.0.0.1", async () => {
    const primary = createHttpServer((_req, res) => res.end("ok"));
    const warnings: string[] = [];
    mirrorOnIpv6(primary, (m) => warnings.push(m));
    primary.listen(0, hasIpv6 ? "::1" : LOOPBACK_V4);
    await listening(primary);
    await new Promise((r) => setTimeout(r, 50));
    expect(warnings).toEqual([]);
    primary.closeAllConnections();
    await closed(primary);
  });
});
