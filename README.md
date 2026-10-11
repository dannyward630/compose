# fast-coding

Turn a feature idea into a reviewed, verified stack of small branches in one sitting.
A frontier model decides and checks; cheap fast models type the code in parallel.

## Quick start

1. Install the required tools: [docs/requirements.md](docs/requirements.md).
2. Install fast-coding: `ln -s "$PWD" ~/.claude/skills/fast-coding` and `ln -s "$PWD/bin/fast-coding" ~/.local/bin/` from this repo.
3. In the target repo, check out the branch the feature belongs on and open Claude Code.
4. Run `/fast-coding <what you want>`, then answer the questions on the Lavish page it opens.
5. Review the task list, say go, then read the stack it builds.

Nothing is pushed until you say so, and fast-coding never merges.

## What you get

- **One gh stack per feature**: one small layer per task, in dependency order, each readable in a minute.
- **Tests first**: every task's test exists and fails before an implementer starts, with holdout cases it cannot see.
- **Fenced tasks**: named files only, protected tests untouched, under 350 changed lines.
- **Real verification**: confirmed model review, acceptance checks per criterion, and a real browser run with an assert you wrote.
- **Changes of course in the open**: when the plan turns out wrong, only the affected tasks pause, you decide what you settled, and every change is recorded in Linear and can be undone.
- **Honest accounting**: every run prints wall time per task and dollars per provider.

## When to use it

Use it for features that split into small independent pieces with clear tests: endpoints, a module plus its callers, a batch of related fixes, a throwaway prototype.

Skip it for:

- one-line fixes and exploratory debugging, where the overhead wins;
- work whose test cannot be written first;
- changes every task would make to the same hot file.

## How it works

1. **Find the way**: in a repo with code an explore crew maps it first; then a wayfinder crew asks every open decision on one Lavish page, and the answers go to the feature in Linear.
2. **Plan**: the orchestrator writes the plan, stories, and one Linear issue per task, each with a failing test.
3. **Run**: parallel implementers (pi on GLM 5.3 Flash by default) each make one test pass in their own clone.
4. **Verify**: checks, then model review, acceptance checks, and browser e2e, with a fix loop.
5. **Stack**: passed tasks become a gh stack; `stack --submit` opens one draft PR per layer when you ask.
6. **Change course**: a failure, a contradiction with Linear, or your word makes Jev screen the settled decisions; affected tasks are held, the plan changes as one recorded change, and the rest keeps running.

Details: [docs/how-it-works.md](docs/how-it-works.md).

## Main commands

The orchestrator runs these for you; run them yourself only in [manual mode](docs/cli.md#manual-mode).

| Command | Does |
|---|---|
| `fast-coding init --project <name>` | Create the project's branch and worktree |
| `fast-coding tasks --project <name>` | Show the task list to review before dispatch |
| `fast-coding run --project <name>` | Dispatch tasks to parallel implementers |
| `fast-coding verify --project <name>` | Run the local verify pipeline |
| `fast-coding status [--project <name>] [--watch]` | Show every project and task |
| `fast-coding stack --project <name> --submit` | Push the stack and open draft PRs |
| `fast-coding resume --project <name>` | Continue after a billing halt |
| `fast-coding clean --project <name>` | Remove what has merged |
| `fast-coding workspace [<name>]` | List or switch billing workspaces |

Every command: [docs/cli.md](docs/cli.md).

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

- CLI tests: `python3 -m unittest discover -s tests`
- jev tests: `cd jev && uv run pytest`
- `bin/fast-coding` is Python standard library only; `jev/` is its own uv project.
