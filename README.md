# fast-coding

You talk to one agent, and it runs a whole software team for you.
The team ships the way real teams do.
Product decisions come first, then tickets and wireframes, then technical specs and estimates, then the code, its tests, code review, and QA.
Whenever the team learns something new, the plan changes with it.

```
you, the product owner
 └── engineering manager   the one agent you talk to
      ├── team lead        feature A: specs, steers, reviews
      │    └── teammates   explore, decide, test, build, verify
      └── team lead        feature B, running at the same time
           └── teammates   explore, decide, test, build, verify
```

The engineering manager takes your request and hands each feature to its own team lead, so the features of one epic move forward at the same time.
Each team lead takes its own teammates through the full software development life cycle, from discovery to pull requests you can review in minutes.
The strongest models do the planning and bring every product decision to you.
Fast, cheap agents write the code and verify it.
The team leads steer their teammates while they work, and the engineering manager nudges any team lead that stalls.

## It ships software the way a real team does

Run `/fast-coding <what you want>` and each feature moves through the same life cycle a good software team follows.

1. **Discovery.**
   An explore teammate maps your codebase through graft, so no question, ticket, or plan rests on a guess about the code.
2. **Product decisions.**
   You are the product owner.
   A wayfinder teammate writes every open decision as a card with options and a recommendation.
   Text cards reach you in one message; visual ones (a wireframe, a layout comparison, a diagram) go on one Lavish page.
   You settle them in one pass or accept every recommendation with one word.
3. **Design.**
   Questions about how a screen should look come with low-fi Frame0 wireframes, so you decide on something you can see.
   High-fi designs are on the roadmap.
4. **Tickets.**
   Your decisions land in Linear the way a PM would file them, with an epic when the work spans several features, a feature issue, and stories with acceptance criteria.
5. **Technical specs and estimates.**
   The team lead specs one technical ticket per task, with its goal, its files, its test plan, and its acceptance criteria.
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
4. Run `/fast-coding <what you want>` and answer the questions it asks, in the session or on the Lavish page it opens for visual ones.
5. Review the task list, say go, and read the stack it builds.

## When to use it

Use fast-coding for features that split into small, independent pieces with clear tests.
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
| [herdr.md](docs/herdr.md) | Watching and steering every agent inside herdr |
| [tasks.md](docs/tasks.md) | The task issue format and `sync` |
| [verify.md](docs/verify.md) | `verify.json`, the stages, e2e, and jev |
| [workspaces.md](docs/workspaces.md) | Workspaces, model config, and billing halts |

## Development

Run the CLI tests with `python3 -m unittest discover -s tests`.
Run the jev tests with `cd jev && uv run pytest`.
`bin/fast-coding` uses only the Python standard library, and `jev/` is its own uv project.

## Credits

The way fast-coding organizes its agents comes from [firstmate](https://github.com/kunchenguid/firstmate).
Its idea of one session that stays your single point of contact, with a crew that reports up to it, is what the engineering manager, team lead, and teammate roles here are adapted from.
