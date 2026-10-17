# CLI

This page lists every `compose` command and its flags.
The team lead runs them for you, and you run them yourself only in manual mode.

Every command takes `--repo <path>` (default `.`) and `--project <name>`.
`--project` works from any checkout of the repository.
You can leave it out when the repo has one project.

## Normal mode

Open Claude Code in the repo and run:

```
/compose plan and build <feature> from ENG-123 and DESIGN.md
```

The team lead runs every command below for you.
You review the plan, the task list, and the stack.

## Manual mode

1. Run `compose init --project my-feature`, then work in the worktree it prints.
2. On Linear, write the feature issue (its description is the plan) and one task issue per task.
   End each task issue with a [`compose` block](tasks.md).
3. Write `{"feature": "ENG-123"}` to `.compose/my-feature/linear.json`, write each task's test, and commit.
4. Run `compose sync --project my-feature < issues.json`, and run it again after any Linear edit ([shape](tasks.md#sync)).
5. Run `compose run --project my-feature`, then `compose verify --project my-feature`.

When you ask, `compose stack --project my-feature --submit` pushes and opens one draft PR per layer.
After the PRs merge, `compose clean --project my-feature` removes what merged, moves those tasks to Done in Linear with their story and the feature, and keeps what did not merge.

Before the first run in a new repo, do these three things:

- Commit everything, because `run` refuses a dirty tree.
- Fill `verify.json` with the repo's lint and test commands ([verify.md](verify.md)).
- For OpenCode tasks only, add an `opencode.jsonc` allowing `edit` and `bash` so it never blocks on a prompt.

## Commands

### Projects

These commands create, list, and clean up projects.

| Command | Does |
|---|---|
| `doctor` | Checks every tool and skill file `compose` depends on (herdr, treehouse, graft, gh, gh stack, claude, npx, pi, bp, the `framelink-figma` MCP server and its token file, and the herdr, i-have-adhd, and writing-plans skill files). It prints one `MISSING: <name> (install: <command>)` line per absent or too-old one and exits 1 when a required one is missing; pi, bp, treehouse, and graft only warn, and Framelink warns as `needed for the designer`. `init` runs the same check first and stops before creating anything, and `designer` checks Framelink first and stops before printing a brief |
| `init` | Creates branch `compose/<name>`, its worktree, and `.compose/<name>/`. `--here` uses this checkout, and `--after <project>` branches from another project |
| `projects` | Lists every project with done/total, last activity, title, and states |
| `status` | Shows every project with every task. `--watch` redraws every 2 s |
| `clean` | Drops merged layers, moves the tasks proven merged to Done in Linear and rolls their story and the feature up, and removes a fully merged project's worktree and branch. `--delete-unmerged` also drops unreviewed layers |
| `graft` | Sets graft up again in the project's worktree |

### Tasks

These commands load the tasks, dispatch them, and steer the run.

| Command | Does |
|---|---|
| `sync` | Stores the feature and its task issues: `--from-linear` reads them from Linear, else JSON on stdin |
| `tasks` | Prints the task list to review, with files, `after`, and tests. It warns on shared files |
| `run` | Dispatches tasks. The flags are `--only 003,004`, `--attempts 3`, `--parallel 3`, `--redo`, `--no-stack`, and `--trunk <branch>` |
| `done` | Records tasks finished by hand with `--only <ids> --note <why>` and moves them In Review on Linear |
| `triage` | Has a fast model clean or flag each passed task (`run` ends with it) |
| `resume` | Continues a run or verify that stopped on a billing halt |
| `reflect` | Screens the settled decisions against evidence with Jev, using `--evidence -` and `--against "<line>"`. `--dismiss "<why>"` marks the evidence so far as answered, so later screens skip it |
| `hold` | Holds tasks back from dispatch with `--only <ids> --reason "<why>"`. `--release <ids>` or `all` releases them |
| `change start\|done\|undo` | Records a change of course. `undo C<n>` puts back what it touched |
| `spec-check` | Prints one `PASS|FAIL <id> <level>: <gaps>` line per issue of a feature's tree. `--stdin` reads sync JSON with no project. Exits 1 on any FAIL |
| `bench` | Runs a frozen task set across models and reports pass rate, attempts, p50/p95 time, and cost |

### Verify and stack

These commands check the finished work and turn it into a stack.

| Command | Does |
|---|---|
| `verify` | Runs the local pipeline. `--fix 0` reports only, and `--skip-e2e` and `--skip-review` skip those stages |
| `stack` | Cuts passed task branches into review layers (`review_layer_lines` in verify.json, default 300 lines, groundwork and each task's tests included) and registers them as one gh stack on the real base. `--submit` pushes and opens one draft PR per layer |
| `top` | Checks out the stack top for manual testing. `--detach` releases it |

### Teammates and supervision

These commands start the teammates, collect their reports, and supervise the team lead.

| Command | Does |
|---|---|
| `crew start\|list\|focus\|stop` | Manages teammates, the Claude sessions in the project's herdr space ([herdr.md](herdr.md)) |
| `explore`, `wayfinder`, `groundwork` | Prints that teammate's brief. `--extra -` appends notes from stdin |
| `planner` | Prints the planner teammate's brief. `--issue NEB-xxx` picks the ticket, default the project's feature. `--extra -` appends notes from stdin |
| `designer` | Prints the designer teammate's brief. `--figma <url or key>` stores the Figma file key, and `--extra -` appends notes from stdin |
| `designcrews` | Starts one `design-NNN` builder per open design task. `--only <ids>` picks tasks, `--max N` caps builders started at once (default 3, or `design_concurrency` in verify.json; the rest are printed), and `--print` prints the briefs |
| `figma check\|tree\|judge` | `check --figma <url or key>` stores the target file key in `linear.json` and proves Framelink reads the file (one depth-1 fetch; it prints the token file path and the `claude mcp add` line when it cannot). `tree --only NNN --node <ids> [--depth n] [--bindings <file or ->]` fetches the nodes through Framelink into `results/NNN.tree.txt` and appends what the write script returned. `judge --only <ids>` asks Jev MET, NOT_MET, or UNCLEAR per acceptance criterion on that tree, confirms each NOT_MET, and exits 1 on a confirmed one |
| `testcrews` | Runs one test-writing teammate per task, in parallel |
| `report` | Lets a teammate report up with `working`, `needs-user`, `blocked`, `done`, `tool-bug`, or `contradiction` |
| `watch` | Blocks until something happens, prints one event line, and exits. `--now` prints the current state and marks it seen |
| `yolo [--push] [words]\|decided\|off` | Records that the product owner is away in `results/yolo.json`: the engineering manager answers each question with the recommendation, and the words pre-answer questions verbatim. `--push` permits submitting the verified stack. `decided "<question>: <answer taken>"` logs an answer. `off` prints the digest (your instructions, decided for you, waiting on you, tried and failed, done, cost) and archives the file as `yolo-<since>.json` |
| `teardown` | Closes finished tabs, stops leftover servers, and saves and quits Frame0 |
| `frame0 up\|save\|down` | Starts, saves, and stops the project's own Frame0 app |
| `guard` | Runs as the PreToolUse hook that keeps the team lead from editing code |
| `rewake` | Runs as the Stop hook that parks the team lead's next `watch` after each turn and wakes it on the event |
| `skillcheck` | Runs as the UserPromptSubmit and Skill PostToolUse hook that tells a `compose` session, once, which skill files changed since it read them |

### Workspaces

One command lists, switches, and manages workspaces.

| Command | Does |
|---|---|
| `workspace [<name>\|add\|key\|remove]` | Lists, switches, or manages workspaces ([workspaces.md](workspaces.md)) |

## Results

Everything a run produces lands in `.compose/<project>/results/`.
Each task run writes `.compose/<project>/results/NNN.json` with every attempt's test output, timing, and cost.
Verify writes `results/verify.json`.
A run that dies shows as `interrupted` in `status`.
`resume` re-runs what did not pass and keeps passed layers.
`run`, `verify`, and `resume` work in their own session and write `results/<command>.log`.
The terminal that started one only streams that log.
Closing that terminal, or a crashed Claude session, leaves the work running.
Ctrl-C stops it.
