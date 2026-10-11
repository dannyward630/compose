# CLI

Every command takes `--repo <path>` (default `.`) and `--project <name>`.
`--project` works from any checkout of the repository; it can be left out when the repo has one project.

## Normal mode

Open Claude Code in the repo and run:

```
/fast-coding plan and build <feature> from ENG-123 and DESIGN.md
```

The orchestrator runs every command below for you.
You review the plan, the task list, and the stack.

## Manual mode

1. `fast-coding init --project my-feature`, then work in the worktree it prints.
2. On Linear: write the feature issue (its description is the plan) and one task issue per task, each ending with a [fast-coding block](tasks.md).
3. Write `{"feature": "ENG-123"}` to `.fast-coding/my-feature/linear.json`, write each task's test, and commit.
4. `fast-coding sync --project my-feature < issues.json`, again after any Linear edit ([shape](tasks.md#sync)).
5. `fast-coding run --project my-feature`, then `fast-coding verify --project my-feature`.

When asked, `fast-coding stack --project my-feature --submit` pushes and opens one draft PR per layer.
After the PRs merge, `fast-coding clean --project my-feature` removes what merged and keeps what did not.

Before the first run in a new repo:

- commit everything: `run` refuses a dirty tree;
- fill `verify.json` with the repo's lint and test commands ([verify.md](verify.md));
- for OpenCode tasks only, add an `opencode.jsonc` allowing `edit` and `bash` so it never blocks on a prompt.

## Commands

### Projects

| Command | Does |
|---|---|
| `init` | Create branch `fast-coding/<name>`, its worktree, and `.fast-coding/<name>/`; `--here` uses this checkout, `--after <project>` branches from another project |
| `projects` | Every project: done/total, last activity, title, states |
| `status` | Every project with every task; `--watch` redraws every 2 s |
| `clean` | Drop merged layers; remove a fully merged project's worktree and branch; `--delete-unmerged` also drops unreviewed layers |
| `graft` | Set graft up in the project's worktree again |

### Tasks

| Command | Does |
|---|---|
| `sync` | Store the feature and its task issues from JSON on stdin |
| `tasks` | The task list to review: files, `after`, tests; warns on shared files |
| `run` | Dispatch tasks; `--only 003,004`, `--attempts 3`, `--parallel 3`, `--redo`, `--no-stack`, `--trunk <branch>` |
| `done` | Record tasks finished by hand: `--only <ids> --note <why>` |
| `triage` | Fast-model clean or flag per passed task (`run` ends with it) |
| `resume` | Continue a run or verify that stopped on a billing halt |
| `bench` | Frozen task set across models: pass rate, attempts, p50/p95 time, cost |

### Verify and stack

| Command | Does |
|---|---|
| `verify` | The local pipeline; `--fix 0` reports only, `--skip-e2e`, `--skip-review` |
| `stack` | Register passed chains as gh stacks; `--submit` pushes and opens draft PRs |
| `top` | Check out the stack top for manual testing; `--detach` releases it |

### Crews and supervision

| Command | Does |
|---|---|
| `crew start\|list\|focus\|stop` | Claude sessions in the project's herdr space ([herdr.md](herdr.md)) |
| `explore`, `wayfinder`, `groundwork` | Print that crew's brief; `--extra -` appends notes from stdin |
| `testcrews` | One test-writing crew per task, in parallel |
| `report` | A crew reports up: `working`, `needs-user`, `blocked`, `done`, `tool-bug` |
| `watch` | Block until something happens, print one event line, exit |
| `teardown` | Close finished tabs, stop leftover servers, save and quit Frame0 |
| `frame0 up\|save\|down` | The project's own Frame0 app |
| `guard` | The PreToolUse hook that keeps the orchestrator from editing code |

### Workspaces

| Command | Does |
|---|---|
| `workspace [<name>\|add\|key\|remove]` | List, switch, or manage workspaces ([workspaces.md](workspaces.md)) |

## Results

Each task run writes `.fast-coding/<project>/results/NNN.json` with every attempt's test output, timing, and cost.
Verify writes `results/verify.json`.
A run that dies shows as `interrupted` in `status`; `resume` re-runs what did not pass and keeps passed layers.
