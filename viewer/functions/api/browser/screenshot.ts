// POST /api/browser/screenshot
//
// Takes a screenshot of a URL using Cloudflare Browser Rendering.
// Returns the image as base64 or as a binary response.
//
// Request body:
//   { "url": "https://example.com", "fullPage": false, "format": "base64" }
//
// Response (format: "base64"):
//   { "url": "...", "screenshot": "data:image/png;base64,...", "elapsed_ms": 123 }
//
// Response (format: "binary"):
//   Raw PNG image bytes with Content-Type: image/png

import puppeteer from "@cloudflare/puppeteer";
import type { Env } from "../../env";

interface ScreenshotRequest {
  url: string;
  fullPage?: boolean; // Capture full scrollable page (default false)
  format?: "base64" | "binary"; // Response format (default "base64")
  timeout?: number;
}

export const onRequestPost: PagesFunction<Env> = async (context) => {
  const start = Date.now();

  let body: ScreenshotRequest;
  try {
    body = await context.request.json();
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  if (!body.url) {
    return Response.json({ error: "Missing required field: url" }, { status: 400 });
  }

  const fullPage = body.fullPage ?? false;
  const format = body.format ?? "base64";
  const timeout = body.timeout ?? 15000;

  let browser;
  try {
    browser = await puppeteer.launch(context.env.BROWSER);
    const page = await browser.newPage();

    await page.setViewport({ width: 1280, height: 720 });
    await page.goto(body.url, {
      waitUntil: "networkidle0",
      timeout,
    });

    const screenshotBuffer = await page.screenshot({
      fullPage,
      type: "png",
    });

    if (format === "binary") {
      return new Response(screenshotBuffer, {
        headers: {
          "Content-Type": "image/png",
          "X-Elapsed-Ms": String(Date.now() - start),
        },
      });
    }

    // Base64 response
    const bytes = new Uint8Array(screenshotBuffer as unknown as ArrayBuffer);
    let binary = "";
    for (const byte of bytes) {
      binary += String.fromCharCode(byte);
    }
    const base64 = btoa(binary);

    return Response.json({
      url: body.url,
      screenshot: `data:image/png;base64,${base64}`,
      elapsed_ms: Date.now() - start,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return Response.json(
      { error: "Screenshot failed", detail: message },
      { status: 500 }
    );
  } finally {
    if (browser) {
      await browser.close();
    }
  }
};
