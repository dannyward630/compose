# Verify

`fast-coding verify --project <name>` runs locally and pushes nothing.
Its only network calls are model APIs.

## Config

`.fast-coding/<project>/verify.json`:

```json
{
  "checks": ["uv run ruff check .", "node --test 'tests/**/*.test.js'"],
  "docs": ["README.md", "DESIGN.md"],
  "perspectives": ["correctness", "security", "spec", "docs"],
  "jev_acceptance": true, "acceptance_threshold": 0.6, "acceptance_gate": false,
  "e2e_setup": "python -m server.server --port $E2E_PORT &", "e2e_setup_wait": 3, "e2e_env": {"API_KEY": "..."},
  "e2e": [{"name": "signup", "url": "http://127.0.0.1:$E2E_PORT/", "goal": "Sign up as a new user.",
           "assert": "python .fast-coding/<project>/e2e/check_signup.py"}],
  "review": true, "review_base": "main",
  "review_context": "Design facts reviewers must respect."
}
```

`fix_model` overrides the fix model, which defaults to the implementer.
`env_file` replaces `~/.fast-coding/.env` for this project.

## Stages

1. **checks**: lint, unit tests, and smoke checks; exact and cheap, run first.
2. **review**: one fast-model review per perspective, then a confirmation call per high or medium finding that must quote the code; only confirmed highs fail.
3. **jev**: one MET / NOT_MET / UNCLEAR question per acceptance criterion; failures above the threshold become findings.
4. **e2e**: jev drives a real browser to each case's goal, then the case's `assert` checks the real DOM or log.
5. **fix**: confirmed findings go to the fix model; protected files are reverted, and stages rerun up to `--fix` rounds, then escalate.

Review, jev, and e2e run in parallel after checks.
Every run ends with time and cost per provider.

## e2e rules

- Each stage gets fresh ports `$E2E_PORT` and `$E2E_CLIENT_PORT`, expanded in `url` and `goal` and set for `e2e_setup`, `driver`, and `assert`; never hardcode a port.
- Start servers in `e2e_setup` with a plain `&`.
- Keep driver and assert scripts under `.fast-coding/<project>/e2e/`.
- Each stage launches its own Chromium with a throwaway profile, so verify never touches your real Chrome; it is visible, and only fast-coding's own test suite runs it headless.
- When the stage ends it stops everything it started: setup processes, its browser and that browser's harness daemons, and anything listening on its ports.

A failure caused by the harness (a jev or browser crash, a missing tool, a port in use) is reported as `TOOL ERROR`, retried once, and never sent to a fix round.

A case with a `driver` command runs the project's own browser driver instead of jev.

## Extensions

The stage's own browser has no extension.
Launch the extension's Chromium in `e2e_setup` and point jev at it with `e2e_env`:

```json
{
  "e2e_setup": "BP_PORT=9333 bp launch about:blank --ext path/to/extension/dist --profile .fast-coding/<project>/bp-profile",
  "e2e_setup_wait": 4,
  "e2e_env": {"BU_CDP_URL": "http://127.0.0.1:9333", "BU_NAME": "bp9333"}
}
```

## jev

`jev/` is the browser agent the e2e stage drives.
It came from [jev-ultrafast](https://github.com/browser-use/jev-ultrafast) at `05b841f`: the library (`jev_ultrafast/`) and its tests, nothing else.

- It is its own uv project (Python 3.12+, `browser-harness`, `httpx`), so `bin/fast-coding` stays standard library only.
- The CLI runs it with `uv run` from `jev/` and passes `~/.fast-coding/.env` when it exists.
- Its tests: `cd jev && uv run pytest`.

jev-ultrafast keeps the demo CLI, its web UI, the examples, and the scripts.
