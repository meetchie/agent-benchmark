# Testing

```bash
make test
```

`make test` runs every suite, offline and with no key. It keeps going when one fails, then lists the failed ones and exits non-zero. `make test SUITES="server hooks"` runs only the named suites and refuses a name that isn't a suite. Each suite also runs alone as `make test-<suite>`, for example `make test-server`.

| suite | what it covers |
|---|---|
| `server` | The API, the LLM layer, the browser-use adapter, the local Rindler interpreter, the arena, the scenarios and the mappings. Some tests drive a real headless Chromium against a local fixture shop. Without a Chromium that starts they are skipped, and pytest prints why. |
| `cli` | The CLI's arms, judge and results, and the prose mapping against a local copy of the site. Its browser tests skip like the server's. It runs apart from the server suite because the two have different pytest settings. |
| `web` | The UI's tests (vitest) and a production build. |
| `viewer` | Tests for the log parser, the caveats panel and the cost chart's axis (vitest), and a production build. |
| `hooks` | The pre-commit check and its installer, in throwaway git repositories. Needs only git. |
| `scripts` | The closing message of `make setup` (it says so when `ANTHROPIC_API_KEY` in `.env` is still blank, and never prints the key), that setup starts Chromium before it says it's done, and the `SUITES` check. Needs only make and sh. |

No test calls a model API. The SDK base URLs point at a closed local port, so a stray call fails at once instead of costing money. The browser tests run against local fixture sites.

## The pre-commit check

`make setup` installs a pre-commit check, `scripts/hooks/pre-commit`, that refuses API keys and `.env` files. Only `.env.example` may be committed. The hook is copied only inside a git checkout that has no pre-commit hook yet, and `core.hooksPath` is never touched. `make install-hooks` runs just that step.
