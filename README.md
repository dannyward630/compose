# fast-coding

Turn a feature idea into a reviewed, verified stack of small branches in one sitting.
A frontier model decides and checks; cheap fast models type the code in parallel.

## Quick start

1. Install the tools listed in [docs/requirements.md](docs/requirements.md).
2. From this repo, install fast-coding with `ln -s "$PWD" ~/.claude/skills/fast-coding` and `ln -s "$PWD/bin/fast-coding" ~/.local/bin/`.
3. In the target repo, check out the branch the feature belongs on and open Claude Code.
4. Run `/fast-coding <what you want>` and answer the questions on the Lavish page it opens.
5. Review the task list, say go, and read the stack it builds.

Nothing is pushed until you say so, and fast-coding never merges anything.

## Why we built it

The expensive part of software is deciding what to build and checking that it works.
Typing the code is the cheap part.
fast-coding spends the frontier model only on deciding and checking, and it makes the typing nearly free.
On the prototype that built fast-coding, the typing came to about a cent per task.

Here is what that buys you over a single Claude session.

**It is cheaper, and it runs in parallel.**
One Claude session is one worker on a subscription with rate limits.
fast-coding runs its implementers side by side for cents, and it saves the subscription for the planning and review that only a frontier model does well.

**Tests come before code, by construction.**
Every task's test exists and fails before an implementer starts, and it includes holdout cases the implementer never sees.
A lone model tends to write the code first and then write tests that fit the code.

**Scope stays where you put it.**
Each task is fenced in.
An implementer may only touch the files its task names, it cannot change the protected tests, it adds no documents, and its branch stays under 350 changed lines.
A long single session drifts, and a fenced task has nowhere to drift to.

**The output is sized for review.**
Each feature becomes one stack, with one layer per task in dependency order.
A 2,000-line branch turns into ten 100-line layers a reviewer can read one at a time.

**The proof comes from outside the model.**
Parallel fast-model reviews raise findings, and each high or medium finding stands only if a second call can quote the code that proves it.
Jev checks every acceptance criterion, a real browser runs the feature against an assert you wrote, and a fix loop handles what fails.
A model saying it is done never counts as proof.

**The plan can change without losing the run.**
When evidence shows a decision was wrong, only the tasks that rest on it pause.
You make the call on anything you settled, every change is recorded in Linear, and any change can be undone.

**The accounting is honest.**
Every run ends with the wall time of each task and the dollars spent with each provider.

The speed and cost figures here come from small benchmarks and one prototype.
Every real run prints its own numbers, and those are the ones to trust.

## When to use it

Use fast-coding for features that split into small, independent pieces with clear tests.
Endpoints, a module and its callers, a fixture and the code that handles it, a batch of related fixes, and throwaway prototypes are all good fits.
Use it for anything you would rather review as a stack of small layers than as one big diff.

Skip it for one-line fixes and exploratory debugging, where the setup costs more than it saves.
Skip it when a task's test can't be written first, because that work isn't a task yet.
Skip it when every task would edit the same hot file, because tasks never share files.

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
