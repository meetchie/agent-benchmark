# Limits

## Live sites drift

Every result here is a snapshot of third-party websites. A run that fails because the site changed is a failed run, not a finding. As checked on 2026-10-24:

- vhlistings.com now rejects the promo code `SPRING`, so `vhlistings_bundle_promo` can't pass on either arm today. Its cart page no longer exposes a remove control, so the `remove_from_cart` action fails. The mappings were repaired where a selector had moved (pagination, the cart listing).
- books.toscrape.com has no Add to basket button on a book's own page, so a generated task for it can fail whatever the agent does. automationexercise.com is a store where a generated task passed on the same day.
- prose.com's prices changed enough that `instructions/prose-hard.yaml` needs new answers, and the mapping can't type into a form field.

## Headless browsers get blocked

The browser is a headless Chromium on your own IP address. Sites behind a bot wall (Cloudflare, captchas, anything that fingerprints headless Chrome) may show a block page, and then the agent fails for a reason that has nothing to do with it. `BENCHMARK_HEADLESS=false` opens a visible window, which may get past some of them. The original hosted setup used headed cloud browsers (Browserbase) to avoid this. That provider is still in the code but was not run again.

## Everything else

The task generator is a model. For books.toscrape.com it answered "not a commerce site" on 2 of 5 tries, and a retry works. Its tasks can also ask for a size or an option the site doesn't offer, like the sauce-demo row in [the local runs](results.md#live-benchmark-runs), and then the run fails because of the task, not the agent.

The step budgets are not the same unit. A browser-use step is one model turn that can carry several browser actions. A Rindler step is one model turn with one tool call.

One run is an anecdote. Sampling noise on a live site is large, so use many runs before drawing a conclusion.

Real runs cost money, and the default 180 s limit can be tight for a long task. Raise `BENCHMARK_TIMEOUT_S` and the web UI reads the new limit from `/health` and waits for it.

Mappings exist for three sites: vhlistings.com and shipt.com for the arena, prose.com for the CLI. The RINDLER arm can't run anywhere else. Adding a site means writing a mapping, see [cli/README.md](../cli/README.md#adding-a-site) and [server/SETUP.md](../server/SETUP.md#adding-or-fixing-a-site-mapping).
