# fast-coding

A frontier model plans and reviews.
Parallel OpenCode instances on a fast model implement.
Verification is local.

- `SKILL.md` is the orchestrator's instructions, linked into `~/.claude/skills/fast-coding`.
- `bin/fast-coding` is the dispatcher, linked into `~/.local/bin/fast-coding`. Python stdlib only.

```bash
fast-coding init   --repo . --project <name>   # .fast-coding/<name>/{tasks,results,verify.json}
fast-coding run    --repo . --project <name>   # one worktree + one OpenCode session per task, in parallel
fast-coding verify --repo . --project <name>   # checks, confirmed Mercury review, Jev acceptance, jev e2e, fix loop, cost
fast-coding clean  --repo . --project <name>
```

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
fast-coding init --project my-feature          # creates .fast-coding/my-feature/{tasks,results,verify.json}
# write .fast-coding/my-feature/tasks/001-slug.md and its test, commit both
fast-coding run --project my-feature           # parallel OpenCode implementers, one worktree each
fast-coding verify --project my-feature        # checks, review, jev acceptance, e2e, fix loop
git merge fast/my-feature/001                  # accept what passed review
fast-coding clean --project my-feature         # remove worktrees and branches
```

Useful flags: `run --only 003,004`, `run --attempts 4`, `run --parallel 8`, `verify --fix 0` (report only), `verify --skip-e2e`, `verify --skip-review`.
Results land in `.fast-coding/my-feature/results/NNN.json` and `verify.json`, with every attempt's test output, timing, and cost.

### Before the first run in a new repo

1. Commit everything. `run` refuses a dirty tree because worktrees branch from HEAD.
2. Add an `opencode.jsonc` in the repo root so headless OpenCode does not block on a permission prompt:
   ```json
   { "permission": { "edit": "allow", "bash": "allow", "webfetch": "deny" } }
   ```
3. Make sure the shell has `CEREBRAS_API_KEY` (it is exported in `~/.zshrc`; open a new terminal or `source ~/.zshrc`).
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
model: cerebras/gpt-oss-120b
after:
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
  │  DISPATCH   one worktree + one OpenCode session per task, in parallel    │
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
  │     accept ──▶ git merge        reject / exhausted ──▶ fix by hand       │
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
    frontier (Claude)   plan, tests, review, merge, refactor, escalations
    fast (Qwen)         green only, one task, one session, never tests
    Mercury             raise findings, then confirm or drop them
    Jev                 score acceptance criteria, drive the browser
    CLI                 red check, protected-file guard, timing, cost ledger
```

Implementer model: `cerebras/gpt-oss-120b` through OpenCode (default since 2026-10-01; Qwen 3.8 27B cost about 4x more per token and Cerebras has no prompt caching, so every tool call resends the full context).
With reasoning `none` the model reads a few files, writes a plan-shaped summary, and never edits; on retries it returns nothing. `low` fixed it at roughly 2x the cost per task.
Reviewer model: whatever `~/code/jev-ultrafast/.env` names as `TEXT_MODEL`, Mercury 2.5 by default.
Browser e2e: jev-ultrafast's `Agent`, with an independent `assert` command per case.
Acceptance review: Jev (TypeSafe) answers one MET/NOT_MET/UNCLEAR question per acceptance criterion.
Every run and verify ends with a cost line per provider and a total.

Each task runs in a separate shared-object clone. The prompt states the clone's absolute root and lists editable files as absolute paths, because a project's own docs often name the original checkout's absolute paths and the model will edit those instead of its working directory. The dispatcher still reverts and flags any write into the main checkout as a safety net.

First real run: the submit deny list in `~/code/jev-autofill-test`, passed on attempt 2 in 11.7 seconds.
