# How it works

## The loop

```
  ORCHESTRATOR (Claude, frontier)
  explore the code ─▶ wayfinder page ─▶ plan in Linear ─▶ task issues + failing tests ─▶ your go
                                                                                        │
                                                                         fast-coding run│
  ┌─────────────────────────────────────────────────────────────────────────────────────▼──┐
  │ DISPATCH   one clone + one pi session per task (GLM 5.3 Flash); `after:` tasks start    │
  │            on their base task's branch                                                  │
  │   test RED on HEAD? ─ no ─▶ skip                                                        │
  │        yes ─▶ implement ─▶ run test, protected files untouched, ≤350 lines, own files  │
  │                 ▲                │                                                      │
  │                 └── RED: failure fed back to the same session, ≤3 attempts             │
  │                                  │ GREEN                                                │
  │                                  ▼                                                      │
  │                         format, commit on fast/<project>/NNN                            │
  └──────────────────────────────────┬──────────────────────────────────────────────────────┘
                                     ▼
  ORCHESTRATOR REVIEW of each layer's diff ─▶ accept, or re-split and re-run
  passed branches ─▶ one gh stack, built in a CLI worktree (nothing pushed)
                                     │ fast-coding verify
  ┌──────────────────────────────────▼──────────────────────────────────────────────────────┐
  │ 1 checks   lint + unit tests                                                            │
  │ then, in parallel:                                                                      │
  │ 2 review   Mercury, one call per perspective ─▶ confirm each finding (must quote code)  │
  │ 3 jev      one MET / NOT_MET / UNCLEAR question per acceptance criterion                │
  │ 4 e2e      jev drives a real browser to the goal, then YOUR assert checks it            │
  │ 5 fix      confirmed findings ─▶ fix model, rerun; still failing ─▶ escalate            │
  └─────────────────────────────────────────────────────────────────────────────────────────┘
```

| Who | Decides |
|---|---|
| Frontier model (Claude) | plan, tests, layer review, escalations; never merges |
| Fast implementer (GLM 5.3 Flash in pi) | makes one test green in one session; never writes tests |
| Mercury | raises review findings, then confirms or drops them |
| Jev (TypeSafe) | scores acceptance criteria, drives the browser, screens settled decisions against new evidence |
| CLI | red check, protected-file guard, timing, cost ledger |

A task that fails three attempts is re-split into smaller tasks, never typed by hand.
A provider out of credit halts the run; see [workspaces.md](workspaces.md#billing-halts).

## Finding the way

In a repo with code, an explore crew maps it through graft first and adds a short codebase brief to the feature.
No question is asked and no plan is written before that brief exists.

Then one wayfinder crew puts every open decision on one Lavish page, each with options and a recommendation.
You answer them all at once, or accept every recommendation with one button.
Answers go to the feature issue's "Decisions so far".

A question about how a screen should look is drawn as a low-fi wireframe in Frame0 and shown on its card.
Each project has its own Frame0 app on `.fast-coding/<project>/design.f0`, so parallel sessions never draw into each other's window.

1. `fast-coding frame0 up --project <name>` starts it.
2. `fast-coding frame0 save --project <name>` writes the drawing to the file.
3. `fast-coding frame0 down --project <name>` saves and quits; `teardown` does this too.

The first drawing makes Frame0 ask you to allow "Frame0 MCP Server" once per app start.

## Linear

Work lives at five levels:

| Level | Is |
|---|---|
| project | the repo |
| epic | a wayfinder map, when the work is bigger than one feature |
| feature | one fast-coding project and one stack; its description is the plan |
| story | one user-visible slice of the feature |
| task | one stack layer; see [tasks.md](tasks.md) |

fast-coding accepts any of them by link and creates the missing ones.
The repo's Linear project link is asked for once and kept in `.fast-coding/linear.json`.
Tasks move to In Progress when dispatched, In Review when their layer passes, and Done when their PR merges.

## Changing course

The fleet notices when the plan is wrong and changes it in the open.

1. Evidence arrives: a task ends without passing, an implementer or crew reports a contradiction with Linear, verify fails, or you say the plan changed.
2. Jev screens every line of the feature's Decisions so far against it: HOLDS, BROKEN, or UNCLEAR.
3. The orchestrator holds only the tasks a flagged line touches (`fast-coding hold`) and confirms; everything else keeps running.
4. Complex or subjective calls, and anything you settled, come to you on a change page in Lavish, through the first mate.
5. The re-plan is one recorded change (`fast-coding change start`, then `done`): the old decision struck through and tagged, the new one beside it, and a comment on the feature saying what changed and why.

`fast-coding change undo C2` puts back every issue and layer that change touched, as a new change of its own.

## Projects

A project is one feature in its own worktree.

- `fast-coding init --project <name>` creates branch `fast-coding/<name>` from your current branch.
- The worktree is a [treehouse](https://github.com/kunchenguid/treehouse) slot from the repo's own pool (`.treehouse/`, git-ignored), or `../fast-coding-<name>` without treehouse.
- `.fast-coding/<name>/` beside it holds the Linear link, the verify config, and results; `init` git-ignores it and `graft/` first.
- The stack's trunk is the project branch, and one final PR brings it to your branch.
- `init --after <other>` branches from another project's branch when the feature needs its code.

Your checkout is never touched, so several features can run at once.
A new request that continues an existing feature joins its project; anything else gets a new project named for the feature.

## Task isolation

Each task runs in its own shared-object clone.
The prompt states the clone's absolute root and lists editable files as absolute paths, because project docs often name the original checkout and models edit those instead.
The dispatcher reverts and flags any write into the main checkout.
Clones borrow the main checkout's git-ignored installs (`node_modules`, `vendor`, `.venv`) as symlinks.

## Model choices

The default implementer is `pi:openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast` (since 2026-10-10), with no fallback.

- **Why GLM 5.3 Flash**: on a real seven-task project, gpt-oss-120b on Cerebras missed the largest task four times and was rate-limited on two more; GLM 5.3 Flash passed each on its first try in 9 to 20 s.
- **pi over OpenCode**: on the same host, pi took 4.2 to 6.5 s per task at about 32K input tokens; OpenCode took 8.5 to 11 s at about 100K, because its fixed context is about 12K tokens per turn against pi's 1K. Both passed every task.
- **Reasoning**: with reasoning `none` the model plans but never edits; `low` fixed it at about twice the cost.
- **Reviewer**: whatever `~/.fast-coding/.env` names as `TEXT_MODEL`, Mercury 2.5 by default.
- **Planner and crews**: set per role in the config; see [workspaces.md](workspaces.md#crew-models).

These figures come from small benchmarks and one prototype.
Every real run prints its own time and cost, and those are the ones to trust.
