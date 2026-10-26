# The live benchmark

The web app in `web/` and the FastAPI server in `server/`. Start both with `make dev` and open http://localhost:5180. `make demo` runs the same thing with canned runs and no key.

## A run

You give the web app a site URL. The server fetches the page and a model proposes three tasks for it. Only commerce sites get tasks, anything else answers 422. You pick one, and the server starts a browser-use agent on `BENCHMARK_AGENT_MODEL` in a throwaway headless Chromium. The UI polls the run and shows each step as it happens.

The server refuses a URL that doesn't resolve, or that points at this machine or an internal address in any notation, IPv4-mapped IPv6 included. The 422 says which: "Could not resolve this host: ..." or "Invalid or disallowed URL: ...". When the server fetches the page for task generation it follows redirects one at a time and checks each target the same way. The agent itself browses like any browser, so once it is on the site it can follow the site's own links and redirects.

<p align="center">
  <img src="images/web-tasks.jpg" width="560" alt="The setup screen of the web UI with https://automationexercise.com pasted in and three tasks the model generated for it, such as 'Add 4 slim fit jeans via Men category', above a Run Benchmark button">
</p>

## Scoring

When the agent stops, a judge model (`BENCHMARK_JUDGE_MODEL`) reads:

- the task, and the list of steps with their timings;
- under each step, the agent's evaluation of the step before, and each browser action that ran with what browser-use returned for it: page text for an action that extracts or reads the page (cut to 600 characters), a short note for a click or a navigation (`Clicked a "View Cart"`), or an error;
- after the steps, the agent's final report, if the agent finished on its own.

It never sees the page or a screenshot. A check the task asks for, such as a quantity, a price or a total, counts only when that text says what the agent found. A report that only says it worked doesn't count. The agent wrote the evaluations and the report, and the judge is told the report is the agent's claim. A pass means the judge believed what the agent wrote. Nobody looked at the site. The status reply and the run file keep the report the judge read as `final_report`, and the success flag the agent set with it as `agent_reported_success`.

A task that can't be done as written (a product the site doesn't have, a code it rejects) is a fail even when the agent finds that out and says so. A run whose agent reported that it did not succeed is never a pass, whatever the judge says.

## Run states

| state | meaning |
|---|---|
| `pass` | The judge says the agent fully completed the task as written, verification included, with the result of every check the task asks for in the steps or the final report, and the agent did not report that it failed. |
| `fail` | The agent ran to the end and the judge says it did not complete the task. |
| `too_slow` | The agent was still going after `BENCHMARK_TIMEOUT_S` (default 180 s) and was stopped. The judge still reads the steps it took. There is no final report, and no phase is marked failed. |
| `error` | The run couldn't be judged pass or fail. The model refused part-way, every step the model drove failed (a bad API key, say), the judge itself failed (key rejected, rate limit, timeout), Chromium is missing or can't start, a setting is invalid, the run crashed, you cancelled it, or the server stopped during it. The message says which. If the agent had taken steps, as in a refusal or a crash part-way, the judge still reads them and the results card shows its summary and phases under the message. |

Cancelling keeps the bill. A cancelled run ends as `error` with "Run cancelled by user." and keeps the time, tokens and cost it had used by then, in the status reply and in the saved run file, because those model calls were paid for.

## Phases

The judge also groups the steps into 3 to 6 phases named for what the user was trying to do ("Find the right yoga mat", "Verify cart contents"). It is told to flag a phase as slow when it took more than 45 seconds or showed pointless retries, and to flag the slowest one even if nothing was slow. It usually does, but nothing enforces it. On a failed run it is told to flag the phase where things went wrong as failed: the agent's mistake, or the point where it found the task couldn't be done. The server keeps at most one failed phase, and none on a pass or a `too_slow` run.

## The screens

The results screen shows the verdict, the summary, the agent's final report and whether the agent said it succeeded, the phases, time, steps, tokens, and the dollar cost of the agent's tokens at the agent model's prices. A model without a price table shows tokens only.

![The web UI after a real run on automationexercise.com for the task 'Add 4 slim fit jeans via Men category': the last page the agent saw (the site's shopping cart), Time 0:53, Steps 13, Cost $0.23, Tokens 298,283, agent model claude-sonnet-5-5, and the last steps of the run's timeline](images/web-finished-run.jpg)

<sub>A real run on automationexercise.com on 2026-10-25. The judge passed it on the step text alone, before it read everything [Scoring](#scoring) lists. The results card that opens when the agent stops is closed here, and **View Results** reopens its verdict, summary and phases.</sub>

While the agent is working, Cost and Tokens read "—". Both are the backend's numbers and arrive when the agent stops, so the UI estimates nothing. Tokens count everything billed: the prompt with its cache reads, cache writes and the output.

The UI waits as long as the server does. It polls a run for `BENCHMARK_TIMEOUT_S` plus 180 s for the judge, at least 5 minutes, or 10 minutes if it can't read the limit, before it reports a lost connection. It reads the limit from `GET /health`, so raising it on the server raises it in the UI.

With `DEMO_MODE=true` every screen after the landing page carries a "Demo mode: canned runs, no real agent or API calls" banner. A canned run plays the same generic steps whichever task you pick: open the site, find the product, add it to the cart, check the cart.

## Saved runs and the API

Finished runs are saved as JSON in `server/runs/` (gitignored). If the server stops during a run, it cancels the run, closes its browser and saves it as an `error`. A run file still marked `running` because the server was killed outright is marked `error` the next time the server starts.

The API is `POST /benchmark/start`, `GET /benchmark/status/{id}`, `GET /benchmark/frame/{id}` (the newest picture of the run's page), `POST /benchmark/cancel/{id}`, `POST /benchmark/generate-tasks`, `GET /benchmark/quota` and `GET /health`. `generate-tasks` takes at most 5 requests a minute from one address, refused ones included, and the sixth answers 429. `/health` reports the provider, the models, the auth mode, `demo_mode` and `timeout_s` (`BENCHMARK_TIMEOUT_S` in whole seconds), and never a key.

[web/README.md](../web/README.md#what-the-ui-expects-from-the-backend) maps every UI call to its backend route.

## Starting and stopping

`make dev` is `scripts/dev.sh`. It starts the backend on the port in `BENCHMARK_API_URL` (default 8000) and the web UI on `BENCHMARK_WEB_PORT` (default 5180), so a busy port is a setting, not a code change. On Ctrl-C or any other exit it stops exactly those two servers by PID, and what they spawned.

The backend first gets up to 15 seconds to end the runs in progress. Each closes its browser and is saved as an `error` that says the server stopped. Anything of the backend's still running after that, a browser whose parent died included, is stopped by its process group.

To stop it from a script, send SIGTERM to `make`, or SIGINT to its whole process group as Ctrl-C does. make doesn't pass on a SIGINT sent to it alone.
