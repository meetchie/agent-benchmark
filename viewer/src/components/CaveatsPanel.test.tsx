import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CAVEATS, CaveatsPanel } from "./CaveatsPanel";

describe("CaveatsPanel", () => {
  const html = renderToStaticMarkup(<CaveatsPanel />);
  const text = html.replace(/<[^>]+>/g, " ").replace(/&quot;/g, '"').replace(/\s+/g, " ");

  it("lists all six caveats", () => {
    expect(CAVEATS).toHaveLength(6);
    expect((html.match(/<li>/g) ?? []).length).toBe(6);
  });

  it("says each thing the headline leaves out", () => {
    expect(text).toMatch(/hand-mapped/);
    expect(text).toMatch(/25 mapping versions/);
    expect(text).toMatch(/VIP check/);
    expect(text).toMatch(/BrowserUse had no mapping/);
    expect(text).toMatch(/Rindler tool vocabulary/);
    expect(text).toMatch(/Browserbase cloud browser with a 30-step cap/);
    expect(text).toMatch(/local Playwright with 25/);
    expect(text).toMatch(/gpt-4o-mini/);
    expect(text).toMatch(/own final report/);
    expect(text).toMatch(/One site, one task, one night/);
    expect(text).toMatch(/23, not 25/);
  });
});
