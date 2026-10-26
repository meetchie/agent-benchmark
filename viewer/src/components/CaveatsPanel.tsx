// What the headline numbers do not say. Shown inside the hero, right under the
// 98.3% vs 1.7% boxes, so that a screenshot of the headline carries it too.
// Every item is checked against the archived logs and the original arena code;
// see "The seven caveats" in docs/results.md for the detail.

export const CAVEATS: ReadonlyArray<{ lead: string; text: string }> = [
  {
    lead: "Mapped against unmapped.",
    text:
      "Rindler drove a hand-mapped site (25 mapping versions tuned on this exact task), and the mapping's own cleanup step is what satisfies the VIP check. BrowserUse had no mapping.",
  },
  {
    lead: "Rindler wording in both prompts.",
    text: "Both agents got task text using Rindler tool vocabulary (\"view_cart\", \"Start a session\").",
  },
  {
    lead: "Different setups.",
    text: "BrowserUse ran on a Browserbase cloud browser with a 30-step cap, Rindler on local Playwright with 25.",
  },
  {
    lead: "A weak judge.",
    text: "gpt-4o-mini read the agent's own final report. It never looked at the cart.",
  },
  {
    lead: "One site, one task, one night.",
    text: "60 runs per arm against a live third-party store on 2026-03-31. The store may have changed since.",
  },
  {
    lead: "Hand-written funnel.",
    text:
      "The funnel stages and \"dark pattern\" labels were written by hand. The judge criteria give 23, not 25, for \"Added 3 items\".",
  },
];

export function CaveatsPanel() {
  return (
    <aside className="caveats" aria-label="Caveats">
      <h2 className="caveats-title">Read the numbers with these caveats</h2>
      <ul className="caveats-list">
        {CAVEATS.map((c) => (
          <li key={c.lead}>
            <strong>{c.lead}</strong> {c.text}
          </li>
        ))}
      </ul>
    </aside>
  );
}
