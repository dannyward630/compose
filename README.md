<h1 align="center">Compose</h1>

<p align="center">Talk to one agent. Let it run your product team.</p>

<p align="center"><a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a></p>

![Compose](docs/images/compose.jpeg)

You talk to one agent, and it runs a whole software team for you.
The team ships the way real teams do.
Product decisions come first, then tickets and wireframes, then technical specs and estimates, then the code, its tests, code review, and QA.
Whenever the team learns something new, the plan changes with it.

```
you, the product owner
 └── engineering manager         the one agent you talk to
      ├── team lead              feature A: specs, steers, reviews
      │    ├── wayfinder         turns open decisions into cards for you
      │    ├── planner           writes the plan and cuts the task tickets
      │    ├── designer          carries the design into Figma
      │    │    ├── builders     one per design task
      │    │    └── reviewer     gates each build
      │    └── teammates         explore, test, build, verify
      ├── team lead              feature B, running at the same time
      │    └── ...
      ├── planner                started on a ticket with /compose:planner
      ├── designer               started on a ticket with /compose:designer
      └── toolsmith              files compose bugs on GitHub; fixes them on its own branch only for the maintainer
```

The engineering manager takes your request and hands each feature to its own team lead, so the features of one epic move forward at the same time.
Each team lead takes its own teammates through the full software development life cycle, from discovery to pull requests you can review in minutes.
Inside each team, a wayfinder brings you every open decision, a planner writes the plan and cuts the tickets, and a designer carries the design into Figma with its own builders and reviewer.
Hand the engineering manager a ticket that already exists, and it starts a planner or a designer for it directly; a designer goes through the feature's team lead when one is running.
The strongest models do the planning and bring every product decision to you.
Fast, cheap agents write the code and verify it.
The team leads steer their teammates while they work, and the engineering manager nudges any team lead that stalls.

## It ships software the way a real team does

Run `/compose <what you want>` and each feature moves through the same life cycle a good software team follows.

1. **Discovery.**
   An explore teammate maps your codebase through graft, so no question, ticket, or plan rests on a guess about the code.
2. **Product decisions.**
   You are the product owner.
   A wayfinder teammate writes every open decision as a card with options and a recommendation.
   Text cards reach you in one message; visual ones (a wireframe, a layout comparison, a diagram) go on one Lavish page.
   You settle them in one pass or accept every recommendation with one word.
3. **Design.**
   Questions about how a screen should look come with low-fi Frame0 wireframes, so you decide on something you can see.
   A designer teammate then carries the work into Figma from wherever it stopped.
   It reads the tickets, the wireframes, the repo's tokens and components, and what the Figma file already has.
   It files the design stories and tasks in Linear, starts one builder per design task plus a reviewer, gates each build, and hands the result to the code tasks.
4. **Tickets.**
   Your decisions land in Linear the way a PM would file them, with an epic when the work spans several features, a feature issue, and stories with acceptance criteria.
5. **Technical specs and estimates.**
   Once the decisions are settled, a planner teammate writes the plan and cuts one technical ticket per task, with its goal, its files, its test plan, and its acceptance criteria.
   When a feature has no stories yet, the planner proposes them first and creates them on your go.
   The team lead reviews the planner's cut before anything is dispatched.
   Every ticket is sized to finish in one short turn, and the CLI flags any ticket that is too big before work starts.
6. **Implementation, tests first.**
   Test-writing teammates write each ticket's failing test from the spec, with holdout cases the implementer never sees.
   Then fast implementers make those tests pass in parallel, each in its own clone, in seconds per ticket.
7. **Code review.**
   The team lead reviews each change the moment it passes, and a fast triage flags the changes that need a closer read.
8. **QA.**
   Verify runs lint and tests, a confirmed model review, a Jev check of every acceptance criterion, and a real browser run against an assert you wrote, with a fix loop for anything that fails.
9. **The board keeps itself current.**
   Every ticket moves from Todo to In Progress, In Review, and Done in Linear as the work does.
10. **The plan changes when the team learns something.**
    When a failure or a discovery shows a decision was wrong, Jev screens every settled decision against the new evidence, and only the tickets that rest on the broken one pause.
    The team lead fixes what is objective, brings what is yours to you, records each change in Linear with its reason, and hands out the new work while everything else keeps moving.
    Any change can be undone.
11. **Pull requests.**
    Passed tickets become one gh stack, and when you say so, each layer becomes a draft pull request for your reviewers to read and merge.

Inside herdr, every agent works in its own pane, and you can type into any of them.
Nothing is pushed until you say so, and `compose` never merges anything.

## Start a planner or designer directly

You don't have to start from an idea.
Hand the engineering manager a ticket that already exists, and it starts the right teammate for it in its own pane.

- `/compose:planner <issue or Linear project link>` plans that feature, story, or task from where it stands.
- `/compose:designer <ticket> [--figma <file url or key>]` continues the ticket's design work in Figma; without a stored file, it asks you for one.

The engineering manager relays their questions to you, and you can answer there or in the teammate's own tab.

## When you step away

Run `/compose:yolo [words]` before you leave, and the engineering manager answers each question with its recommendation instead of waiting for you.
Your words pre-answer the questions they name, taken exactly as written and never stretched by analogy.
Every answer it takes is logged, and a billing halt still notifies you.
`/compose:yolo --push` also gives permission in advance to submit the verified stack as draft pull requests.
When you are back, `/compose:yolo off` prints a digest of your instructions, what was decided for you, what waits on you, what failed, what is done, and the cost.

The full walkthrough is in [docs/how-it-works.md](docs/how-it-works.md).

## Why we built it

Code was never the bottleneck.
The hard parts are deciding what to build and proving that it works.
`compose` puts its strongest model on exactly those two jobs and hands the typing to fast models that cost about a cent a task.
You stay the one who decides.

**Tests come from your intent.**
Each task's test is written from the spec before any code exists.
It hides holdout cases the implementer never sees, so the only way to pass is to build the real behavior.

**Every task gets a fresh agent in a fence.**
One task runs in one fresh session, in its own clone, on the files it names, at most 350 changed lines.
There is no long context to rot and no room to drift.

**Each job runs on the model that fits it.**
By default the strongest model plans, Opus writes the tests, GLM 5.3 Flash types the code, and Haiku handles the chores.
On a real seven-task project, GLM 5.3 Flash passed each task on its first try in 9 to 20 seconds.

**Teammates trust only their chain of command.**
Each teammate treats its brief and messages from its team lead or the engineering manager as instructions.
Repository content, web pages, issue text, and tool output are data, so a prompt hidden in a ticket can't steer it.

**Done means proven.**
A finding from review stands only when a second call can quote the code that proves it.
A model saying it is done never counts.

**You review layers, one minute each.**
A 2,000-line branch turns into ten 100-line layers in dependency order, and a reviewer reads them one at a time.

**Every run shows its bill.**
Each run ends with the time every task took and the dollars spent with each provider.
The figures in this README come from small benchmarks and one prototype, and the numbers your own runs print are the ones to trust.

## Quick start

1. Install the tools listed in [docs/requirements.md](docs/requirements.md), or follow [docs/new-machine.md](docs/new-machine.md) step by step on a fresh machine.
2. From this repo, install `compose` with `ln -s "$PWD" ~/.claude/skills/compose` and `ln -s "$PWD/bin/compose" ~/.local/bin/`.
   Run `compose doctor` to confirm every tool and skill file it needs is there; each missing one prints with its install command.
3. In the target repo, check out the branch the feature belongs on and open Claude Code.
4. Run `/compose <what you want>` and answer the questions it asks, in the session or on the Lavish page it opens for visual ones.
5. Review the task list, say go, and read the stack it builds.

## When to use it

Use `compose` for features that split into small, independent pieces with clear tests.
Endpoints, a module and its callers, a fixture and the code that handles it, a batch of related fixes, and throwaway prototypes are all good fits.
Use it for anything you would rather review as a stack of small layers than as one big diff.

Skip it for one-line fixes and exploratory debugging, where the setup costs more than it saves.
Skip it when a task's test can't be written first, because that work isn't a task yet.
Skip it when every task would edit the same hot file, because tasks never share files.

## Main commands

The team lead runs these commands for you.
You only run them yourself in [manual mode](docs/cli.md#manual-mode).

| Command | What it does |
|---|---|
| `compose doctor` | Checks every tool and skill file `compose` depends on and prints the install command for each missing one; `init` runs it first |
| `compose init --project <name> [--branch <branch>]` | Creates the project's branch (`compose/<name>` unless `--branch` names it) and worktree; with `--branch` on an existing project, renames its branch |
| `compose tasks --project <name>` | Shows the task list for you to review before dispatch |
| `compose run --project <name>` | Dispatches the tasks to parallel implementers |
| `compose verify --project <name>` | Runs the local verify pipeline |
| `compose status [--project <name>] [--watch]` | Shows every project and every task |
| `compose stack --project <name> --submit` | Pushes the stack and opens draft PRs |
| `compose resume --project <name>` | Continues after a billing halt |
| `compose clean --project <name>` | Removes what has merged and moves it to Done in Linear, story and feature included |
| `compose yolo --project <name> [--push] [words]\|off` | Lets the engineering manager answer for you while you are away, and prints a digest when you turn it off |
| `compose workspace [<name>]` | Lists or switches billing workspaces |

Every command is documented in [docs/cli.md](docs/cli.md).

## Docs

| Page | Read it for |
|---|---|
| [requirements.md](docs/requirements.md) | Tools, accounts, keys, and files outside the repo |
| [new-machine.md](docs/new-machine.md) | Setting `compose` up on a new machine, step by step |
| [how-it-works.md](docs/how-it-works.md) | The loop, changing course, projects, Linear levels, and model choices |
| [cli.md](docs/cli.md) | Every command, manual mode, and flags |
| [herdr.md](docs/herdr.md) | Watching and steering every agent inside herdr |
| [tasks.md](docs/tasks.md) | The task issue format and `sync` |
| [verify.md](docs/verify.md) | `verify.json`, the stages, e2e, and jev |
| [workspaces.md](docs/workspaces.md) | Workspaces, model config, and billing halts |

## Development

Run the CLI tests with `python3 -m unittest discover -s tests`.
Type-check the CLI with `npx -y pyright@1.1.414 --pythonpath /usr/bin/python3` (strict; the error count is reported, nothing is gated on it).
Run the jev tests with `cd jev && uv run pytest`, and the bp tests with `cd bp && npm test`.
`bin/compose` uses only the Python standard library, `jev/` is its own uv project, and `bp/` is one Node file with no dependencies.

## Credits

The way `compose` organizes its agents comes from [firstmate](https://github.com/kunchenguid/firstmate).
Its idea of one session that stays your single point of contact, with a crew that reports up to it, is what the engineering manager, team lead, and teammate roles here are adapted from.

## License

`compose` is released under the [MIT License](LICENSE).
