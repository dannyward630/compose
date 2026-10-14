# Task issues

Each task is a Linear issue with a brief the implementer follows and a block the CLI reads.
This page shows that format and what `sync` does with it.

A task is a Linear issue under the project's feature, directly or under a story.
Its title is the task's title.
Its description is the implementer's brief and ends with the block the CLI reads.
A complete description looks like this:

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
- No new dependencies beyond what the goal names. Do not edit protected files.

```fast-coding
id: 002
files: extension/snapshot.js
protected: tests/snapshot.test.js
test: node --test 'tests/**/*.test.js'
```
````

Three more rules apply to the block and the issue around it:

- The `after` field comes from the issue's "blocked by" links to other tasks of the feature.
  Each linked task becomes the layer this task stacks on.
- The `model:` field picks another implementer for one task.
  Leave it unset unless the product owner decided otherwise.
- Only an issue with the block counts as a task.
  Stories, for example, have none.

## Design tasks

A design task is the same issue with `kind: design` and a `nodes:` line in place of the `files:` line.
The `nodes:` line lists the page and frames the builder draws, like `Checkout/Cart, Checkout/Pay`.
The optional `figma:` line is a file key or url for a task whose file is not the project's stored one.
The `test:` command is `fast-coding figma judge --project <slug> --only NNN`.

````markdown
```fast-coding
id: 006
kind: design
nodes: Checkout/Cart, Checkout/Pay
figma: AbCdEf123456
test: fast-coding figma judge --project my-feature --only 006
```
````

Three rules apply to design tasks.
Two design tasks never share a page.
A design task never runs, stacks, or is judged from files.
The builder saves the node tree as text under `results/`, and the judge reads it.

## Right-sized

A task is ready when it meets all four of these:

- It touches one or two files.
- It has one test command.
- It has at most five criteria.
- Its test fails on HEAD.

If you cannot write the test, it is not a task yet.

## Sync

The team lead reads the feature and every issue under it with its Linear MCP tools and pipes them to `fast-coding sync`.
The JSON has this shape:

```json
{"feature": {"id": "ENG-123", "title": "...", "description": "<the feature's description, plan included>"},
 "issues": [{"id": "ENG-124", "title": "...", "description": "<brief + fast-coding block>", "status": "Todo", "blockedBy": ["ENG-125"]}]}
```

`sync` refuses a feature other than the one `linear.json` names, a block without `id` or `test`, and an id used twice.
`run`, `verify`, `resume`, `bench`, and `tasks` read what was last synced, so the team lead syncs right before each.

The CLI writes to Linear only to keep states true, and only when the active workspace has a Linear key.
The team lead writes everything else on Linear through the Linear MCP.

`.fast-coding/<project>/` holds only the CLI's files.
Those are `linear.json`, `verify.json`, `results/`, the wayfinder's Lavish page, and the Frame0 design file.
Nothing about the work is written to a file in the repo.
