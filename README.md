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
With no `GRILLING.md`, it grills you one question at a time with a recommendation on each until the decisions are settled, then writes the plan and the tasks with their tests and shows you the plan.
It writes the tasks and their failing tests, shows you the task list (`fast-coding tasks`: files each task owns, what it builds on, its test, stack order) and waits for your go; you can combine, split, reorder, or drop tasks first.
Then it dispatches, reviews each layer's diff, runs verify, and reports the run and cost lines.
You read the stack; when you say so, `stack --submit` pushes it and opens one draft PR per layer. A human reviewer reads them bottom-up on GitHub and decides whether the stack merges. fast-coding never merges.
A provider out of credit halts the run with the top-up link, and `resume` continues where it stopped.
A task that fails three attempts is re-split into smaller tasks, not typed by hand.

The speed and cost figures in this file come from small benchmark tasks and one prototype; every real run prints its own, and those are the ones to trust.

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
| `~/.pi/agent/models.json` | declares provider `openrouter-fast` (base `https://openrouter.ai/api/v1`, api `openai-completions`, key `$OPENROUTER_API_KEY` or the auth store) with model `openai/gpt-oss-120b@preset/gpt-oss-120b-cerebras` priced 0.35/0.75 per M | written by hand once | yes |
| gh CLI + gh-stack | `run` registers passed chains as stacks; `stack --submit` opens PRs | `brew install gh && gh extension install github/gh-stack`; `git config rerere.enabled true` | yes for stacks; `run --no-stack` without |
| jev-ultrafast checkout at `~/code/jev-ultrafast` with `.env` | `verify`: Mercury review (`TEXT_MODEL*`), Jev acceptance (`TYPESAFE_API_KEY`, `TYPESAFE_MODEL`), browser e2e (`jev_ultrafast.Agent`) | clone it, fill `.env`, `uv sync` | yes for `verify` |
| uv | runs jev-ultrafast and the Python test commands in verify.json | `brew install uv` | yes for `verify` |
| Chrome plus browser-harness | `verify` e2e cases drive a real browser | installed by jev-ultrafast; `uv run browser-harness --doctor` there | only with e2e cases |
| OpenCode | alternative implementer, `model: openrouter/openai/gpt-oss-120b`; bench column | `curl -fsSL https://opencode.ai/install \| bash`; key in `~/.local/share/opencode/auth.json`; `~/.config/opencode/opencode.jsonc` pins `options.provider.order: ["cerebras", "groq"]` | optional |
| Claude Code | `model: claude` baseline through the subscription (`claude -p`) | already installed if you are reading this from it | optional |
| graft | `graft build .` gives implementers a `file:line` context pack instead of exploring | `brew install graft` (or the project's installer); free, git-ignored | optional, recommended |

Secrets never live in this repo or in task files: pi and OpenCode read their auth stores, verify reads the jev-ultrafast `.env`.

- `SKILL.md` is the orchestrator's instructions, linked into `~/.claude/skills/fast-coding`.
- `bin/fast-coding` is the dispatcher, linked into `~/.local/bin/fast-coding`. Python stdlib only.

```bash
fast-coding init   --repo . --project <name>   # branch fast-coding/<name> + worktree ../fast-coding-<name> with .fast-coding/<name>/ committed (--here: in this checkout)
fast-coding run    --repo . --project <name>   # one clone + one pi session per task; dependency order; one gh stack on your branch
fast-coding stack  --repo . --project <name>   # re-register stacks; --submit pushes and opens draft PRs (ask first)
fast-coding verify --repo . --project <name>   # checks, confirmed Mercury review, Jev acceptance, jev e2e, fix loop, cost
fast-coding resume --repo . --project <name>   # continue a run or verify that stopped on PAYMENT REQUIRED
fast-coding tasks    --repo . --project <name>   # the task list to review before dispatch: files owned, after, tests; warns on shared files
fast-coding projects --repo .                  # every project (feature): done/total, last activity, title, states
fast-coding status --repo . [--project <name>] [--watch]   # all projects with every task, or one; state, attempts, time, cost, stack layer; --watch refreshes
fast-coding clean  --repo . [--project <name>]  # post-merge: fetch, drop layers proven merged (ancestry or merged PR); remove a project's worktree+branch once fully merged
```

Merging is a human decision on GitHub: `stack --submit` opens one draft PR per layer, the reviewer merges the stack or not. Nothing in fast-coding merges, locally or remotely.

## How to use it

### With Claude as orchestrator (the normal way)

Open Claude Code in the repo and ask for the skill:

```
/fast-coding plan and build <feature> from GRILLING.md and DESIGN.md
```

Claude reads the spec, writes `.fast-coding/<project>/plan.md`, splits it into task files, writes the acceptance tests, dispatches, reviews each diff, runs verify, and reports with timing and cost.
You review the plan and the results.
You never call the CLI yourself in this mode.

### Manually

```bash
cd ~/code/some-repo
fast-coding init --project my-feature          # worktree ../fast-coding-my-feature on branch fast-coding/my-feature; work there from now on
# write .fast-coding/my-feature/tasks/001-slug.md and its test, commit both
fast-coding run --project my-feature           # parallel pi implementers, one clone each; `after:` tasks stack on their base
fast-coding verify --project my-feature        # checks, review, jev acceptance, e2e, fix loop
fast-coding stack --project my-feature --submit   # when asked: push the stack, one draft PR per layer; a reviewer merges on GitHub
fast-coding clean --project my-feature         # after the PRs merged: removes what is merged, keeps what is not
```

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
4. Fill `verify.json` with the repo's lint and test commands, and list the docs the docs perspective should check.
5. Add e2e cases only for browser-facing work, each with an `assert` command you wrote.
6. Run `graft build .` so implementers get a context pack instead of exploring. It is free and git-ignored; the CLI rebuilds it inside each worktree.

### Task file

```markdown
---
id: 002
title: Snapshot port
files: extension/snapshot.js
protected: tests/snapshot.test.js
test: node --test 'tests/**/*.test.js'
model: openrouter/openai/gpt-oss-120b
after:            # id of the task this one builds on; it becomes the next layer of that task's stack
---

## Goal
One paragraph. What to build, where, exact export names.

## Acceptance criteria
- One bullet per behavior. Each is checked by the test.

## Test plan
- How to run: the `test:` command above.
- Covered: which behaviors the test exercises, in words.
- Holdout: the test has cases not listed here.

## Constraints
- No new dependencies. Do not edit protected files.
```

Right-sized means one to three files, one test command, under ten criteria, and the test fails on HEAD.
If you cannot write the test, it is not a task yet.

## How the loop works

```
                          ORCHESTRATOR  (Claude, frontier)
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  spec (GRILLING.md, DESIGN.md, ticket)                                   │
  │     │                                                                    │
  │     ▼                                                                    │
  │  plan.md ──▶ tasks/001.md 002.md 003.md ...   (goal, ACs, test plan)     │
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
