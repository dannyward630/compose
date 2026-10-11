# Task issues

A task is a Linear issue under the project's feature, directly or under a story.
Its title is the task's title.
Its description is the implementer's brief and ends with the block the CLI reads:

````markdown
## Goal
One paragraph. What to build, where, exact export names.

## Acceptance criteria
- One bullet per behavior. Each is checked by the test.

## Test plan
- How to run: the `test:` command below.
- Covered: which behaviors the test exercises, in words.
- Holdout: the test has cases not listed here.

## Constraints
- No new dependencies. Do not edit protected files.

```fast-coding
id: 002
files: extension/snapshot.js
protected: tests/snapshot.test.js
test: node --test 'tests/**/*.test.js'
```
````

- `after` is the issue's "blocked by" links to other tasks of the feature; each becomes the layer this task stacks on.
- `model:` picks another implementer for one task; leave it unset unless the captain decided otherwise.
- Issues without the block, such as stories, are not tasks.

## Right-sized

- One to three files.
- One test command.
- Under ten criteria.
- The test fails on HEAD.

If you cannot write the test, it is not a task yet.

## Sync

The orchestrator reads the feature and every issue under it with its Linear MCP tools and pipes them to `fast-coding sync`:

```json
{"feature": {"id": "ENG-123", "title": "...", "description": "<the feature's description, plan included>"},
 "issues": [{"id": "ENG-124", "title": "...", "description": "<brief + fast-coding block>", "status": "Todo", "blockedBy": ["ENG-125"]}]}
```

`sync` refuses a feature other than the one `linear.json` names, a block without `id` or `test`, and an id used twice.
`run`, `verify`, `resume`, `bench`, and `tasks` read what was last synced, so the orchestrator syncs right before each.

The CLI writes to Linear only to keep states true, and only when the active workspace has a Linear key.
Everything else on Linear is written by the orchestrator through the Linear MCP.

`.fast-coding/<project>/` holds only the CLI's files: `linear.json`, `verify.json`, `results/`, the wayfinder's Lavish page, and the Frame0 design file.
Nothing about the work is written to a file in the repo.
