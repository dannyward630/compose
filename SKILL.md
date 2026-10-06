---
name: fast-coding
description: The full fast loop for a feature, from first question to verified stacked branches. Find the way with wayfinder until the decisions are settled, as tickets on the repo's Linear project, plan, split into tiny numbered tasks with tests, fan the tasks out to parallel implementers (pi running gpt-oss-120b, pinned to Cerebras by an OpenRouter preset; OpenCode and Claude available per task), verify locally with jev-ultrafast browser runs and a Mercury review, register each chain as a gh stack, keep every task's Linear issue in step, and inside herdr run the implementers as named agents in a per-project space that the orchestrator steers. Use when the user says "fast-coding", "fast loop", "fan out", or asks to build a feature or prototype fast. Works in any repo.
---

# fast-coding

You are the orchestrator. The implementer is pi running gpt-oss-120b on Cerebras (through the OpenRouter preset `gpt-oss-120b-cerebras`); OpenCode or Claude can take a task via `model:`. Verification is local; nothing is pushed.
This skill is the whole flow: the moment the user invokes it with a task, start at step 0 and carry it through to verified, stacked branches.

| Who | Does | Never does |
|---|---|---|
| You (orchestrator) | Find the way with the user (wayfinder), write the spec and plan, split into tasks, mirror the feature and every task on Linear and move them through its states, write each acceptance test, dispatch, review diffs, run verify, re-split escalated tasks into smaller ones, submit the stack when told | Type implementation a task file covers (unless the blocker is infrastructure); merge anything: a human reviewer merges the PRs on GitHub |
| Implementer (fast model via pi or OpenCode; inside herdr a named pi agent in its own tab) | One task file, the named files, until its test passes, under 350 changed lines, adding no documents | Edit protected files, plan, touch other tasks, address the captain |
| `fast-coding verify` | Checks, jev-ultrafast browser e2e, Mercury diff review | Push, open PRs, run CI |

## Workflow

### 0. Know the repo's Linear project
Everything that would be a ticket lives on Linear, never as files in the repo: the feature, its decision tickets, its tasks.
Read `.fast-coding/linear.json` at the repo root: `{"project": "<Linear project URL>", "team": "Engineering"}`.
If it does not exist, ask the user for the link to the Linear project this repo's work belongs to, write the file with that URL and the team `Engineering` (unless the user names another), and commit it on the user's branch before anything else.
All Linear reads and writes are yours, through the Linear MCP tools (`save_issue`, `get_issue`, `list_issues`, `save_comment`). The CLI never talks to Linear.

### 0h. Inside herdr, the fleet is visible and steerable
You are inside herdr when `HERDR_ENV=1` (herdr also sets `HERDR_SOCKET_PATH`, `HERDR_PANE_ID`, `HERDR_WORKSPACE_ID`). Then invoke the `herdr` skill; it carries the safety rules for panes and agents.
`herdr agent get $HERDR_PANE_ID` tells which harness you are (`claude` under Claude Code, which also sets `CLAUDECODE=1`; `pi`; ...). The flow is the same for any orchestrator; only the harness-specific tools differ.
The CLI builds the topology by itself, named so the captain reads it at a glance:
- **space** `<slug>`: the project's worktree, opened as a herdr worktree workspace grouped under the repo's space (`init` and `run` create it)
- tab **`status`**: `fast-coding status --watch` running live; tab **`shell`**: a shell in the project worktree
- one tab per task, **`NNN <title>`**, holding the task's implementer: an interactive pi agent named **`<slug>-NNN`**, with state labels (`attempt 2/3`, `passed`, `rejected_size`) and tokens (`model`, `cost`) on its pane
- tab **`verify HH:MM`** per verify run: one pane per stage (`checks`, `e2e <name>`, `review`, `jev`), reported `working`, then `idle` ok or `blocked` FAIL
Your own pane stays where the captain started you. Name it: `herdr agent rename $HERDR_PANE_ID <slug>-orchestrator` and `herdr pane rename $HERDR_PANE_ID "<slug> orchestrator"`.
Outside herdr the same commands run headless and nothing is shown; the skill is identical.

### 0a. Put the work in a project, in its own worktree
A project is one feature: its own git worktree and branch, one plan, one set of tasks, one gh stack. The moment the user invokes you with a task, decide which project it belongs to before anything else:
- Run `fast-coding projects --repo <path>`. If the request continues a feature that already has a project (same spec, same area of the code, or the user names it), use that project: new tasks get the next ids and become new layers of its stack.
- Otherwise create one: `fast-coding init --repo <path> --project <slug>`, where `<slug>` is a short kebab-case name for the feature in the user's words (`custom-dropdowns`, `workday-login`), not the repo's name and not a date. This creates branch `fast-coding/<slug>` from the branch the user is on and a worktree `../fast-coding-<slug>` next to the repo, with `.fast-coding/<slug>/` committed there. Tell the user the project name and the worktree path in your first reply.
- Every project has one **feature issue** on Linear: a top-level issue in the repo's Linear project, title in the user's words, labelled `wayfinder:map`, holding the wayfinder map body. Create it when you create the project and record its identifier (`ENG-123`) in `.fast-coding/<slug>/linear.json` as `{"feature": "ENG-123"}`. Decision tickets and tasks are its sub-issues, so the whole feature reads as one tree in Linear.
- From then on everything you do for this project happens in that worktree: GRILLING.md additions, the plan, task files, acceptance tests, every commit, every `fast-coding` command (`--repo <worktree>`, or any checkout with `--project <slug>`: the CLI resolves it). The user's own checkout and branch are never touched. Several projects can run at the same time, each in its own worktree with its own stack.
- The stack's trunk is `fast-coding/<slug>`; PRs target it, and one final PR takes the project branch to the user's branch.
- Never mix two features in one project, and never spread one feature over two. If a request is really two features, make two projects and say so.
`fast-coding status --repo <path>` shows every project in every worktree with all its tasks; `--project <name>` shows one; `--watch` follows a run live. Use these when reporting progress.

### 0b. Find the way first when the decisions are not written down
A settled spec is a feature issue whose map says the way is clear: no open decision sub-issues, and `## Not yet specified` empty. A repo file (`DESIGN.md`, a PRD) counts too when the user points at it.
If none exists for this piece of work, do not plan yet: invoke the `wayfinder` skill with the feature issue as the map. Wayfinder's tracker is Linear here, and this is how its operations map:
- the **map** is the feature issue; its description is the map body (Destination, Notes, Decisions so far, Not yet specified, Out of scope)
- a **ticket** is a sub-issue of the feature issue, labelled `wayfinder:<type>` (`research`, `prototype`, `grilling`, `task`), body `## Question`
- **blocking** is Linear's native "blocked by" relation (`save_issue` with `blockedBy`), so the frontier shows in Linear's own UI
- the **frontier** is `list_issues` on the feature's sub-issues: open, no unresolved blockers, unassigned
- **claim** by assigning the ticket to the user; **resolve** by posting the answer as a comment, setting the state to Done, and appending the one-line gist to the map's Decisions so far
Wayfinder resolves one ticket per session, with the user, one question at a time and your recommendation on each; the grilling it runs is HITL, never answer for the user. When it reports no fog (the way is already clear in one sitting), its grilling is the spec: write the decisions into the map's Decisions so far and continue to step 1.
If a spec exists, read it and do not reopen its decisions. Open a decision ticket only for what it leaves open that the plan needs.

### 1. Plan from the spec
Input is the feature issue's map and resolved tickets, plus `DESIGN.md`, a PRD, whatever the repo already had.
Read all of it. Then invoke `superpowers:writing-plans` and write the plan to `.fast-coding/<project>/plan.md` inside the project's worktree, committed on `fast-coding/<project>`.
`<project>` is a short slug for this piece of work, one repo can hold several.
The plan follows writing-plans conventions: numbered steps, each with files touched, the test that proves it, and explicit dependencies.
Decisions already made in the spec are not reopened.

### 2. Split into tasks
Turn each plan step into `.fast-coding/<project>/tasks/NNN-slug.md` (format below).
A task is right-sized when all of these hold:
- one to three files, one test command, under ten acceptance criteria
- no open design choices; every "how" is stated or obvious from the named files
- the whole task plus the files it touches fits comfortably in 40K tokens
- its branch will change at most 350 lines (added plus deleted). The CLI rejects a bigger branch, so size the task for it
- it adds no documents. Implementers never create .md, .txt, .rst, or docs/ files; the CLI rejects a branch that does. Docs are the orchestrator's, edited by hand after the reviewer has merged the PRs, only when the user asked for them
- it names every file it may touch in `files:`. The CLI rejects a change to any other file, so a task that needs a new file lists it. Two tasks never share a file; a shared file means they are one task or one is `after:` the other
- it is independent of other pending tasks, or its `after:` names the task whose code it needs. An `after:` task branches from that task's tip, so its code is there
If you cannot write its test, it is not a task yet. Split further or do it yourself.
Each task is also a **task issue** on Linear: a sub-issue of the feature issue, labelled `fast-coding:task`, state Todo, title equal to the task's title, description equal to the task file body (Goal, Acceptance criteria, Test plan, Constraints), with `blockedBy` set to the `after:` task's issue. Create it with `save_issue` when you write the task file and put its identifier in the file's `linear:` field. The task file is the CLI's contract; the issue is where humans watch it. Keep both saying the same thing: edit one, edit the other.
One feature, one stack. The project's tasks become the layers of a single `gh stack` on the branch the user invoked you from, in `after:` order and then id order: foundational code at the bottom, code that depends on it above, one concern per layer. Number tasks in the order a reviewer should read them.

### 3. Write the tests first (red)
The acceptance test is yours. List it under `protected:`. The CLI rejects any attempt that changes a protected file.
It must fail on HEAD; `run` refuses a task whose test already passes.
Include holdout cases the task file does not list. The implementer is told they exist, so it has to implement the behavior rather than the examples. The deny-list task showed why: given only the listed labels, the fast model wrote one literal regex per label.
Commit tests and task files before dispatching; independent tasks branch from HEAD, stacked tasks from their lower layer.

### 3b. The user reviews the tasks before anything runs
Run `fast-coding tasks --repo <path> --project <name>` and show the user its output: every task's id, title, the files it owns, what it builds on, and its test, in stack order, with a warning for any file two tasks claim. Add one line per task saying what its holdout cases cover, in words.
Then stop and wait. The user may combine tasks, split them, reorder the stack, change file ownership, or drop one, here or in Linear. Apply the changes to the task files and their issues (a dropped task's issue is Canceled), re-run `fast-coding tasks`, and only dispatch after an explicit go. Skip this gate only when the user has said in this conversation to run without review.
Green is the implementer's job. Refactor is yours, through review and the verify fix loop, never the implementer refactoring its own green code.

### 4. Dispatch
`fast-coding run --repo <path> --project <name>` runs tasks in dependency order: independent tasks in parallel, one clone and one implementer session (pi by default) each; a task with `after:` starts as soon as that task passes, on top of its branch. Test failures, an over-limit diff, a new document, or a change outside `files:` are fed back into the same session up to `--attempts` (default 3).
The trunk is the branch the user is on when you run it (`--trunk` overrides). That checkout is never switched: clones are separate repos, and every `gh stack` operation runs in a CLI-owned detached worktree under `.fast-coding/<project>/worktrees/.stackroot`, with the stack state mirrored into the user's `.git` so `gh stack view` works from a task branch there.
When the run ends, all passed task branches of the project are rebased into one linear chain on the trunk tip and registered as one stack: `(my-feature) <- fast/<project>/001 <- fast/<project>/002 <- fast/<project>/003`, printed on a `stack ok` line. A later wave grows the same stack; before it starts, the existing layers are rebased onto the current trunk so new tests and task files are present on every base. A rebase conflict stops the chain at that layer with the exact commands to resolve it. `--no-stack` skips registration.
Use `--only 003,004` for a subset.
Inside herdr, run it in the background (`run_in_background`) and steer the fleet while it works; this is your job during a run, not typing code:
- `herdr agent list` is the wake signal: `working` is fine, `blocked` means pi is asking something, `done` means its turn ended. A status is a wake event, not truth: the truth is `fast-coding status`, `results/NNN.json`, and the diff.
- Read before you act: `herdr agent read <slug>-NNN --source recent-unwrapped --lines 80`.
- Steer with one specific instruction: `herdr agent prompt <slug>-NNN "<what to change, which file, which test>"`. The CLI's own re-prompts and yours go to the same agent, so keep yours short and concrete, and never contradict the task file; if the task is wrong, fix the task and re-run it.
- A stalled agent (working, no output change for a few minutes) gets one nudge, then `fast-coding` times it out into a fresh session by itself; do not kill panes.
- Log each steer as a comment on the task's Linear issue, one line, so the trail is in the ticket and not only in a terminal.
Linear follows the run from your side, since the CLI does not talk to it: right before `run`, move every task you are dispatching to In Progress. When `run` ends, read `results/NNN.json` and move each passed task to In Review with a comment naming its branch, attempts, and cost; a failed task stays In Progress with a comment that gives the failure in one paragraph (step 7 decides what happens to it). A user looking at the feature issue in Linear sees the stack's state without asking you.
Nothing is pushed. `fast-coding stack --submit` runs `gh stack submit --auto`, which pushes every branch and opens draft PRs: run it only when the user has explicitly asked for that push.

### 5. Review
Read `.fast-coding/<project>/results/NNN.json` and the layer's own diff: `git diff <base>..fast/<project>/NNN`, where `base` is in the result (`HEAD` or the lower task's branch). `gh stack view --json` from a task branch shows the chain.
Passing is not done. Reject scope creep, gamed tests, site-specific hacks, and poor quality; a rejected layer is re-split or fixed, then re-run. You never merge, locally or on GitHub. When the user says so, `fast-coding stack --submit` pushes the stack and opens one draft PR per layer; a human reviewer reads them bottom-up and decides on GitHub whether the stack merges. `gh stack merge` is the reviewer's tool, not yours.

Verify runs at the top of the stack, in the CLI's worktree, since layers are never merged locally; its fix commits land on the top layer and are reviewed like everything else.

### 6. Verify
`fast-coding verify --repo <path> --project <name>` is the local no-mistakes-style pipeline. Nothing is pushed; the only network calls are model APIs. Stages, in order, from `.fast-coding/<project>/verify.json`:

```json
{
  "checks": ["uv run ruff check .", "node --test 'tests/**/*.test.js'"],
  "docs": ["README.md", "DESIGN.md"],
  "perspectives": ["correctness", "security", "spec", "docs"],
  "jev_acceptance": true, "acceptance_threshold": 0.6, "acceptance_gate": false,
  "e2e_setup": "cd ... && python -m server.server", "e2e_setup_wait": 3, "e2e_env": {"API_KEY": "..."},
  "e2e": [{"name": "greenhouse fill", "url": "https://...", "goal": "Fill the application ... stop before Submit.",
           "assert": "python scripts/check_greenhouse.py", "prices": {"typesafe_per_call": 0.0}}],
  "review": true, "review_base": "main", "fix_model": "openrouter/openai/gpt-oss-120b",
  "review_context": "Design facts reviewers must respect, e.g. test credentials come from env by design and never reach the server."
}
```
1. **checks**: lint and unit tests, exact and cheap, run first.
2. **review**: parallel fast-model reviews (Mercury 2.5 via the jev-ultrafast `.env`), one per perspective, then a confirmation call per high or medium finding that must quote the code. Unconfirmed findings are dropped and shown as dropped. Only confirmed highs fail the stage.
3. **jev acceptance**: every bullet under `## Acceptance criteria` in every task file becomes one choice question to Jev (TypeSafe): MET, NOT_MET, UNCLEAR, with probabilities, one request per task against that task's own files, then a confirmation call per NOT_MET. Advisory by default, since the tests already cover every criterion; set `acceptance_gate: true` to make confirmed NOT_MET fail the stage.
4. **e2e**: each case drives a real browser with jev-ultrafast to the goal, then runs `assert`, an independent check you write that reads the real DOM or run log. A DONE from the model is never the proof.
5. **fix loop** (`--fix N`, default 2): confirmed findings go to the fast implementer in the repo itself, protected files are reverted if touched, the fix is committed, and every stage runs again. After N rounds it escalates to you with the findings. `--fix 0` reports only.

Every line prints its clock time and duration. The last line is the cost ledger: dollars and tokens per provider (openrouter for implementers, fixes, Mercury reviews, and jev's text helper; cerebras when a task pins it; typesafe for Jev decisions) and the total. `+?` after a provider means tokens were counted but no price is configured; set `prices` in verify.json to price it.

Fix what fails, re-run. Only then tell the user it is done, with the verify output.

### 7. Escalate and clean
A task that exhausts its attempts comes back with its full log. Read the log, then split: write two or three smaller, more specific tasks that each name the exact function, file, and behavior the log shows the implementer missed, give each its own red test, and dispatch those. Never re-dispatch the same task unchanged, and do not pick up the keyboard yourself just because an attempt failed. The exhausted task's issue is Canceled with a comment pointing at the issues that replace it; the new tasks get their own issues, blocked by whatever the old one was blocked by.
Implement by hand only when the blocker is not the task: the provider is down or out of credit, the task cannot be made smaller than one function, or the fix is a one-line change in a file you are already editing. When you do, record it: `fast-coding done --project <name> --only 024,025 --note "provider out of credit"`, so `fast-coding status` shows the truth, and say so in the report.
`fast-coding status --repo <path> [--watch]` shows every project with each task's state, attempts, time, cost, and stack layer; use it to report progress instead of describing it from memory.
`fast-coding clean --repo <path>` is the post-merge step, run after the reviewer has merged PRs on GitHub (or the user merged locally): it fetches, removes task clones and the CLI's stack worktree, deletes task branches that are proven merged (contained in the trunk or its remote, or a merged PR on GitHub, which also covers squash and rebase merges), and once every layer and the project branch are merged it removes the project's worktree and branch too. Unmerged work is kept and named. It never deletes unmerged layers unless `--delete-unmerged`. Run it whenever the user says PRs were merged, and at the end of a feature. Then move each merged task's issue to Done, and the feature issue to Done once every layer and the project branch are merged. A task you did by hand (`fast-coding done`) goes to Done with the same note.

## Task file format

`model:` is `pi:<provider/model>` for the pi harness (the default: lean, ~1K tokens of fixed context per turn), an OpenCode model id, or `claude`. Omit it for the CLI default, which pins gpt-oss-120b to Cerebras through the OpenRouter preset `gpt-oss-120b-cerebras`.

```markdown
---
id: 001
title: Submit deny list
files: extension/deny_list.js
protected: tests/deny_list.test.js
test: node --test tests/deny_list.test.js
model: pi:openrouter-fast/openai/gpt-oss-120b@preset/gpt-oss-120b-cerebras
after:            # id of the task this one builds on; it becomes the next layer of that task's stack
linear: ENG-124   # this task's Linear issue, a sub-issue of the feature issue, blocked by `after:`'s issue
---

## Goal
One paragraph. What to build, where, exact export names.

## Acceptance criteria
- One bullet per behavior. Each is checked by the test.

## Test plan
- How to run: the `test:` command above.
- Covered: which behaviors the test exercises, in words, not the literal cases.
- Holdout: state that the test has cases not listed here (do not list them).

## Constraints
- No new dependencies. Do not edit protected files.
```

## Rules
- Tests are the contract. The implementer never edits them.
- You steer, you do not type. Talk to the captain in outcomes, not mechanics; empty polls and no-change updates are not progress. Your final message stands alone: what finished, the stack, the cost, and the decision needed.
- Linear is the ticket tracker. No ticket, map, decision, or task list is ever written as a file in the repo beyond the task files the CLI needs; everything a human would read as a ticket is an issue under the feature issue, and its state is kept true at every step: Todo when written, In Progress when dispatched, In Review when its layer passed, Done when merged, Canceled when dropped or re-split.
- A `PAYMENT REQUIRED` stop is the user's, not yours. When `run` or `verify` exits 3 with that banner, stop everything and tell the user in one short message: which provider refused, the provider's own words, the top-up link the banner printed, and that `fast-coding resume --repo <path> --project <name>` continues from exactly where it stopped (passed tasks keep their branches, remaining tasks run, a halted verify reruns). Do not switch providers, re-dispatch, hand-implement, or retry around a billing stop. When the user says the account is fixed, run `resume`.
- A task branch changes at most 350 lines and never adds a document. These are CLI-enforced; plan tasks that fit, do not fight the guard.
- Never push or submit a stack without the user's explicit permission for that push. `run` registers stacks locally only.
- Fresh session per task. Never chain tasks in one session.
- Keep the target repo's fixed context small: short AGENTS.md, no unneeded MCP servers, no duplicate skills.
- Build a graft graph in the repo (`graft build .`, free, git-ignored). The CLI prepends a `graft ask` context pack with exact `file:line` and source to every implementer and fixer prompt, and tells the model to use `graft ask` and `graft callers` instead of exploring. Without graft the fast model reads whole files and every extra tool call resends the full context at Cerebras prices.
- Report honestly: attempts per task, what escalated, what you changed by hand, and the verify output.
- Always show timing and cost. Paste the CLI's `run start` and `run done` lines, the per-task table, the `verify` stage lines, and the final `cost` line into your report. The user wants to see when it started, how fast it finished, and what each implement cost, every time.
