# Verify

Verify gives you confidence that a stack works before anyone reviews it or pushes it.
It runs on your machine, pushes nothing, and makes no network calls except to model APIs.

Run it with `compose verify --project <name>`.

## Config

Verify reads `.compose/<project>/verify.json`.

```json
{
  "checks": ["uv run ruff check .", "node --test 'tests/**/*.test.js'"],
  "docs": ["README.md", "DESIGN.md"],
  "perspectives": ["correctness", "security", "spec", "docs"],
  "jev_acceptance": true, "acceptance_threshold": 0.6, "acceptance_gate": false,
  "e2e_setup": "python -m server.server --port $E2E_PORT &", "e2e_setup_wait": 3, "e2e_env": {"API_KEY": "..."},
  "e2e": [{"name": "signup", "url": "http://127.0.0.1:$E2E_PORT/", "goal": "Sign up as a new user.",
           "assert": "python .compose/<project>/e2e/check_signup.py"}],
  "review": true, "review_base": "main",
  "review_context": "Design facts reviewers must respect."
}
```

`commit_convention` (`{"types": [...], "example": "feat: ..."}`) makes every commit the CLI makes, and every teammate brief, start with a type prefix: tests are `test`, docs `docs`, dependencies and config `chore` or `build`, fixes `fix`, the rest `feat`.
`fix_model` overrides the fix model, which defaults to the implementer.
`env_file` replaces `~/.compose/.env` for this project.

## Stages

1. **checks** runs lint, unit tests, and smoke checks.
   These are exact and cheap, so they run first.
2. **review** makes one fast-model review per perspective.
   Each high or medium finding then gets a confirmation call that must quote the code, and only confirmed highs fail.
3. **jev** asks one MET / NOT_MET / UNCLEAR question per acceptance criterion.
   Failures above the threshold become findings.
4. **e2e** has jev drive a real browser to each case's goal.
   Then the case's `assert` checks the real DOM or log.
5. **fix** sends confirmed findings to the fix model.
   Protected files are reverted, and the stages rerun for up to `--fix` rounds before they escalate.

Review, jev, and e2e run in parallel after checks.
Every run ends with time and cost per provider.

## e2e rules

- Each stage gets fresh ports `$E2E_PORT` and `$E2E_CLIENT_PORT`.
  Verify expands them in `url` and `goal` and sets them for `e2e_setup`, `driver`, and `assert`.
  Never hardcode a port.
- Start servers in `e2e_setup` with a plain `&`.
- The cases start once every port `e2e_setup` names (`$E2E_PORT`, `$E2E_CLIENT_PORT`) accepts a connection, waiting up to 60 s, or `e2e_setup_wait` if longer.
  A setup that names neither, such as an extension's browser on a pinned port, waits a fixed `e2e_setup_wait` seconds.
  A case's own `setup` works the same way with `setup_wait`.
- Keep driver and assert scripts under `.compose/<project>/e2e/`.
- Each stage launches its own Chromium with a throwaway profile, so verify never touches your real Chrome.
  The browser is visible, and only the `compose` test suite runs it headless.
- When the stage ends, it stops everything it started.
  That covers setup processes, its browser and that browser's harness daemons, and anything listening on its ports.

When the harness itself fails, for example a jev or browser crash, a missing tool, or a port in use, verify reports `TOOL ERROR` and retries once.
It never sends that failure to a fix round.

A case with a `driver` command runs the project's own browser driver instead of jev.

## Extensions

The stage's own browser has no extension.
To test one, launch the extension's Chromium in `e2e_setup` and point jev at it with `e2e_env`.

```json
{
  "e2e_setup": "BP_PORT=9333 bp launch about:blank --ext path/to/extension/dist --profile .compose/<project>/bp-profile",
  "e2e_setup_wait": 4,
  "e2e_env": {"BU_CDP_URL": "http://127.0.0.1:9333", "BU_NAME": "bp9333"}
}
```

## jev

`jev/` is the browser agent the e2e stage drives.
It came from [jev-ultrafast](https://github.com/browser-use/jev-ultrafast) at `05b841f`, and it holds the library (`jev_ultrafast/`) and its tests, nothing else.

- It is its own uv project (Python 3.12+, `browser-harness`, `httpx`), so `bin/compose` stays standard library only.
- The CLI runs it with `uv run` from `jev/` and passes `~/.compose/.env` when it exists.
- You run its tests with `cd jev && uv run pytest`.

jev-ultrafast keeps the demo CLI, its web UI, the examples, and the scripts.
