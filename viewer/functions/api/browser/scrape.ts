// POST /api/browser/scrape
//
// Simple browser task using Cloudflare Browser Rendering.
// Spins up a headless browser on the edge, navigates to a URL,
// and extracts content. Fast, serverless, no container needed.
//
// Request body:
//   { "url": "https://example.com", "selector": "body" }
//
// Response:
//   { "url": "...", "title": "...", "content": "...", "elapsed_ms": 123 }

import puppeteer from "@cloudflare/puppeteer";
import type { Env } from "../../env";

interface ScrapeRequest {
  url: string;
  selector?: string; // CSS selector to extract (defaults to "body")
  waitFor?: string; // Optional CSS selector to wait for before scraping
  timeout?: number; // Navigation timeout in ms (default 15000)
}

interface ScrapeResponse {
  url: string;
  title: string;
  content: string;
  elapsed_ms: number;
}

export const onRequestPost: PagesFunction<Env> = async (context) => {
  const start = Date.now();

  let body: ScrapeRequest;
  try {
    body = await context.request.json();
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  if (!body.url) {
    return Response.json({ error: "Missing required field: url" }, { status: 400 });
  }

  const selector = body.selector ?? "body";
  const timeout = body.timeout ?? 15000;

  let browser;
  try {
    browser = await puppeteer.launch(context.env.BROWSER);
    const page = await browser.newPage();

    await page.goto(body.url, {
      waitUntil: "networkidle0",
      timeout,
    });

    // Wait for a specific element if requested
    if (body.waitFor) {
      await page.waitForSelector(body.waitFor, { timeout });
    }

    const title = await page.title();
    const content = await page.$eval(selector, (el) => el.textContent ?? "");

    const result: ScrapeResponse = {
      url: body.url,
      title,
      content: content.trim(),
      elapsed_ms: Date.now() - start,
    };

    return Response.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return Response.json(
      { error: "Browser task failed", detail: message },
      { status: 500 }
    );
  } finally {
    if (browser) {
      await browser.close();
    }
  }
};
