# Provenance

This was built at Rindler from December 2025 to March 2026, with later commits to the web app up to August 2026, by Michelle Serrano (`meetchie`), Michael Serrano and Arthur De Los Santos. Counting the original commits, from December 2025 to August 2026, the web app is mostly Michelle's at 71 of 91, the server and the arena mostly Michael's at 114 of 159, and the CLI Arthur's at 35 of 36. To check:

```bash
git shortlog -sn --before=2026-09-01 HEAD -- <folder>
```

## The history

The repository keeps the original commit history, 337 commits re-created with their original authors and dates: 326 from December 2025 to March 2026 and 11 later ones to the web app from April to August 2026. All three authors' commits use their GitHub noreply addresses.

It was extracted from the company's monorepo in October 2026 and then adapted to run standalone. The hosted pieces were replaced with local ones: Anthropic models instead of OpenAI, a local file store instead of the Rindler database, an in-process mapping interpreter instead of the Rindler servers, and a no-sign-in local mode with Clerk optional. The commits from October 2026 are that adaptation.

The hosted setup is retired and was not kept. Four March commits that only touched it are not in this history either: two edits of its notes, a note about it in the code, and the merge of one of them.

Commit messages were lightly normalized at extraction. Pull-request merge subjects became plain branch merges, trailing pull-request numbers were dropped, and most co-author trailers were removed. Some commit messages and seed-file comments were also reworded or trimmed to leave out internal company details.

## Redactions

Some values were redacted when the history was extracted: two street addresses that were used as task input, staff email addresses, and third-party account identifiers, for example the Browserbase account in session replay links. In the six Rindler context logs in `server/arena_logs/`, two entries for internal tools of Rindler's hosted platform were removed from the list of registered tools.
