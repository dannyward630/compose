# fast-coding

fast-coding turns a feature idea into a reviewed, verified stack of small branches in one sitting.
A frontier model does the thinking once, up front: it interviews you until the decisions are written down, plans, and writes a failing test for every tiny task.
Then cheap fast models type the code in parallel, each boxed into one task, one test, a few named files, and 350 lines.
A local pipeline checks, reviews, and drives a real browser before anything reaches you.
You get a gh stack on your branch, one layer per task, each readable in a minute.

## Why

The expensive part of software is deciding and checking, not typing.
fast-coding spends the frontier model only on deciding and checking, and makes the typing nearly free: about a cent per task on the prototype that built it.

Against a single Claude session:

- **Cheaper and parallel.** One Claude session is one worker on a subscription with rate limits. fast-coding runs eight implementers at once for cents and leaves the subscription for the planning and review only a frontier model does well.
- **Tests before code, by construction.** The test exists and fails before an implementer starts, with holdout cases it cannot see. A lone model tends to write code, then tests that fit the code.
- **Scope cannot creep.** Each task is physically fenced: named files only, protected tests untouched, under 350 changed lines, no documents. A long single session drifts; this cannot.
- **Review-sized output.** One stack per feature, one layer per task, in dependency order. A 2,000-line branch becomes ten 100-line layers.
- **Verification that is not the model's opinion.** Four parallel fast-model reviews with a confirmation pass that must quote the code, Jev acceptance over every criterion, a real browser run with an independent assertion you wrote, and a fix loop. A "done" from any model is never the proof.
- **Honest accounting.** Every run ends with wall time per task and dollars per provider at the real pinned rate.

## When

Use it for features that decompose into independent small pieces with clear tests: new endpoints, a module plus its callers, a fixture plus the code that handles it, a batch of related fixes, a prototype you may throw away.
Use it for anything you want to review as a stack rather than a blob.

Do not use it for one-line fixes or exploratory debugging, where the overhead beats the benefit; for work where the test cannot be written first, which means it is not a task yet; or for changes to one hot file every task would need, since tasks never share files.

## How

Check out the branch the feature belongs on and tell Claude `fast-coding <what you want>`.
It first asks for the repo's Linear project link once (kept in `.fast-coding/linear.json`) and opens one feature issue there per project.
With no settled spec, it runs wayfinder: the open decisions become sub-issues of the feature issue, worked with you one question at a time with a recommendation on each, until the way is clear; then it writes the plan and the tasks with their tests and shows you the plan.
Work is five levels in Linear: the project is the repo, an epic is a wayfinder map, a feature is one fast-coding project and stack, a story is one user-visible slice of it, and a task is one stack layer; fast-coding accepts any of them by link, creates the missing ones, and never runs an implementer until you have seen the task list and said go.
Wayfinder prototype tickets about screens or flows are drawn as low-fi wireframes in Frame0 through its MCP server and attached to the ticket as images.
Every task is a sub-issue of the feature issue too, moved to In Progress when dispatched, In Review when its layer passes, and Done when its PR merges, so the feature's progress is visible in Linear without asking.
It writes the tasks and their failing tests, shows you the task list (`fast-coding tasks`: files each task owns, what it builds on, its test, stack order) and waits for your go; you can combine, split, reorder, or drop tasks first.
Then it dispatches, reviews each layer's diff, runs verify, and reports the run and cost lines.
You read the stack; when you say so, `stack --submit` pushes it and opens one draft PR per layer. A human reviewer reads them bottom-up on GitHub and decides whether the stack merges. fast-coding never merges.
A provider out of credit halts the run with the top-up link, and `resume` continues where it stopped.
A task that fails three attempts is re-split into smaller tasks, not typed by hand.

The speed and cost figures in this file come from small benchmark tasks and one prototype; every real run prints its own, and those are the ones to trust.

## In herdr

Inside [herdr](https://herdr.dev) (`HERDR_ENV=1`) the fleet is visible and steerable; outside it the same commands run headless.

Three roles, after [firstmate](https://github.com/kunchenguid/firstmate); you are the captain:

| Role | Who | Where |
|---|---|---|
| first mate | the Claude session you started: takes your request, creates the project, then only relays | stays in the pane you started it in |
| orchestrator | a Claude session that runs the project from wayfinder to a verified stack | tab `orchestrator` in the project's space, agent `<slug>-orchestrator` |
| crew | wayfinder question agents (one per independent question, at most three at once), helpers, implementers | one tab each in the project's space |

You talk to the first mate. A question agent grills you in its own tab; answer there, or tell the first mate, who forwards it. You can type into any crew tab directly.
Crew report upward with `fast-coding report` (`working`, `needs-user`, `blocked`, `done`); `watch` turns each report into a wake event, so a session that is waiting costs nothing.

```bash
fast-coding crew start --project <slug> --role orchestrator --title orchestrator --brief - < brief.txt   # first mate, after init
fast-coding crew start --project <slug> --role q-ENG-12 --title "Payment provider" --brief - < brief.txt  # orchestrator, per independent question
fast-coding crew list  --project <slug>                       # every crew session with its last report and herdr status
fast-coding crew stop  --project <slug> --role q-ENG-12       # close its tab; refused until it reported done (--force overrides)
fast-coding report --project <slug> --as <slug>-q-eng-12 needs-user "Stripe or Adyen? I recommend Stripe"   # what crew run
fast-coding watch --project <slug> --from orchestrator        # the first mate wakes only on the orchestrator's reports
```

| herdr | fast-coding | label |
|---|---|---|
| space | one project (its worktree, grouped under the repo's space) | `<slug>` |
| tab | the live `fast-coding status --watch` | `status` |
| tab | one task, holding its implementer | `NNN <title>` |
| agent | the task's interactive pi, steerable with `herdr agent prompt` | `<slug>-NNN` |
| tab | one verify run, one pane per stage | `verify HH:MM` |
| tab | the project's orchestrator, a Claude session | `orchestrator`, agent `<slug>-orchestrator` |
| tab | one crew session: a wayfinder question, a helper | its title, agent `<slug>-<role>` |
| the first mate's pane | stays where you started it | yours |

Each task pane carries state labels (`attempt 2/3`, `passed`) and tokens (`model`, `cost`); verify panes go `working`, then `idle` ok or `blocked` FAIL.
The orchestrator steers a working or blocked agent with one specific instruction through `herdr agent prompt <slug>-NNN "..."`, which lands in the same pi session the CLI is driving.
`clean` closes the project's space with its worktree.

Supervision is event-driven: `fast-coding watch --project <slug>` sleeps until a task reaches a final state, an agent blocks, a crew session reports, the run ends, or verify finishes, prints one `event ...` line (with the task's Linear id and branch), and exits.
The orchestrator runs it in the background and is woken by its exit, so waiting costs no tokens.
Every run leaves `results/run.json` with its pid; a run that dies shows as `interrupted` in `status`, and `fast-coding resume` re-runs what did not pass, keeping passed layers.

## Projects

A project is one feature in its own worktree: `fast-coding init --project <name>` creates branch `fast-coding/<name>` from the branch you are on and checks it out at `../fast-coding-<name>` next to the repo, with `.fast-coding/<name>/` (plan, numbered tasks, verify config, results) committed there.
The orchestrator does all of the feature's work in that worktree, so your checkout and branch are never touched, and several features can run at once, each with its own stack.
The stack's trunk is the project branch; its PRs target that branch, and one final PR brings the project branch to yours.
Every command accepts `--project <name>` from any checkout of the repository and resolves it to the right worktree.

Grouping is automatic and happens before anything else.
When you invoke `fast-coding <task>`, the skill first runs `fast-coding projects` on the repo.
If the request continues a feature that already has a project, by spec, by area of the code, or because you name it, the new tasks join that project with the next ids and become new layers of its stack.
Otherwise it creates a project named for the feature in your words, kebab-case (`custom-dropdowns`, `workday-login`), and tells you the name in its first reply.
One feature never spans two projects and two features never share one; a request that is really two features becomes two projects, and the skill says so.

Three views:

```bash
fast-coding projects --repo .                   # every feature: done/total, last activity, title, states
fast-coding status --repo .                     # every project with all its tasks
fast-coding status --repo . --project <name>    # one project
fast-coding status --repo . --watch             # follow a run live, redrawn every 2 s
```

```
project          done   last activity     title / states
jev-autofill     31/31  2026-10-02 17:21  Jev Autofill Prototype Implementation Plan  [31 merged]
```

The title is the plan's first heading, so a project with a plan is self-describing.
A payment halt shows on its project line with the resume hint.
The views cover every worktree of the repository (the listing shows each project's worktree); there is no cross-repository view yet.

## Pieces

## Requirements

Everything the CLI shells out to, and where each one is used. Install the required rows once per machine; the optional rows unlock one stage each.

| Tool | Needed for | Install | Required |
|---|---|---|---|
| Python 3.9+ | `bin/fast-coding` itself, stdlib only | macOS ships it | yes |
| git 2.30+ | task clones (`git clone --shared`), branches, diffs | Xcode CLT or Homebrew | yes |
| Node 22.19+ | pi, and `node --test` in repos that use it | `brew install node` | yes |
| pi | default implementer harness | `npm install -g --ignore-scripts @earendil-works/pi-coding-agent` | yes |
| OpenRouter account and key | every implementer, fixer, and reviewer call | key in `~/.pi/agent/auth.json` (`openrouter`, `openrouter-fast`) and in `~/code/jev-ultrafast/.env` as `TEXT_MODEL_API_KEY` | yes |
| OpenRouter preset `gpt-oss-120b-cerebras` | pins the implementer to Cerebras from the model string | dashboard, Settings > Presets: model `openai/gpt-oss-120b`, provider order Cerebras, fallbacks off, nothing else included | yes |
| OpenRouter preset `glm-5.3-flash-fast` | the fallback: takes a task (or a later fix round) when a gpt-oss attempt errors, times out, is rate-limited, or misses | dashboard, Settings > Presets: model `z-ai/glm-5.3-flash`, provider order Together then CoreWeave, fallbacks off, nothing else included | yes |
| `~/.pi/agent/models.json` | declares provider `openrouter-fast` (base `https://openrouter.ai/api/v1`, api `openai-completions`, key `$OPENROUTER_API_KEY` or the auth store) with models `openai/gpt-oss-120b@preset/gpt-oss-120b-cerebras` priced 0.35/0.75 per M and `z-ai/glm-5.3-flash@preset/glm-5.3-flash-fast` priced 0.15/0.50 per M | written by hand once | yes |
| gh CLI + gh-stack | `run` registers passed chains as stacks; `stack --submit` opens PRs | `brew install gh && gh extension install github/gh-stack`; `git config rerere.enabled true` | yes for stacks; `run --no-stack` without |
| jev-ultrafast checkout at `~/code/jev-ultrafast` with `.env` | `verify`: Mercury review (`TEXT_MODEL*`), Jev acceptance (`TYPESAFE_API_KEY`, `TYPESAFE_MODEL`), browser e2e (`jev_ultrafast.Agent`) | clone it, fill `.env`, `uv sync` | yes for `verify` |
| uv | runs jev-ultrafast and the Python test commands in verify.json | `brew install uv` | yes for `verify` |
| Chrome plus browser-harness | `verify` e2e cases drive a real browser | installed by jev-ultrafast; `uv run browser-harness --doctor` there | only with e2e cases |
| `bp` (browser-probe) | every browser exploration and extension e2e: launches a Chromium with the extension, `e2e_env` points jev at it | `cd ~/code/browser-probe && npm link` | yes for extension work |
| OpenCode | alternative implementer, `model: openrouter/openai/gpt-oss-120b`; bench column | `curl -fsSL https://opencode.ai/install \| bash`; key in `~/.local/share/opencode/auth.json`; `~/.config/opencode/opencode.jsonc` pins `options.provider.order: ["cerebras", "groq"]` | optional |
| Claude Code | `model: claude` baseline through the subscription (`claude -p`) | already installed if you are reading this from it | optional |
| graft | `graft build .` gives implementers a `file:line` context pack instead of exploring | `brew install graft` (or the project's installer); free, git-ignored | optional, recommended |

Secrets never live in this repo or on Linear issues: the active workspace's key comes from `~/.fast-coding/config.json` (see [Workspaces](#workspaces)); without one, pi and OpenCode read their auth stores and verify reads the jev-ultrafast `.env`.

- `SKILL.md` is the orchestrator's instructions, linked into `~/.claude/skills/fast-coding`.
- `bin/fast-coding` is the dispatcher, linked into `~/.local/bin/fast-coding`. Python stdlib only.

```bash
fast-coding init   --repo . --project <name>   # branch fast-coding/<name> + worktree ../fast-coding-<name> with .fast-coding/<name>/ committed (--here: in this checkout)
fast-coding run    --repo . --project <name>   # one clone + one pi session per task; dependency order; one gh stack on your branch
fast-coding stack  --repo . --project <name>   # re-register stacks; --submit pushes and opens draft PRs (ask first)
fast-coding verify --repo . --project <name>   # checks, confirmed Mercury review, Jev acceptance, jev e2e, fix loop, cost
fast-coding resume --repo . --project <name>   # continue a run or verify that stopped on PAYMENT REQUIRED
fast-coding sync     --repo . --project <name> < issues.json   # store the feature (plan) and its task issues, read from Linear by the orchestrator
fast-coding tasks    --repo . --project <name>   # the task list to review before dispatch: files owned, after, tests; warns on shared files
fast-coding projects --repo .                  # every project (feature): done/total, last activity, title, states
fast-coding status --repo . [--project <name>] [--watch]   # all projects with every task, or one; state, attempts, time, cost, stack layer; --watch refreshes
fast-coding clean  --repo . [--project <name>]  # post-merge: fetch, drop layers proven merged (ancestry or merged PR); remove a project's worktree+branch once fully merged
fast-coding crew   start|list|stop --project <name> [--role <role>]   # Claude sessions in the project's herdr space (see In herdr)
fast-coding report --project <name> --as <agent> <state> <message>     # a crew session reports up: working | needs-user | blocked | done
fast-coding workspace [<name> | add <name> | key <name> | remove <name>]   # list, switch, or manage workspaces (OpenRouter key and models per account)
```

Merging is a human decision on GitHub: `stack --submit` opens one draft PR per layer, the reviewer merges the stack or not. Nothing in fast-coding merges, locally or remotely.

## How to use it

### With Claude as orchestrator (the normal way)

Open Claude Code in the repo and ask for the skill:

```
/fast-coding plan and build <feature> from ENG-123 and DESIGN.md
```

Claude reads the spec, writes the plan into the feature issue on Linear, splits it into task issues, writes the acceptance tests, dispatches, reviews each diff, runs verify, and reports with timing and cost.
You review the plan and the results.
You never call the CLI yourself in this mode.

### Manually

```bash
cd ~/code/some-repo
fast-coding init --project my-feature          # worktree ../fast-coding-my-feature on branch fast-coding/my-feature; work there from now on
# on Linear: the feature issue (its description holds the plan) and one task issue per task, each ending with a fast-coding block
# echo '{"feature": "ENG-123"}' > .fast-coding/my-feature/linear.json; write each task's test; commit
fast-coding sync --project my-feature < issues.json   # the feature and its issues as read from Linear (shape below); again after any Linear edit
fast-coding run --project my-feature           # parallel pi implementers, one clone each; `after:` tasks stack on their base
fast-coding verify --project my-feature        # checks, review, jev acceptance, e2e, fix loop
fast-coding stack --project my-feature --submit   # when asked: push the stack, one draft PR per layer; a reviewer merges on GitHub
fast-coding clean --project my-feature         # after the PRs merged: removes what is merged, keeps what is not
```

### Workspaces

A workspace is one OpenRouter account and its settings: which key every call bills to, and optionally its own models and env.
`default` always exists; add as many others as you need and switch between them.

```bash
fast-coding workspace                              # list workspaces (* = active, keys shown as their last 4 characters) and the active models
fast-coding workspace personal                     # switch to personal; run and verify print `workspace <name>` first
fast-coding workspace default                      # switch back to default
pbpaste | fast-coding workspace add client-x       # create a workspace with the key on the clipboard (no pipe: hidden prompt, empty = set later)
pbpaste | fast-coding workspace key client-x       # set or rotate a workspace's key (`key default` sets the top-level one)
fast-coding workspace remove client-x              # delete it; removing the active one switches to default
```

The same commands from Claude Code, through the plugin's slash command:

```
/fast-coding:workspace
/fast-coding:workspace personal
/fast-coding:workspace add client-x
/fast-coding:workspace remove client-x
```

The slash command never asks for a key in chat; to set one, copy it and type `! pbpaste | fast-coding workspace key <name>` in the prompt.
Workspace names are letters, digits, `-` and `_`; `add`, `key`, `remove` and `default` are reserved.

The commands edit `~/.fast-coding/config.json` (mode 600, it holds keys; `FAST_CODING_CONFIG` points elsewhere), which you can also edit by hand.
It has top-level settings and a `workspaces` map; the active one (`workspace`) is merged over the top level:

```json
{"workspace": "work",
 "models": {"implementer": "pi:openrouter-fast/openai/gpt-oss-120b@preset/gpt-oss-120b-cerebras",
            "fallback": "pi:openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5.3-flash-fast", "fix": "<optional, default: implementer>"},
 "env": {"TYPESAFE_API_KEY": "<optional, any env var the CLI and its tools read>"},
 "workspaces": {"work": {"openrouter_api_key": "sk-or-..."},
                "personal": {"openrouter_api_key": "sk-or-...", "models": {"fallback": null}}}}
```

The workspace key goes to pi (`--api-key`, which beats its auth store), OpenCode (`OPENCODE_CONFIG_CONTENT`), the Mercury review, and jev's e2e text helper (`TEXT_MODEL_API_KEY`), so every OpenRouter call bills that account.
OpenRouter presets belong to an account: create `gpt-oss-120b-cerebras` and `glm-5.3-flash-fast` in each workspace's account too.
`fallback: null` turns the fallback off; a project's `verify.json` `fix_model` still wins over `models.fix`.
`default` always exists: it is the top level itself, active when `workspace` is unset, and with no top-level `openrouter_api_key` the harnesses keep their own auth stores.
`/fast-coding:workspace` comes from the repo being a skills-dir plugin too (`.claude-plugin/plugin.json`, `commands/workspace.md`).
Keys are read from piped stdin or a hidden prompt, never an argument, so they stay out of shell history and the process list.
A workspace added without a key stops every command while active, rather than billing another account.

### When a provider stops for billing

Any provider call can come back with payment required: OpenRouter credits (implementers, fixer, Mercury reviews), Cerebras or Groq through OpenCode, TypeSafe (Jev acceptance), or the jev-ultrafast e2e driver's own calls.
`run` and `verify` treat that as a halt, not a failure: no attempt is consumed, nothing is retried, running tasks finish, no new task starts, and the state goes to `.fast-coding/<project>/results/resume.json`.
The banner names the provider, quotes its message, prints the top-up link, and lists what is left. Exit code is 3.

```bash
fast-coding resume --repo . --project <name>   # after topping up: runs the remaining tasks, or reruns the halted verify
```

Passed tasks keep their branches and are not rerun. A halted verify reruns from its first stage, since the stages are cheap and idempotent.
`FAST_CODING_FAKE_402=openrouter` (optionally `FAST_CODING_FAKE_402_MATCH=<text in the task prompt>`) simulates the stop for testing.

Useful flags: `run --only 003,004`, `run --attempts 4`, `run --parallel 8`, `verify --fix 0` (report only), `verify --skip-e2e`, `verify --skip-review`.
Results land in `.fast-coding/my-feature/results/NNN.json` and `verify.json`, with every attempt's test output, timing, and cost.

### Before the first run in a new repo

1. Commit everything. `run` refuses a dirty tree because branches start from HEAD and `gh stack init` switches branches while registering.
   Install `gh extension install github/gh-stack` and set `git config rerere.enabled true`.
2. Only if a task will use OpenCode: add an `opencode.jsonc` in the repo root so headless OpenCode does not block on a permission prompt (pi runs tools without prompts):
   ```json
   { "permission": { "edit": "allow", "bash": "allow", "webfetch": "deny" } }
   ```
3. Keys. The implementer runs on OpenRouter: OpenCode reads the key from its auth store (`~/.local/share/opencode/auth.json`, entry `openrouter`), pi from `~/.pi/agent/auth.json` (entries `openrouter` and `openrouter-fast`). Both hold the same OpenRouter key the jev-ultrafast `.env` uses as `TEXT_MODEL_API_KEY`.
   pi itself: `npm install -g --ignore-scripts @earendil-works/pi-coding-agent` (Node 22.19+). Its `~/.pi/agent/models.json` declares the provider `openrouter-fast` (OpenRouter base URL, `openai-completions` API) with the model `openai/gpt-oss-120b@preset/gpt-oss-120b-cerebras`: an OpenRouter preset (dashboard, Settings > Presets) that pins provider order to Cerebras with fallbacks off, so a harness with no request-body options still gets the pinned host. Priced at the Cerebras rate so the ledger is honest.
   OpenCode pins the host explicitly instead: `~/.config/opencode/opencode.jsonc` sets `options.provider.order: ["cerebras", "groq"]` with fallbacks off.
   Workspaces override all of that per account: see [Workspaces](#workspaces).
4. Fill `verify.json` with the repo's lint and test commands, and list the docs the docs perspective should check.
5. Add e2e cases only for browser-facing work, each with an `assert` command you wrote.
6. Run `graft build .` so implementers get a context pack instead of exploring. It is free and git-ignored; the CLI rebuilds it inside each worktree.

### Task issue

A task is a Linear issue under the project's feature (directly or under a story).
Its title is the task's title; its description is the implementer's brief and ends with the block the CLI reads:

````markdown
## Goal
One paragraph. What to build, where, exact export names.

## Acceptance criteria
- One bullet per behavior. Each is checked by the test.

## Test plan
- How to run: the `test:` command below.
- Covered: which behaviors the test exercises, in words.
- Holdout: the test has cases not listed here.

## Constraints
- No new dependencies. Do not edit protected files.

```fast-coding
id: 002
files: extension/snapshot.js
protected: tests/snapshot.test.js
test: node --test 'tests/**/*.test.js'
model: openrouter/openai/gpt-oss-120b
```
````

`after` is the issue's "blocked by" links to other tasks of the same feature: each becomes the layer this task stacks on.
Issues without the block (stories, decision tickets) are not tasks.
The plan is the feature issue's description; nothing about the work is written to a file in the repo.
The CLI never calls Linear and needs no Linear key: the orchestrator reads the feature and every issue under it (stories' children included) with its Linear MCP tools (`list_issues` for the ids, then `get_issue` for each whole description and its relations, since `list_issues` truncates descriptions) and pipes them to `fast-coding sync`:

```json
{"feature": {"id": "ENG-123", "title": "...", "description": "<the feature's description, plan included>"},
 "issues": [{"id": "ENG-124", "title": "...", "description": "<brief + fast-coding block>", "status": "Todo", "blockedBy": ["ENG-125"]}]}
```

`sync` refuses a feature other than the one `linear.json` names, a block without `id` or `test`, and an id used twice.
`run`, `verify`, `resume`, `bench`, and `tasks` read what was last synced and refuse to start without a sync; the orchestrator syncs right before each of them, so an edit made in Linear reaches the implementer.
`.fast-coding/<project>/` holds only the CLI's JSON: `linear.json` (`{"feature": "ENG-123"}`), `verify.json`, and the git-ignored `results/` (with `tasks.json`, what `sync` stored).

Right-sized means one to three files, one test command, under ten criteria, and the test fails on HEAD.
If you cannot write the test, it is not a task yet.

## How the loop works

```
                          ORCHESTRATOR  (Claude, frontier)
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  spec (Linear feature issue + wayfinder tickets, DESIGN.md, PRD)         │
  │     │                                                                    │
  │     ▼                                                                    │
  │  Linear: plan in the feature ──▶ task issues 001 002 003 (+ CLI block)   │
  │                  │                                                       │
  │                  ▼                                                       │
  │  write tests/*.test.js  (RED on HEAD, holdout cases inside, protected)   │
  │                  │                                                       │
  │              git commit                                                  │
  └──────────────────┼───────────────────────────────────────────────────────┘
                     │  fast-coding run
                     ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  DISPATCH   one clone + one pi session per task; `after:` tasks         │
  │             start on their base task's branch; trunk = your branch       │
  │                                                                          │
  │   task 001              task 002              task 003                   │
  │   ┌────────────┐        ┌────────────┐        ┌────────────┐            │
  │   │ test RED?  │        │ test RED?  │        │ test RED?  │  no ──▶ skip│
  │   │    yes     │        │    yes     │        │    yes     │  (already   │
  │   │     ▼      │        │     ▼      │        │     ▼      │   green)    │
  │   │ ┌────────┐ │        │ ┌────────┐ │        │ ┌────────┐ │            │
  │   │ │OpenCode│ │        │ │OpenCode│ │        │ │OpenCode│ │            │
  │   │ │ Qwen   │ │        │ │ Qwen   │ │        │ │ Qwen   │ │  Cerebras  │
  │   │ │Cerebras│ │        │ │Cerebras│ │        │ │Cerebras│ │  ~2000 t/s │
  │   │ └───┬────┘ │        │ └───┬────┘ │        │ └───┬────┘ │            │
  │   │     ▼      │        │     ▼      │        │     ▼      │            │
  │   │ run test   │        │ run test   │        │ run test   │            │
  │   │ protected  │        │ protected  │        │ protected  │            │
  │   │ untouched? │        │ untouched? │        │ untouched? │            │
  │   │  │      │  │        │            │        │            │            │
  │   │ GREEN  RED─┼─┐      │    ...     │        │    ...     │            │
  │   │  │      ▲  │ │ feed failure back, same session, ≤3 attempts          │
  │   │  │      └──┼─┘      │            │        │            │            │
  │   │  ▼         │        │            │        │            │            │
  │   │ commit on  │        │            │        │            │            │
  │   │ fast/001   │        │            │        │            │            │
  │   └────────────┘        └────────────┘        └────────────┘            │
  │                                                                          │
  │   results/NNN.json  +  per-task time  +  $ cost                          │
  └──────────────────┬───────────────────────────────────────────────────────┘
                     │
                     ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  ORCHESTRATOR REVIEW   git diff main..fast/NNN                           │
  │     accept ──▶ layer stays      reject / exhausted ──▶ re-split, re-run  │
  │     every attempt: test, protected files untouched, ≤350 changed lines,  │
  │     no new documents, only `files:` touched; passed branches ──▶ one     │
  │     linear gh stack on your branch, built in a CLI worktree (no push)    │
  └──────────────────┬───────────────────────────────────────────────────────┘
                     │  fast-coding verify        (all local, nothing pushed)
                     ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  VERIFY PIPELINE                                                         │
  │                                                                          │
  │  1 checks      lint + unit tests                        exact, cheap     │
  │       │                                                                  │
  │  2 review      Mercury x4 in parallel ──▶ confirm each finding           │
  │                correctness security spec docs    (must quote the code)   │
  │                dropped ─── unconfirmed                                   │
  │       │        confirmed high ──▶ FAIL                                   │
  │  3 jev         one choice question per acceptance criterion             │
  │                MET / NOT_MET / UNCLEAR with probabilities   ~0.3 s       │
  │       │                                                                  │
  │  4 e2e         jev-ultrafast drives a real browser to the goal          │
  │                then YOUR assert reads the real DOM                       │
  │       │                                                                  │
  │       ▼                                                                  │
  │   all ok? ── yes ──▶ PASS  +  time  +  cost per provider  +  total       │
  │       │                                                                  │
  │       no                                                                 │
  │       ▼                                                                  │
  │  5 fix loop    confirmed findings ──▶ OpenCode/Qwen in the repo          │
  │                protected files reverted if touched, commit, rerun 1-4    │
  │                ≤ N rounds ──▶ still failing ──▶ ESCALATE to orchestrator │
  └──────────────────────────────────────────────────────────────────────────┘

  Who decides what
    frontier (Claude)   plan, tests, review, refactor, escalations; never merges
    fast (Qwen)         green only, one task, one session, never tests
    Mercury             raise findings, then confirm or drop them
    Jev                 score acceptance criteria, drive the browser
    CLI                 red check, protected-file guard, timing, cost ledger
```

Implementer model: `pi:openrouter-fast/openai/gpt-oss-120b@preset/gpt-oss-120b-cerebras` (default since 2026-10-02): gpt-oss-120b through the pi harness, with the OpenRouter preset `gpt-oss-120b-cerebras` pinning the host to Cerebras, fallbacks off. Bench on the frozen deny-list task, same host: pi 4.2 to 6.5 s (p50 5.0 s) at ~32K input tokens per task; OpenCode `openrouter/openai/gpt-oss-120b` (pinned in its own config) 8.5 to 11 s at ~100K, because its fixed context is ~12K tokens per turn against pi's ~1K. Both pass 100%. OpenCode stays available per task via `model:`.
Groq measures 342 t/s at 0.16 s latency with prompt caching at $0.15/$0.60 per M; Cerebras direct was 538 t/s at $0.35/$0.75 with no caching and a 150K tokens-per-minute dev-tier limit, which is what made Qwen 3.8 27B cost about $10 for one prototype build.
With reasoning `none` the model reads a few files, writes a plan-shaped summary, and never edits; on retries it returns nothing. `low` fixed it at roughly 2x the cost per task.
Reviewer model: whatever `~/code/jev-ultrafast/.env` names as `TEXT_MODEL`, Mercury 2.5 by default.
Browser e2e: jev-ultrafast's `Agent`, with an independent `assert` command per case.
Acceptance review: Jev (TypeSafe) answers one MET/NOT_MET/UNCLEAR question per acceptance criterion.
Every run and verify ends with a cost line per provider and a total.

Each task runs in a separate shared-object clone. The prompt states the clone's absolute root and lists editable files as absolute paths, because a project's own docs often name the original checkout's absolute paths and the model will edit those instead of its working directory. The dispatcher still reverts and flags any write into the main checkout as a safety net.

First real run: the submit deny list in `~/code/jev-autofill-test`, passed on attempt 2 in 11.7 seconds.
