# fast-coding

fast-coding runs the entire engineering workflow, from the first question to pull requests you can review in minutes.
You make the decisions and read the result.
A fleet of agents does everything in between, and you can watch and steer every one of them.

## The whole workflow, one command

Run `/fast-coding <what you want>` and the feature moves through every stage on its own.

1. **Explore.**
   An explore crew maps your codebase through graft, so no question or plan rests on a guess about the code.
2. **Decide.**
   A wayfinder puts every open decision on one Lavish page, each with options and a recommendation, and draws screen questions as Frame0 wireframes.
   You answer them all in one pass, or accept every recommendation with one click, and your answers go to the feature in Linear.
3. **Plan.**
   The strongest model writes the plan, the stories, and one Linear issue per task, each small enough for a fast model to finish in one short turn.
4. **Test first.**
   Test crews write every task's failing test from the spec in parallel, with holdout cases the implementers never see.
5. **Build.**
   Fast implementers each make one test pass in their own clone, side by side, in seconds per task.
6. **Review.**
   The orchestrator reviews each layer the moment it passes, and a fast triage flags the layers that need a closer read.
7. **Verify.**
   Lint and tests run first, then a confirmed model review, a Jev check of every acceptance criterion, and a real browser run against an assert you wrote, with a fix loop for anything that fails.
8. **Stack.**
   Passed tasks become one gh stack, and when you say so, each layer becomes a draft pull request.
9. **Correct course.**
   When a failure or a discovery shows a decision was wrong, only the tasks that rest on it pause.
   You make the call, the change is recorded in Linear with its reason, and any change can be undone.

Linear tracks the whole run, so the feature, its stories, and every task move through their states as the work does.
Inside herdr, every agent works in its own pane, and you can type into any of them.
Nothing is pushed until you say so, and fast-coding never merges anything.

The full walkthrough is in [docs/how-it-works.md](docs/how-it-works.md).

## Why we built it

Code was never the bottleneck.
The hard parts are deciding what to build and proving that it works.
fast-coding puts its strongest model on exactly those two jobs and hands the typing to fast models that cost about a cent a task.
You stay the one who decides.

**Tests come from your intent.**
Each task's test is written from the spec before any code exists.
It hides holdout cases the implementer never sees, so the only way to pass is to build the real behavior.

**Every task gets a fresh agent in a fence.**
One task runs in one fresh session, in its own clone, on the files it names, under 350 changed lines.
There is no long context to rot and no room to drift.

**Each job runs on the model that fits it.**
By default the strongest model plans, Opus writes the tests, GLM 5.3 Flash types the code, and Haiku handles the chores.
On a real seven-task project, GLM 5.3 Flash passed each task on its first try in 9 to 20 seconds.

**Done means proven.**
A finding from review stands only when a second call can quote the code that proves it.
A model saying it is done never counts.

**You review layers, one minute each.**
A 2,000-line branch turns into ten 100-line layers in dependency order, and a reviewer reads them one at a time.

**Every run shows its bill.**
Each run ends with the time every task took and the dollars spent with each provider.
The figures in this README come from small benchmarks and one prototype, and the numbers your own runs print are the ones to trust.

## Quick start

1. Install the tools listed in [docs/requirements.md](docs/requirements.md).
2. From this repo, install fast-coding with `ln -s "$PWD" ~/.claude/skills/fast-coding` and `ln -s "$PWD/bin/fast-coding" ~/.local/bin/`.
3. In the target repo, check out the branch the feature belongs on and open Claude Code.
4. Run `/fast-coding <what you want>` and answer the questions on the Lavish page it opens.
5. Review the task list, say go, and read the stack it builds.

## When to use it

Use fast-coding for features that split into small, independent pieces with clear tests.
Endpoints, a module and its callers, a fixture and the code that handles it, a batch of related fixes, and throwaway prototypes are all good fits.
Use it for anything you would rather review as a stack of small layers than as one big diff.

Skip it for one-line fixes and exploratory debugging, where the setup costs more than it saves.
Skip it when a task's test can't be written first, because that work isn't a task yet.
Skip it when every task would edit the same hot file, because tasks never share files.

## Main commands

The orchestrator runs these commands for you.
You only run them yourself in [manual mode](docs/cli.md#manual-mode).

| Command | What it does |
|---|---|
| `fast-coding init --project <name>` | Creates the project's branch and worktree |
| `fast-coding tasks --project <name>` | Shows the task list for you to review before dispatch |
| `fast-coding run --project <name>` | Dispatches the tasks to parallel implementers |
| `fast-coding verify --project <name>` | Runs the local verify pipeline |
| `fast-coding status [--project <name>] [--watch]` | Shows every project and every task |
| `fast-coding stack --project <name> --submit` | Pushes the stack and opens draft PRs |
| `fast-coding resume --project <name>` | Continues after a billing halt |
| `fast-coding clean --project <name>` | Removes what has merged |
| `fast-coding workspace [<name>]` | Lists or switches billing workspaces |

Every command is documented in [docs/cli.md](docs/cli.md).

## Docs

| Page | Read it for |
|---|---|
| [requirements.md](docs/requirements.md) | Tools, accounts, keys, and files outside the repo |
| [how-it-works.md](docs/how-it-works.md) | The loop, changing course, projects, Linear levels, and model choices |
| [cli.md](docs/cli.md) | Every command, manual mode, and flags |
| [herdr.md](docs/herdr.md) | Running the fleet visibly inside herdr |
| [tasks.md](docs/tasks.md) | The task issue format and `sync` |
| [verify.md](docs/verify.md) | `verify.json`, the stages, e2e, and jev |
| [workspaces.md](docs/workspaces.md) | Workspaces, model config, and billing halts |

## Development

Run the CLI tests with `python3 -m unittest discover -s tests`.
Run the jev tests with `cd jev && uv run pytest`.
`bin/fast-coding` uses only the Python standard library, and `jev/` is its own uv project.
