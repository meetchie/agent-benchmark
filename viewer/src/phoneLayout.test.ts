import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Read from disk: vitest hands CSS imports to tests as empty strings, ?raw included.
const css = readFileSync(new URL("./App.css", import.meta.url), "utf8");

// The phone rules live in the 768 px media query of App.css. Without them both pages
// scrolled sideways on a 360-390 px screen and the step timeline's Action column
// came out 0 px wide. Checked in a browser at 360 and 390 px when they were written;
// these tests keep the rules that made it fit.

function mediaBlock(source: string, query: string): string {
  const start = source.indexOf(`@media ${query} {`);
  if (start < 0) throw new Error(`no @media ${query} block`);
  let depth = 0;
  for (let i = source.indexOf("{", start); i < source.length; i++) {
    if (source[i] === "{") depth++;
    if (source[i] === "}" && --depth === 0) return source.slice(source.indexOf("{", start) + 1, i);
  }
  throw new Error(`unclosed @media ${query} block`);
}

/** Declarations for a selector inside a block, merged over every rule that lists it. */
function declarations(block: string, selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  const withoutComments = block.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const [, selectors, body] of withoutComments.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (!selectors.split(",").map((s) => s.trim()).includes(selector)) continue;
    for (const decl of body.split(";")) {
      const colon = decl.indexOf(":");
      if (colon > 0) out[decl.slice(0, colon).trim()] = decl.slice(colon + 1).trim();
    }
  }
  return out;
}

const phone = mediaBlock(css, "(max-width: 768px)");
const REM = 16;

function px(value: string): number {
  if (value.endsWith("rem")) return parseFloat(value) * REM;
  if (value.endsWith("px")) return parseFloat(value);
  throw new Error(`not a fixed length: ${value}`);
}

describe("the phone layout", () => {
  it("stacks the three task steps on the Results page", () => {
    expect(declarations(phone, ".scenario-steps")["grid-template-columns"]).toBe("1fr");
  });

  it("lets the log dashboard column shrink to the screen", () => {
    expect(declarations(phone, ".dashboard-grid")["grid-template-columns"]).toBe("minmax(0, 1fr)");
    for (const sel of [".grid-left", ".grid-right", ".panel"]) {
      expect(declarations(phone, sel)["min-width"], sel).toBe("0");
    }
  });

  it("lets the run picker shrink instead of holding a fixed minimum width", () => {
    expect(declarations(phone, ".log-selector-trigger")["min-width"]).toBe("0");
    expect(declarations(phone, ".log-section-controls .log-selector-trigger")["min-width"]).toBe("0");
    expect(declarations(phone, ".header-controls")["flex-wrap"]).toBe("wrap");
  });

  it("leaves the step timeline's Action column room on a 360 px screen", () => {
    const row = declarations(phone, ".timeline-row");
    const header = declarations(phone, ".timeline-panel .timeline-header-row");
    expect(header["grid-template-columns"]).toBe(row["grid-template-columns"]);
    expect(declarations(phone, ".td-bar").display).toBe("none");

    const tracks = row["grid-template-columns"].split(/\s+(?![^(]*\))/);
    expect(tracks[1]).toBe("minmax(0, 1fr)");
    const fixed = tracks.filter((_, i) => i !== 1).reduce((sum, t) => sum + px(t), 0);
    const gaps = (tracks.length - 1) * px(row.gap);

    // Row width on a 360 px screen: the page gutter and the panel padding on each side,
    // the panel border, then the row's own padding.
    const gutter = px(declarations(phone, ".app-main").padding.split(/\s+/)[1]);
    const panelPad = px(declarations(phone, ".panel").padding);
    const rowWidth = 360 - 2 * gutter - 2 * panelPad - 2 - px(row["padding-left"]) - px(row["padding-right"]);
    // Enough for an action name such as "view_cart" or "add_to_cart" in full.
    expect(rowWidth - fixed - gaps).toBeGreaterThanOrEqual(80);
  });
});
