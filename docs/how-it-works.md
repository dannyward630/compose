# How it works

The loop turns a feature idea into one gh stack of small branches, each green against its own test and reviewed before verify checks the whole stack.
A frontier model plans and checks the work, cheap fast models write the code in parallel, and nothing is pushed.

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

Five roles split the decisions.

| Who | Decides |
|---|---|
| Frontier model (Claude) | plan, tests, layer review, escalations; never merges |
| Fast implementer (GLM 5.3 Flash in pi) | makes one test green in one session; never writes tests |
| Mercury | raises review findings, then confirms or drops them |
| Jev (TypeSafe) | scores acceptance criteria, drives the browser, screens settled decisions against new evidence |
| CLI | red check, protected-file guard, timing, cost ledger |

A task that fails three attempts is re-split into smaller tasks and re-run, and the loop never falls back to typing its code by hand.
A provider that runs out of credit halts the run, and [workspaces.md](workspaces.md#billing-halts) explains billing halts.

## Finding the way

In a repo that already has code, an explore crew maps it through graft first and adds a short codebase brief to the feature.
Questions and planning both wait for that brief.

Next, one wayfinder crew puts every open decision on a single Lavish page, each with its options and a recommendation.
You answer them all at once, or accept every recommendation with one button.
Your answers go to the feature issue's "Decisions so far".

A question about how a screen should look comes with a low-fi wireframe, drawn in Frame0 and shown on its card.
Each project has its own Frame0 app on `.fast-coding/<project>/design.f0`, so parallel sessions never draw into each other's window.
Three commands manage it:

1. `fast-coding frame0 up --project <name>` starts it.
2. `fast-coding frame0 save --project <name>` writes the drawing to the file.
3. `fast-coding frame0 down --project <name>` saves and quits.
   `teardown` does this too.

On the first drawing after each app start, Frame0 asks you to allow "Frame0 MCP Server".

## Linear

Work lives at five levels in Linear:

| Level | Is |
|---|---|
| project | the repo |
| epic | a wayfinder map, when the work is bigger than one feature |
| feature | one fast-coding project and one stack; its description is the plan |
| story | one user-visible slice of the feature |
| task | one stack layer; see [tasks.md](tasks.md) |

You can hand fast-coding a link to any of these levels, and it creates the missing ones.
It asks for the repo's Linear project link once and keeps it in `.fast-coding/linear.json`.
Each task moves to In Progress when it is dispatched, In Review when its layer passes, and Done when its PR merges.

## Changing course

When the plan turns out to be wrong, the fleet notices and changes it in the open.

1. Evidence arrives when a task ends without passing, an implementer or crew reports a contradiction with Linear, verify fails, or you say the plan changed.
2. Jev screens every line of the feature's Decisions so far against that evidence and marks each one HOLDS, BROKEN, or UNCLEAR.
3. The orchestrator holds only the tasks a flagged line touches, with `fast-coding hold`, then confirms the flags.
   Everything else keeps running.
4. Complex or subjective calls, plus anything you settled yourself, reach you through the first mate on a change page in Lavish.
5. The re-plan is one recorded change, started with `fast-coding change start` and finished with `done`.
   The old decision is struck through and tagged, the new one sits beside it, and a comment on the feature says what changed and why.

To reverse a change, run `fast-coding change undo C2`.
It puts back every issue and layer that change touched, and records the undo as a new change of its own.

## Projects

A project is one feature in its own worktree.

- `fast-coding init --project <name>` creates branch `fast-coding/<name>` from your current branch.
- The worktree is a [treehouse](https://github.com/kunchenguid/treehouse) slot from the repo's own git-ignored pool in `.treehouse/`.
  Without treehouse, it is `../fast-coding-<name>`.
- `.fast-coding/<name>/` sits beside it and holds the Linear link, the verify config, and results.
  `init` git-ignores it and `graft/` first.
- The stack's trunk is the project branch, and one final PR brings it to your branch.
- `init --after <other>` branches from another project's branch when the feature needs its code.

Your checkout is never touched, so several features can run at once.
A new request that continues an existing feature joins that feature's project.
Anything else gets a new project named for the feature.

## Task isolation

Each task runs in its own shared-object clone.
The prompt states the clone's absolute root and lists every editable file as an absolute path.
The absolute paths are there because project docs often name the original checkout, and models edit those instead.
The dispatcher reverts and flags any write into the main checkout.
Clones borrow the main checkout's git-ignored installs as symlinks, so `node_modules`, `vendor`, and `.venv` come along without a fresh install.

## Model choices

Since 2026-10-10, the default implementer is `pi:openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast`, with no fallback.

GLM 5.3 Flash earned that spot on a real seven-task project.
There, gpt-oss-120b on Cerebras missed the largest task four times and was rate-limited on two more, while GLM 5.3 Flash passed each on its first try in 9 to 20 s.

The default implementer runs in pi because pi was faster than OpenCode on the same host.
On that host, pi took 4.2 to 6.5 s per task at about 32K input tokens, and OpenCode took 8.5 to 11 s at about 100K.
OpenCode's fixed context is about 12K tokens per turn against pi's 1K, which accounts for the gap.
Both passed every task.

Reasoning has to be on.
With reasoning `none`, the model plans but never edits, and `low` fixed that at about twice the cost.

The reviewer is whichever model `~/.fast-coding/.env` names as `TEXT_MODEL`, and it defaults to Mercury 2.5.
You set the planner and crew models per role in the config, as [workspaces.md](workspaces.md#crew-models) describes.

These figures come from small benchmarks and one prototype.
Every real run prints its own time and cost, and those are the ones to trust.
