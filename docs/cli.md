# CLI

This page lists every fast-coding command and its flags.
The team lead runs them for you, and you run them yourself only in manual mode.

Every command takes `--repo <path>` (default `.`) and `--project <name>`.
`--project` works from any checkout of the repository.
You can leave it out when the repo has one project.

## Normal mode

Open Claude Code in the repo and run:

```
/fast-coding plan and build <feature> from ENG-123 and DESIGN.md
```

The team lead runs every command below for you.
You review the plan, the task list, and the stack.

## Manual mode

1. Run `fast-coding init --project my-feature`, then work in the worktree it prints.
2. On Linear, write the feature issue (its description is the plan) and one task issue per task.
   End each task issue with a [fast-coding block](tasks.md).
3. Write `{"feature": "ENG-123"}` to `.fast-coding/my-feature/linear.json`, write each task's test, and commit.
4. Run `fast-coding sync --project my-feature < issues.json`, and run it again after any Linear edit ([shape](tasks.md#sync)).
5. Run `fast-coding run --project my-feature`, then `fast-coding verify --project my-feature`.

When you ask, `fast-coding stack --project my-feature --submit` pushes and opens one draft PR per layer.
After the PRs merge, `fast-coding clean --project my-feature` removes what merged and keeps what did not.

Before the first run in a new repo, do these three things:

- Commit everything, because `run` refuses a dirty tree.
- Fill `verify.json` with the repo's lint and test commands ([verify.md](verify.md)).
- For OpenCode tasks only, add an `opencode.jsonc` allowing `edit` and `bash` so it never blocks on a prompt.

## Commands

### Projects

These commands create, list, and clean up projects.

| Command | Does |
|---|---|
| `init` | Creates branch `fast-coding/<name>`, its worktree, and `.fast-coding/<name>/`. `--here` uses this checkout, and `--after <project>` branches from another project |
| `projects` | Lists every project with done/total, last activity, title, and states |
| `status` | Shows every project with every task. `--watch` redraws every 2 s |
| `clean` | Drops merged layers and removes a fully merged project's worktree and branch. `--delete-unmerged` also drops unreviewed layers |
| `graft` | Sets graft up again in the project's worktree |

### Tasks

These commands load the tasks, dispatch them, and steer the run.

| Command | Does |
|---|---|
| `sync` | Stores the feature and its task issues from JSON on stdin |
| `tasks` | Prints the task list to review, with files, `after`, and tests. It warns on shared files |
| `run` | Dispatches tasks. The flags are `--only 003,004`, `--attempts 3`, `--parallel 3`, `--redo`, `--no-stack`, and `--trunk <branch>` |
| `done` | Records tasks finished by hand with `--only <ids> --note <why>` |
| `triage` | Has a fast model clean or flag each passed task (`run` ends with it) |
| `resume` | Continues a run or verify that stopped on a billing halt |
| `reflect` | Screens the settled decisions against evidence with Jev, using `--evidence -` and `--against "<line>"`. `--dismiss "<why>"` marks the evidence so far as answered, so later screens skip it |
| `hold` | Holds tasks back from dispatch with `--only <ids> --reason "<why>"`. `--release <ids>` or `all` releases them |
| `change start\|done\|undo` | Records a change of course. `undo C<n>` puts back what it touched |
| `bench` | Runs a frozen task set across models and reports pass rate, attempts, p50/p95 time, and cost |

### Verify and stack

These commands check the finished work and turn it into a stack.

| Command | Does |
|---|---|
| `verify` | Runs the local pipeline. `--fix 0` reports only, and `--skip-e2e` and `--skip-review` skip those stages |
| `stack` | Registers passed chains as gh stacks. `--submit` pushes and opens draft PRs |
| `top` | Checks out the stack top for manual testing. `--detach` releases it |

### Teammates and supervision

These commands start the teammates, collect their reports, and supervise the team lead.

| Command | Does |
|---|---|
| `crew start\|list\|focus\|stop` | Manages teammates, the Claude sessions in the project's herdr space ([herdr.md](herdr.md)) |
| `explore`, `wayfinder`, `groundwork` | Prints that teammate's brief. `--extra -` appends notes from stdin |
| `testcrews` | Runs one test-writing teammate per task, in parallel |
| `report` | Lets a teammate report up with `working`, `needs-user`, `blocked`, `done`, `tool-bug`, or `contradiction` |
| `watch` | Blocks until something happens, prints one event line, and exits. `--now` prints the current state and marks it seen |
| `teardown` | Closes finished tabs, stops leftover servers, and saves and quits Frame0 |
| `frame0 up\|save\|down` | Starts, saves, and stops the project's own Frame0 app |
| `guard` | Runs as the PreToolUse hook that keeps the team lead from editing code |
| `rewake` | Runs as the Stop hook that parks the team lead's next `watch` after each turn and wakes it on the event |

### Workspaces

One command lists, switches, and manages workspaces.

| Command | Does |
|---|---|
| `workspace [<name>\|add\|key\|remove]` | Lists, switches, or manages workspaces ([workspaces.md](workspaces.md)) |

## Results

Everything a run produces lands in `.fast-coding/<project>/results/`.
Each task run writes `.fast-coding/<project>/results/NNN.json` with every attempt's test output, timing, and cost.
Verify writes `results/verify.json`.
A run that dies shows as `interrupted` in `status`.
`resume` re-runs what did not pass and keeps passed layers.
`run`, `verify`, and `resume` work in their own session and write `results/<command>.log`.
The terminal that started one only streams that log.
Closing that terminal, or a crashed Claude session, leaves the work running.
Ctrl-C stops it.
