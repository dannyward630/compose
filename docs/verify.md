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
`checks` also gate `compose stack --submit`: each layer is checked on its own tree, bottom up, and a failing layer refuses the submit.
`land_method` (`squash`, `merge`, or `rebase`; default `squash`) is how `compose land` merges each PR.
`review_base` is the branch the project's work is reviewed and stacked against: `init` records the branch the project started from.
One that names no branch (a project made before init recorded it holds `main`, also in a repository whose trunk is `master`) reads as the repository's default branch.
`fix_model` overrides the fix model, which defaults to the implementer.
`env_file` replaces `~/.compose/.env` for this project.

## Stages

1. **checks** runs lint, unit tests, and smoke checks.
   These are exact and cheap, so they run first.
   A fix round runs only the `test:` commands of the tasks whose files its fix changed, and the full checks once, after every other stage passed.
   A fix that changes a file no task names runs the full checks.
2. **review** makes one fast-model review per perspective.
   Each high or medium finding then gets a confirmation call that must quote the wrong line and say how it must read.
   A quote that is not in the code, or a line that must read as it already does, drops the finding, and only confirmed highs fail.
3. **jev** asks one MET / NOT_MET / UNCLEAR question per acceptance criterion.
   Failures above the threshold become findings.
4. **e2e** has jev drive a real browser to each case's goal.
   Then the case's `assert` checks the real DOM or log.
5. **fix** sends confirmed findings to the fix model.
   Protected files are reverted, and the stages rerun for up to `--fix` rounds before they escalate.
   A fix commit holds only the files the fixer changed: never the agent wiring (`.claude/settings.json`), which a session hook rewrites, nor files a check left behind.
   Uncommitted changes of your own skip the fix, so a bad fix can always be reverted.
   A verify passes only once the full checks pass on the final code, so the fixes' scoped tests never hide a regression.

Review, jev, and e2e run in parallel after checks.
Every run ends with time and cost per provider.

## Parts of the pipeline

Three flags run one part of the pipeline at the point in the work where it pays off.
None of them fixes anything or reconciles Linear, and none writes `results/verify.json`.

`compose verify --project <name> --prove` runs before `run`, once the acceptance tests are collected.
It runs every e2e case headless against the project branch as it is before `run` (trunk, the groundwork stubs and the tests, with each case's own setup and seed), once and without the retry.
Each case must fail, and only because the feature is missing.
A failure is classified from jev's stop reason, last steps, and final page: rules first (the page did not load, the user landed on a login page, jev skipped the password field, the assert script crashed, the harness failed), then a fast model that reads the rest and must find the app working up to the point the feature should appear.
A case that fails for the environment (page did not load, login failed, a blocking overlay such as a cookie banner or tour, seed missing, wrong path), one the model cannot tell apart from that, and one that already passes all fail the step with the reason.
Prove refuses once the stack holds the feature.
It records `results/prove.json`.

Prove also lints the cases for the real flag path.
Every variant of a flag or experiment needs at least one case that reaches it through the real assignment (a seeded user, the flag service).
A page whose cases all carry a URL override (a query or fragment key such as `variant`, `experiment`, `flag`, `force`, `bucket`, or a whole-word `ab`, `ff`, `exp`) is reported, and so fails the step.
One case on the same path without an override covers it.
A case that must force the variant says why in `"url_override": "<reason>"`; an empty reason is itself reported.

`compose verify --project <name> --review-only` runs right after `run`.
It runs the review and the jev acceptance, with no checks, e2e, or fix rounds, and records `results/review.json`.
Findings then arrive while the stack is fresh, as tasks to fix, instead of after the whole pipeline.

`compose verify --project <name> --prototype` runs right after `run` too.
`verify.json` lists the screens that must match the prototype, one entry each:

```json
"prototype": [{"name": "settings", "url": "http://127.0.0.1:$E2E_PORT/settings", "goal": "Open the settings page.",
               "reference": "Frame0 page Settings", "must_match": ["icons", "empty state copy", "row spacing"]}]
```

It drives jev to each screen of the built app at the top of the stack and keeps the screenshots in `results/prototype/e2e/`.
It writes one report, `results/prototype.md`: per screen, the reference, the capture, and a `- [ ]` line for each `must_match`.
The reader opens both images and ticks the lines, and a mismatch becomes a task before the first full verify.
It fails only when a screen cannot be reached; whether it matches is for the reader to decide.

## e2e rules

- Each stage gets fresh ports `$E2E_PORT` and `$E2E_CLIENT_PORT`.
  Verify expands them in every value of a case (`url`, `goal`, its `env`) and in `e2e_env`, and sets them for `e2e_setup`, `setup`, `driver`, and `assert`.
  Never hardcode a port.
- Start servers in `e2e_setup` with a plain `&`.
- The cases start once every port `e2e_setup` names (`$E2E_PORT`, `$E2E_CLIENT_PORT`) accepts a connection, waiting up to 60 s, or `e2e_setup_wait` if longer.
  A setup that names neither, such as an extension's browser on a pinned port, waits a fixed `e2e_setup_wait` seconds.
  A case's own `setup` works the same way with `setup_wait`.
- A case's own `setup`, for a jev case as for a driver case, starts before that case and ends after its `assert`.
  Use it for what one case needs alone, such as logging in a different user.
- Keep driver and assert scripts under `.compose/<project>/e2e/`.
- Each stage launches its own Chromium with a throwaway profile, so verify never touches your real Chrome.
  The browser is headless, because an unattended verify runs while the display sleeps, and a headed Chromium then stops painting.
  Set `"e2e_headed": true` to watch the browser; on macOS the whole verify keeps the Mac awake with `caffeinate -dims -w <pid>`, headless or not, so the machine does not sleep under it.
- When the stage ends, it stops everything it started.
  That covers setup processes, its browser and that browser's harness daemons, and anything listening on its ports.
  A SIGTERM or SIGHUP to verify ends them too.
  A verify killed outright ends nothing, so the next stage ends the browser of any verify that is gone.
- When verify runs at the stack top in a slot under the main checkout, every absolute path in `checks` and the e2e config that points into the project worktree or the main checkout is moved to that slot, once.

## jev cases

A case without a `driver` runs jev to its `goal`, then runs its `assert`.
The `assert` runs after every jev run, also one that gave up, crashed, or hit its limit, so an assert that resets the app for the next case always runs.
It runs while jev's tab is still open, so it can read the page jev left over `BU_CDP_URL`; jev closes the tab once it ends.

jev never sends a password to a model.
To log in through a form, name the field's value in `secrets`, keyed by the field's label, and keep the value in the environment, for example in `e2e_env` or `~/.compose/.env`:

```json
{"name": "billing", "url": "http://127.0.0.1:$E2E_PORT/login", "goal": "Log in as e2e@example.com and open Billing.",
 "secrets": {"Password": "$E2E_PASSWORD"}, "assert": "python .compose/<project>/e2e/check_billing.py"}
```

jev types the value itself, so it never reaches a model, jev's history, its result, or verify's output.
A literal value is refused; name an environment variable.
Without a matching secret, jev skips the password field, and its stop reason names the field it skipped.

A jev run that does not reach its goal ends `blocked` (or `error`, for a crash) and reports `TOOL ERROR`.
The `e2e` line then names jev's stop reason, and the next lines show the page it stopped on and its last steps.
`results/verify.json` keeps every step of the run, and `results/e2e/<n>-<case>/` keeps a screenshot of each step of a case that did not pass.

A failing check keeps its whole output in `results/checks/` (named on its `check` line and as `output_file` in `results/verify.json`, whose `output` is only the last 3000 characters).
The reflect and every fix round read the check's failing tests (unittest's `FAIL:` and `ERROR:` lines), then the end of the output, then that path.

When the harness itself fails, for example a jev or browser crash, a missing tool, or a port in use, verify reports `TOOL ERROR` and retries once.
It never sends that failure to a fix round.

A case with a `driver` command runs the project's own browser driver instead of jev.
That driver still gets the stage's browser in `BU_CDP_URL`.
When no case needs a browser, for example drivers of a terminal app, set `"e2e_browser": false`: the stage then launches none and sets no `BU_CDP_URL`.

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
verify and `bp goal` both run it as `python -m jev_ultrafast <url> <goal>`, which ends with a `JEV_RESULT` line and exits 0 only when the goal is done.

- It is its own uv project (Python 3.12+, `browser-harness`, `httpx`), so `bin/compose` stays standard library only.
- The CLI runs it with `uv run` from `jev/` and passes `~/.compose/.env` when it exists.
- You run its tests with `cd jev && uv run pytest`.

jev-ultrafast keeps the demo CLI, its web UI, the examples, and the scripts.
