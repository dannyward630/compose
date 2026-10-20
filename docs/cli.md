# CLI

This page lists every `compose` command and its flags.
The team lead runs them for you, and you run them yourself only in manual mode.

Run `compose` with no command on a terminal outside herdr to open the herdr session `compose` ([herdr.md](herdr.md)).
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
4. Run `compose sync --project my-feature`, and run it again after any Linear edit ([shape](tasks.md#sync)).
5. Run `compose run --project my-feature`, then `compose verify --project my-feature`.

When you ask, `compose stack --project my-feature --submit` pushes and opens one draft PR per layer.
After the PRs merge, `compose clean --project my-feature` removes what merged, moves those tasks to Done in Linear with their story and the feature, and keeps what did not merge.
A kept branch is named with its first unmatched commit.

Before the first run in a new repo, do these three things:

- Commit everything, because `run` refuses a dirty tree.
- Fill `verify.json` with the repo's lint and test commands ([verify.md](verify.md)).
- For OpenCode tasks only, add an `opencode.jsonc` allowing `edit` and `bash` so it never blocks on a prompt.

## Commands

### Projects

These commands create, list, and clean up projects.

| Command | Does |
|---|---|
| `setup` | Installs and configures everything `compose` needs ([new-machine.md](new-machine.md)). On a terminal it asks one question at a time (Quick start or Custom, a yes or no per missing step under Custom, each key with hidden input); `--yes`, or no terminal, runs the same steps with every default and never prompts. With `--dry-run` it asks the same questions and runs the same checks but changes nothing on the machine, prints each change as a `would` line, and ends with `dry run: nothing changed; N changes listed above`. It exits 1 when Claude Code is missing. Without `--yes` it also exits 1 when a required key is missing or the model probe fails. With `--yes` it exits 0 and ends with `compose is installed but not ready:` when a required step is missing |
| `update` | Pulls the checkout with `--ff-only`, relinks the CLI, the skill, and `bp`, and runs `doctor`. It stops when the checkout has local changes. When the branch has commits its upstream lacks, it lists each as `-` (already upstream under another hash) or `+` (only here) and prints the one command that gets it moving again: `reset --hard` when every one is `-`, else `rebase` |
| `doctor` | Checks every setup step (the tools, links, keys by presence only, pi's provider, the herdr config, the skill files). It prints one `MISSING: <name> (install: <command>)` line per absent or too-old step and exits 1 when a required one is missing; the default-on steps print `- optional`, and the designer rows print one `designer extras not set up` line. While `claude` is missing, the steps that need it share one `waiting on Claude Code` line. It also warns about a key still in `config.json` or `.env`, and about a gh that is not logged in (`gh auth` is also a required step, so that is a `MISSING` line too). `init` runs the same check first and stops before creating anything only when a required tool is missing, and `designer` checks Framelink first and stops before printing a brief |
| `init` | Creates branch `compose/<name>`, its worktree, and `.compose/<name>/`. `--here` uses this checkout, and `--after <project>` branches from another project |
| `projects` | Lists every project with done/total, last activity, title, and states, and each line ends with its `can start now:` line |
| `status` | Shows every project with every task, each with the `can start now:` line from `results/ready.json`. `--watch` redraws every 2 s, and asks git only when a result file or a branch changed |
| `clean` | Drops merged layers, moves the tasks proven merged to Done in Linear and rolls their story and the feature up, refreshes the `Ready` marks, and removes a fully merged project's worktree and branch, or keeps them while the command runs inside the worktree or the team lead has not reported done (its `done` removes them). A branch is merged when it is contained in the target, when every commit has its patch there, when merging it would change nothing, or when GitHub has a merged PR for it; the review base is checked first. A kept branch is named with its first unmatched commit. `--delete-unmerged` also drops unreviewed layers |
| `trail` | Sets trail up again in the project's worktree |

### Tasks

These commands load the tasks, dispatch them, and steer the run.

| Command | Does |
|---|---|
| `sync` | Stores the feature and its task issues, read from Linear with the workspace's key, and refreshes the `Ready` marks; `--stdin` reads JSON from stdin instead. A task blocked by an unfinished issue outside the feature's tasks is listed with `waits on <id> (<state>)`, and `run` holds it |
| `linear <verb>` | Reads and writes Linear with the workspace's key and prints compact lines: `get <id> [--body] [--comments]`, `list --parent <id>` or `--search "<terms>"` (with `--state`, `--label`), `create --title ... [--parent] [--label] [--state] [--blocked-by]`, `update <id>` (`--title`, `--state`, `--parent`, `--label`, `--blocked-by`, and `--section "## <heading>"`, `--append`, or `--description` for the body; `--section` replaces that H2 section, renames it when the body starts with another `## ` heading, and removes it when the body is empty), `comment <id>`, `labels [--create <name>]`, `project` (`--body` prints its description; `--section`, `--append`, or `--description` write it), and `doc create --title ...`, `doc list`, `doc get <id>`, or `doc update <id>` (`--title`, and the same body flags as `update`). Bodies come from `--file <path>` or stdin. `list`, `create`, and `doc list` use the project in `.compose/linear.json`; `get`, `update`, `comment`, and `doc update` refuse an issue or document in another project unless `--any-project`. `--json` prints the raw fields |
| `tasks` | Prints the task list to review, with files, `after`, and tests. It warns on shared files |
| `run` | Dispatches tasks. The flags are `--only 003,004`, `--attempts 3`, `--parallel N` (default `parallel` in the config, else 3), `--redo`, `--no-stack`, and `--trunk <branch>` |
| `done` | Records tasks finished by hand with `--only <ids> --note <why>` and moves them In Review on Linear |
| `triage` | Has a fast model clean or flag each passed task (`run` ends with it) |
| `resume` | Continues a run or verify that stopped on a billing halt. `--parallel N` sets tasks at once (default `parallel` in the config, else the halted run's) |
| `reflect` | Screens the settled decisions against evidence with Jev, using `--evidence -` and `--against "<line>"`. `--dismiss "<why>"` marks the evidence so far as answered, so later screens skip it |
| `hold` | Holds tasks back from dispatch with `--only <ids> --reason "<why>"`. `--release <ids>` or `all` releases them |
| `change start\|done\|undo` | Records a change of course. `undo C<n>` puts back what it touched |
| `spec-check` | Prints one `PASS|FAIL <id> <level>: <gaps>` line per issue of a feature's tree. `--stdin` reads sync JSON with no project. Exits 1 on any FAIL |
| `ready` | Labels `Ready` each story, and each feature of the epic, that is Todo or Backlog with every blocker Done or Canceled (a Design blocker counts at In Review); it writes `results/ready.json` and prints `can start now:`, and `compose linear labels --create Ready` creates the label. `sync`, the end of `run`, a `verify` PASS, and `clean` refresh the marks too |
| `bench` | Runs a frozen task set across models and reports pass rate, attempts, p50/p95 time, and cost |

### Verify and stack

These commands check the finished work and turn it into a stack.

| Command | Does |
|---|---|
| `verify` | Runs the local pipeline. `--fix 0` reports only, and `--skip-e2e` and `--skip-review` skip those stages |
| `stack` | Cuts passed task branches into review layers (`review_layer_lines` in verify.json, default 300 lines, groundwork and each task's tests included), at most `max_stack_prs` layers, and registers them as one gh stack on the real base. `--submit` pushes and opens one draft PR per layer, and stops while the base is ahead of its upstream; without it, each layer's PR title and body are printed, each marked `written` (from `.compose/<project>/pr/<name>.md`) or `generated` |
| `top` | Checks out the stack top for manual testing. `--detach` releases it |

### Teammates and supervision

These commands start the teammates, collect their reports, and supervise the team lead.

| Command | Does |
|---|---|
| `crew start\|list\|focus\|stop` | Manages teammates, the Claude sessions in the project's herdr space ([herdr.md](herdr.md)) |
| `explore`, `wayfinder`, `groundwork` | Prints that teammate's brief. `--extra -` appends notes from stdin |
| `planner` | Prints the planner teammate's brief. `--issue NEB-xxx` picks the ticket, default the project's feature. `--extra -` appends notes from stdin |
| `designer` | Prints the designer teammate's brief. `--figma <url or key>` stores the Figma file key, and `--extra -` appends notes from stdin |
| `designcrews` | Starts one `design-NNN` builder for only the design tasks whose blockers are In Review or Done, and prints `<id> waits on <ids>` for the rest. `--only <ids>` picks tasks, `--max N` caps builders started at once (default `design_concurrency` in verify.json, else 3, never `parallel` in the config; the rest are printed), and `--print` prints the briefs |
| `figma check\|tree\|judge` | `check --figma <url or key>` stores the target file key in `linear.json` and proves Framelink reads the file (one depth-1 fetch; it prints the token file path and the `claude mcp add` line when it cannot). `tree --only NNN --node <ids> [--depth n] [--bindings <file or ->]` fetches the nodes through Framelink into `results/NNN.tree.txt` and appends what the write script returned. `judge --only <ids>` asks Jev MET, NOT_MET, or UNCLEAR per acceptance criterion on that tree, confirms each NOT_MET, and exits 1 on a confirmed one |
| `testcrews` | Runs one test-writing teammate per task, in parallel, at most `parallel` from the config at once when it is set |
| `toolsmith` | Prints the toolsmith teammate's brief from the project's newest tool-bug entry. The maintainer's variant files, then fixes on a branch; anyone else's only reproduces, diagnoses, and files. It exits non-zero when the project has no entry |
| `tool-bug file --body <file>` | Scrubs the body file (line 1 is `# <command>: <symptom>`), searches open issues on prodoxx/compose, then posts a `bug` issue or comments on the match (`--comment <n>`, or `--new` to force a new issue), and records the URL in `tool-bugs.jsonl` as `issue`. Without maintainer rights or a logged-in gh it saves a draft under `~/.compose/tool-bugs/` and posts nothing until the same command runs with `--approved` |
| `report` | Lets a teammate report up with `working`, `needs-user`, `blocked`, `done`, `tool-bug`, or `contradiction` |
| `watch` | Blocks until something happens, prints one event line, and exits. `--now` prints the current state and marks it seen. `event ready=<ids>` lists only the issues that just became ready |
| `yolo [--push] [words]\|decided\|--clear-words\|off` | Records that the product owner is away in `results/yolo.json`: the engineering manager answers each question with the recommendation, and the words pre-answer questions verbatim. `--push` permits submitting the verified stack. `decided "<question>: <answer taken>"` logs an answer. `--clear-words` empties the words and keeps `since`, push, and the decisions. Words that start with `--repo` or `--project` or contain ` decided ` are refused with a hint about quoting: they are a whole command that a shell variable passed as one word. `off` prints the digest (your instructions, decided for you, waiting on you, tried and failed, done, cost) and archives the file as `yolo-<since>.json` |
| `teardown` | Closes finished tabs, stops leftover servers, and saves and quits Frame0 |
| `frame0 up\|save\|down` | Starts, saves, and stops the project's own Frame0 app |
| `guard` | Runs as the PreToolUse hook that keeps the team lead from editing code |
| `rewake` | Runs as the Stop hook that parks the team lead's next `watch` after each turn and wakes it on the event |
| `skillcheck` | Runs as the UserPromptSubmit and Skill PostToolUse hook that tells a `compose` session, once, which skill files changed since it read them |
| `timed <seconds> -- <command>` | Runs a command with a hard time limit, which is what teammates run tests and a project's own commands through: past the limit its whole process group is killed and the result is exit 124 with a hang hint. The command gets a scratch `~/.compose` config, a change to the real one is flagged unless a compose outside the command made it, and the output is scrubbed of secrets. The caller's stdin reaches the command (`< file` works), unless it is a terminal. compose's own commands (`sync`, `linear`, `status`, `verify`, ...) run directly, not through it: under it they have no workspace and no keys, and one that needs a key says so. At most `COMPOSE_TEST_SLOTS` (default 2) timed commands run at once on this machine; the next waits for a slot and says so. On SIGTERM or SIGHUP it ends the command, removes the scratch config, and exits 143 or 129 |

### Workspaces

One command lists, switches, and manages workspaces.

| Command | Does |
|---|---|
| `workspace [<name>\|add\|key\|remove]` | Lists, switches, or manages workspaces ([workspaces.md](workspaces.md)). `key <name>` sets the OpenRouter key; `--linear` sets the Linear key and `--typesafe` the TypeSafe key. Keys go to `~/.compose/auth.json` |

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
