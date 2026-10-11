# fast-coding

With fast-coding, a feature idea becomes a reviewed, verified stack of small branches in one sitting.
A frontier model makes the decisions and checks the work, while cheap fast models write the code in parallel.

## Quick start

1. Install the tools listed in [docs/requirements.md](docs/requirements.md).
2. From this repo, install fast-coding with `ln -s "$PWD" ~/.claude/skills/fast-coding` and `ln -s "$PWD/bin/fast-coding" ~/.local/bin/`.
3. In the target repo, check out the branch the feature belongs on and open Claude Code.
4. Run `/fast-coding <what you want>` and answer the questions on the Lavish page it opens.
5. Review the task list, say go, and read the stack it builds.

Nothing is pushed until you say so, and fast-coding never merges anything.

## What you get

Each feature becomes one gh stack.
Every task is a small layer in dependency order, and each layer takes about a minute to read.

Tests come first.
Every task's test exists and fails before an implementer starts, and it includes holdout cases the implementer never sees.

Each task stays inside its fence.
An implementer may only touch the files its task names, it cannot change the protected tests, and its branch stays under 350 changed lines.

Verification happens for real.
Every finding from the model review is confirmed against the code, every acceptance criterion gets its own check, and a real browser runs the feature against an assert you wrote.

Changes of course happen in the open.
When the plan turns out to be wrong, only the affected tasks pause, and you make the call on anything you already settled.
Every change is recorded in Linear, and any change can be undone.

The accounting is honest.
Every run prints the wall time of each task and the dollars spent with each provider.

## When to use it

Use fast-coding for features that split into small, independent pieces with clear tests.
Endpoints, a module and its callers, a batch of related fixes, and throwaway prototypes are all good fits.

Skip it for one-line fixes and exploratory debugging, where the setup costs more than it saves.
Skip it when a task's test can't be written first, or when every task would edit the same hot file.

## How it works

1. **Find the way.**
   In a repo that already has code, an explore crew maps it first.
   A wayfinder crew then puts every open decision on one Lavish page, and your answers go to the feature in Linear.
2. **Plan.**
   The orchestrator writes the plan and the stories, plus one Linear issue per task, each with a failing test.
3. **Run.**
   Parallel implementers each make one test pass in their own clone.
   By default they are pi sessions running GLM 5.3 Flash.
4. **Verify.**
   Checks run first, then the model review, the acceptance checks, and the browser e2e.
   A fix loop takes another pass at anything that fails.
5. **Stack.**
   Passed tasks become a gh stack.
   When you ask, `stack --submit` opens one draft PR per layer.
6. **Change course.**
   A failure, a contradiction with Linear, or your own word makes Jev screen the settled decisions.
   The affected tasks are held, the plan changes as one recorded change, and the rest of the run keeps going.

The full walkthrough is in [docs/how-it-works.md](docs/how-it-works.md).

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
