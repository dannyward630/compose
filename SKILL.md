---
name: fast-coding
description: The full fast loop for a feature, from first question to verified stacked branches. Find the way with wayfinder until the decisions are settled, as tickets on the repo's Linear project, plan, split into tiny numbered tasks with tests, fan the tasks out to parallel implementers (pi running gpt-oss-120b, pinned to Cerebras by an OpenRouter preset; OpenCode and Claude available per task), verify locally with jev-ultrafast browser runs and a Mercury review, register each chain as a gh stack, keep every task's Linear issue in step, and inside herdr run the implementers as named agents in a per-project space that the orchestrator steers. Use when the user says "fast-coding", "fast loop", "fan out", or asks to build a feature or prototype fast. Works in any repo.
---

# fast-coding

You are the orchestrator. The implementer is pi running gpt-oss-120b on Cerebras (through the OpenRouter preset `gpt-oss-120b-cerebras`); OpenCode or Claude can take a task via `model:`. Verification is local; nothing is pushed.
This skill is the whole flow: the moment the user invokes it with a task, start at step 0 and carry it through to verified, stacked branches.

| Who | Does | Never does |
|---|---|---|
| You (orchestrator) | Find the way with the user (wayfinder), write the spec, the plan, and every task as Linear issues and move them through its states, write each acceptance test, dispatch, review diffs, run verify, re-split escalated tasks into smaller ones, submit the stack when told | Type implementation a task file covers (unless the blocker is infrastructure); merge anything: a human reviewer merges the PRs on GitHub |
| Implementer (fast model via pi or OpenCode; inside herdr a named pi agent in its own tab) | One task issue's brief, the named files, until its test passes, under 350 changed lines, adding no documents | Edit protected files, plan, touch other tasks, address the captain |
| `fast-coding verify` | Checks, jev-ultrafast browser e2e (through `bp` for extensions), Mercury diff review | Push, open PRs, run CI |

## Workflow

### 0. Know the repo's Linear project
Everything that would be a ticket lives on Linear, never as files in the repo: the feature, its decision tickets, its tasks.
Read `.fast-coding/linear.json` at the repo root: `{"project": "<Linear project URL>", "team": "Engineering"}`.
If it does not exist, ask the user for the link to the Linear project this repo's work belongs to, write the file with that URL and the team `Engineering` (unless the user names another), and commit it on the user's branch before anything else.
All Linear reads and writes are yours, through the Linear MCP tools (`save_issue`, `get_issue`, `list_issues`, `save_comment`). The CLI never talks to Linear.
Confirm the file points at a real project before any other Linear call: `get_project` with its URL must return a project on its team.
Scope every Linear read, search, and write to that project and team; when a project is in play, its feature comes from `.fast-coding/<slug>/linear.json`.
Stop and ask the user, never guess, when any of these happen:
- a Linear MCP call fails (auth, connection, timeout): say which call and its error, and wait; do not carry on as if Linear were empty
- the file's project or team is not found, or the user hands you an issue that lives in another project
- you cannot tell which epic, feature, story, or ticket the work belongs to, or a search returns more than one plausible match

### 0i. The levels: project, epic, feature, story, task
Linear has projects, issues, sub-issues, and labels; these five levels are how fast-coding uses them. Labels `Epic`, `Feature`, `Story`, `Task` live on the Engineering team (`Feature` exists; create the others once with `create_issue_label` if `list_issue_labels` does not show them).

| level | in Linear | in fast-coding | holds |
|---|---|---|---|
| **project** | the Linear project from `.fast-coding/linear.json` | the repo | epics and features; set once, never created by you |
| **epic** | top-level issue, label `Epic`; its description is the wayfinder map | a wayfinder map | decision tickets (`wayfinder:<type>`) and features, as sub-issues |
| **feature** | label `Feature`; sub-issue of its epic, or top-level when there is no epic | one fast-coding project: worktree, plan, one stack | stories; its description is the settled spec (or the map, when the feature is small enough to be its own map) |
| **story** | label `Story`; sub-issue of its feature | a contiguous group of layers in the feature's stack | tasks; its description is one user-visible slice with acceptance criteria |
| **task** | label `Task`; sub-issue of its story | one task issue (with its `fast-coding` block), one stack layer | goal, acceptance criteria, test plan |

A feature with one obvious slice still gets one story, so tasks always have the same parent shape. A bug or improvement is a feature with one story. Fewer levels is always right when the work is small: an epic exists only when wayfinder finds fog (more than one feature's worth of open decisions).

### 0j. What you were given decides where you start
Fast-coding accepts a Linear project link, an issue (epic, feature, story, or task, by URL or identifier such as `ENG-123`), a loose idea, or a loose idea plus the level the user names ("this is a story"). Resolve the level from the issue's label, else from its parent chain, else from the user's word; when none of these settle it, ask. Then:
- **project link, nothing else**: list its open epics and features and ask which one, or whether this is new work.
- **epic**: work the map (wayfinder "work through the map"): resolve the next decision ticket with the user, graduate features out of the fog. When a feature's way is clear, create its fast-coding project (step 0a) and continue with it as a feature. One ticket per session; the epic itself is never implemented.
- **feature**: if its map is not clear, wayfinder it (step 0b). If it has no stories, write them with the user: one issue per user-visible slice, acceptance criteria in the description, in the order they should ship. Then plan (step 1) and split (step 2) under each story.
- **story**: its feature is the parent; use or create that project. Write tasks for this story only; other stories' tasks are not touched.
- **task**: it belongs to a story that belongs to a feature; dispatch that task alone (`run --only NNN`) after the go.
- **loose idea**: wayfinder names the destination. No fog means it is a feature: create the feature issue (top-level) and continue. Fog means it is an epic: create the epic, chart it, stop.
- **user names the level**: create the issue at that level with the user's words as the title. A story needs a feature and a feature may need an epic: ask for the parent link, or create the parent too if the user says it is new. Then proceed as above.
Everything you create is a Linear issue in the project from step 0, labelled, parented, in state Todo or Backlog, before any file is written.

### 0s. Every level's state, kept true
A parent's state rolls up from its children; set it in the same step as the child change that moves it, never later:
| Level | In Progress | In Review | Done |
|---|---|---|---|
| task | dispatched (`run` starts it) | its layer passed | its layer merged |
| story | its first task is dispatched | every task is In Review or Done | every task is Done |
| feature | the session starts work on it: wayfinder, a recorded decision, the project, or the plan | every story is In Review or Done and `verify` passed | every story is Done and the project branch merged |
| epic | its first feature is In Progress | every feature is In Review or Done | every feature is Done |
A Backlog or Todo parent with an In Progress child is a bug: fix it the moment you see it.
Canceled children do not count. A re-opened child (a failed fix round, a new task) moves its parents back to In Progress.
Checkpoints, each followed by a reconcile of the whole tree (`list_issues` with the feature as parent, then its stories' children, compared against this table and `fast-coding status`): the end of planning (step 3b), right before and after every `run`, after every `verify`, after `clean`, and at session start (0r).

### 0h. Inside herdr, the fleet is visible and steerable
You are inside herdr when `HERDR_ENV=1` (herdr also sets `HERDR_SOCKET_PATH`, `HERDR_PANE_ID`, `HERDR_WORKSPACE_ID`). Then invoke the `herdr` skill; it carries the safety rules for panes and agents.
`herdr agent get $HERDR_PANE_ID` tells which harness you are (`claude` under Claude Code, which also sets `CLAUDECODE=1`; `pi`; ...). The flow is the same for any orchestrator; only the harness-specific tools differ.
The CLI builds the topology by itself, named so the captain reads it at a glance:
- **space** `<slug>`: the project's worktree, opened as a herdr worktree workspace grouped under the repo's space (`init` and `run` create it)
- tab **`status`**: `fast-coding status --watch` running live; tab **`shell`**: a shell in the project worktree
- one tab per task, **`NNN <title>`**, holding the task's implementer: an interactive pi agent named **`<slug>-NNN`**, with state labels (`attempt 2/3`, `passed`, `rejected_size`) and tokens (`model`, `cost`) on its pane
- tab **`verify HH:MM`** per verify run: one pane per stage (`checks`, `e2e <name>`, `review`, `jev`), reported `working`, then `idle` ok or `blocked` FAIL
Your own pane stays where the captain started you. Name it: `herdr agent rename $HERDR_PANE_ID <slug>-orchestrator` and `herdr pane rename $HERDR_PANE_ID "<slug> orchestrator"`.
`<slug>` is the project's (0a); until a project exists it is a kebab-case name for the map in the user's words.
Helpers you fan out yourself (research readers, writers, reviewers: anything `run` and `verify` do not start) are herdr agents too, one tab each, so the captain sees and steers them like the implementers.
The harness's in-process subagent tool (Claude's `Agent`) has no pane, so herdr cannot show it: inside herdr it is not used.
Per helper: `herdr tab create --workspace $HERDR_WORKSPACE_ID --label "<what it does>" --cwd <repo> --no-focus` (the project's space instead, found by its `<slug>` label in `herdr workspace list`, once `init` has created it), `herdr agent start <slug>-<role> --kind claude --pane <root_pane.pane_id> -- --permission-mode auto`, then `herdr agent prompt <slug>-<role> "<the task, the files to read, the one file to write>"`.
Prompt them all, then `herdr agent wait <name> --timeout 600000` each; read the file each wrote; `herdr tab close <tab_id>` once you have.
Names match `[a-z][a-z0-9_-]{0,31}` and are unique among live agents.
Outside herdr the same CLI commands run headless and nothing is shown, and helpers are the harness's own subagents; the skill is identical.

### 0a. Put the work in a project, in its own worktree
A project is one feature: its own git worktree and branch, one plan, one set of tasks, one gh stack. The moment the user invokes you with a task, decide which project it belongs to before anything else:
- Run `fast-coding projects --repo <path>`. If the request continues a feature that already has a project (same spec, same area of the code, or the user names it), use that project: new tasks get the next ids and become new layers of its stack.
- Otherwise create one: `fast-coding init --repo <path> --project <slug>`, where `<slug>` is a short kebab-case name for the feature in the user's words (`custom-dropdowns`, `workday-login`), not the repo's name and not a date. This creates branch `fast-coding/<slug>` from the branch the user is on and a worktree `../fast-coding-<slug>` next to the repo, with `.fast-coding/<slug>/` committed there. Tell the user the project name and the worktree path in your first reply.
- Every project is one **feature issue** on Linear (label `Feature`, title in the user's words, under its epic when there is one). Create it if the user did not hand you one, and record its identifier in `.fast-coding/<slug>/linear.json` as `{"feature": "ENG-123"}`. Its stories, their tasks, and any decision tickets are its sub-issues, so the whole feature reads as one tree in Linear.
- From then on everything you do in code for this project happens in that worktree: acceptance tests, every commit, every `fast-coding` command (`--repo <worktree>`, or any checkout with `--project <slug>`: the CLI resolves it). Everything written in words (grilling notes, the plan, tasks, decisions) goes to Linear, never to a file (Rules). The user's own checkout and branch are never touched. Several projects can run at the same time, each in its own worktree with its own stack.
- The stack's trunk is `fast-coding/<slug>`; PRs target it, and one final PR takes the project branch to the user's branch.
- Never mix two features in one project, and never spread one feature over two. If a request is really two features, make two projects and say so.
`fast-coding status --repo <path>` shows every project in every worktree with all its tasks; `--project <name>` shows one; `--watch` follows a run live. Use these when reporting progress.

### 0b. Find the way first when the decisions are not written down
A settled spec is a feature issue whose description says the way is clear: no open decision sub-issues, and `## Not yet specified` empty. A repo file (`DESIGN.md`, a PRD) counts too when the user points at it.
If none exists for this piece of work, do not plan yet: invoke the `wayfinder` skill with the epic (or the feature, when it is its own map) as the map (it is user-invocable only; when the Skill tool does not list it, read `~/.claude/skills/wayfinder/SKILL.md` and follow it). Wayfinder's tracker is Linear here, and this is how its operations map:
- the **map** is the epic issue, or the feature issue when there is no epic; its description is the map body (Destination, Notes, Decisions so far, Not yet specified, Out of scope)
- a **ticket** is a sub-issue of the map, labelled `wayfinder:<type>` (`research`, `prototype`, `grilling`, `task`), body `## Question`
- **blocking** is Linear's native "blocked by" relation (`save_issue` with `blockedBy`), so the frontier shows in Linear's own UI
- the **frontier** is `list_issues` on the feature's sub-issues: open, no unresolved blockers, unassigned
- **claim** by assigning the ticket to the user; **resolve** by posting the answer as a comment, setting the state to Done, and appending the one-line gist to the map's Decisions so far
- a **file** wayfinder or a skill it loads would write (`GRILLING.md`, research notes, a findings summary, a decision log) is a **Linear document** in the repo's project instead (`save_document` with the project from `.fast-coding/linear.json`), titled after its map and purpose (`<map>: grilling`), linked from the map's Notes; add to it with `save_document` rather than writing anything to disk. A file the user hands you stays where it is and is linked as a project resource.
- a **prototype** ticket about how a screen or a flow should look is drawn in Frame0 through the `frame0` MCP server (low-fi wireframes: `create_frame` with the device kind, text, rectangles, icons from `search_icons`, `create_connector` between frames for a flow, one page per ticket named after the ticket). Frame0 must be running with its API server on (Settings > API Server > Run on start); if the tools fail to connect, say so and wait rather than describing the design in words. Export the page with `export_page_as_image`, attach the image to the ticket (`prepare_attachment_upload` then `create_attachment_from_upload`), and walk the user through it in the grilling; the resolution comment names the Frame0 page. Logic or stub prototypes still go in code on a throwaway branch.
Wayfinder resolves one ticket per session, with the user, one question at a time and your recommendation on each; the grilling it runs is HITL, never answer for the user. When it reports no fog (the way is already clear in one sitting), its grilling is the spec: write the decisions into the map's Decisions so far and continue to step 1.
Before any question reaches the user (charting, grilling, story writing), look for its answer in Linear first:
1. the map's Decisions so far and Notes, and the description and comments of the feature, its epic, and the story at hand
2. the resolution comments of Done tickets under the map (`list_issues` with the map as parent, then `list_comments`)
3. a `list_issues` search, scoped to the project in `.fast-coding/linear.json`, for the question's key terms, since another epic or feature may have decided it
A decision found there is settled: state it with its ticket's name and link, build on it, and do not ask again.
Ask only when Linear is silent, or when two recorded decisions conflict; then quote both and ask which one stands.
"We need to make decisions" from the user is fog, whatever deliverables the same request lists: a PRD, epics, user flows or a tech doc asked for up front are what the map and its resolved tickets become after the grilling, not drafts written around decisions you picked.
When the user cannot answer (a harness note says so, or no reply comes): chart the map, post the first question on its ticket, say so, and stop; the session ends at the question and 0r resumes it.
An autonomous mode is never a mandate to decide for the user.
Helpers in this phase read research, draft ticket Questions, or draw a prototype whose decision is settled; none writes a document that carries an open decision.
Research the user points at (notes, a folder of findings) feeds the map's Notes; it is not the spec.
If a spec exists, read it and do not reopen its decisions. Open a decision ticket only for what it leaves open that the plan needs.

### 0r. Pick up where the last session stopped
Everything is on disk, so a restart is a non-event. At the start of a session on an existing project, before anything else: `fast-coding status --repo <wt> --project <slug>` and `fast-coding watch ... --now`, which prints the current state as event lines, then reconcile the Linear tree against them (0s). Then:
- `run INTERRUPTED` or a task `interrupted`: the previous run died with you. `fast-coding resume` re-runs what did not pass, in fresh agents, keeping passed layers. Reconcile Linear from the `--now` lines first, so the issues say what the disk says, parents included (0s).
- `HALTED ... payment required`: the user's stop; say so and wait for the word to `resume`.
- `run live`: another orchestrator session owns it. Supervise with `watch`, do not start a second run.
- Herdr agents of a dead run are closed by the next run of their task; do not close them by hand.

### 1. Plan from the spec
Input is the feature issue's map and resolved tickets, plus `DESIGN.md`, a PRD, whatever the repo already had.
Read all of it. Then invoke `superpowers:writing-plans` for how to write the plan, but not where: the plan is a `## Plan` section in the feature issue's description (`save_issue`), never a file. Writing-plans' own save path does not apply.
`<project>` is a short slug for this piece of work, one repo can hold several; `.fast-coding/<project>/linear.json` holds `{"feature": "<feature issue id>"}` and is how the CLI finds the plan and the tasks.
The plan follows writing-plans conventions: numbered steps, each with files touched, the test that proves it, and explicit dependencies.
Decisions already made in the spec are not reopened.

### 2. Split into tasks
Turn each plan step into a task issue on Linear (format below). There is no task file: the CLI reads the issue.
A task is right-sized when all of these hold:
- one to three files, one test command, under ten acceptance criteria
- no open design choices; every "how" is stated or obvious from the named files
- the whole task plus the files it touches fits comfortably in 40K tokens
- its branch will change at most 350 lines (added plus deleted). The CLI rejects a bigger branch, so size the task for it
- it adds no documents. Implementers never create .md, .txt, .rst, or docs/ files; the CLI rejects a branch that does. Docs are the orchestrator's, edited by hand after the reviewer has merged the PRs, only when the user asked for them
- it names every file it may touch in `files:`. The CLI rejects a change to any other file, so a task that needs a new file lists it. Two tasks never share a file; a shared file means they are one task or one is `after:` the other
- it is independent of other pending tasks, or its `after:` names the task whose code it needs. An `after:` task branches from that task's tip, so its code is there
If you cannot write its test, it is not a task yet. Split further or do it yourself.
A task is a **task issue** on Linear: a sub-issue of its story, labelled `Task`, state Todo, its title the task's title, its description the brief (Goal, Acceptance criteria, Test plan, Constraints) ending with the `fast-coding` block, and `blockedBy` set to the issue of each task it builds on. That one issue is the CLI's contract, the implementer's brief, and where humans watch and edit the work.
The CLI never calls Linear; you hand it what Linear says. **Sync** right before every `tasks`, `run`, `resume`, and `verify`, so an edit anyone made in Linear is what runs:
1. `get_issue` on the feature (from `.fast-coding/<project>/linear.json`) for its id, title, and description.
2. `list_issues` with the feature as `parentId`, then with each story as `parentId`, for the ids only: `list_issues` truncates descriptions, and the block is at the end.
3. `get_issue` on every one of those issues with fields `id`, `title`, `description`, `status`, `relations`.
4. Pipe it in: `fast-coding sync --repo <wt> --project <slug> <<'EOF'` then `{"feature": {"id", "title", "description"}, "issues": [{"id", "title", "description", "status", "blockedBy": <relations.blockedBy as returned>}]}` then `EOF`. Pass every description whole, exactly as `get_issue` returned it; the CLI hands it to the implementer as the brief.
The commands refuse to start without a sync, and `sync` refuses a feature other than `linear.json`'s.
One feature, one stack. The project's tasks become the layers of a single `gh stack` on the branch the user invoked you from, in `after:` order and then id order: foundational code at the bottom, code that depends on it above, one concern per layer. Number tasks in the order a reviewer should read them.

### 3. Write the tests first (red)
The acceptance test is yours. List it under `protected:`. The CLI rejects any attempt that changes a protected file.
It must fail on HEAD; `run` refuses a task whose test already passes.
Include holdout cases the task issue does not list. The implementer is told they exist, so it has to implement the behavior rather than the examples. The deny-list task showed why: given only the listed labels, the fast model wrote one literal regex per label.
Commit the tests before dispatching; independent tasks branch from HEAD, stacked tasks from their lower layer.

### 3b. The user reviews the tasks before anything runs
Run `fast-coding tasks --repo <path> --project <name>` and show the user its output: every task's id, title, the files it owns, what it builds on, and its test, in stack order, with a warning for any file two tasks claim. Add one line per task saying what its holdout cases cover, in words.
Then stop and wait. The user may combine tasks, split them, reorder the stack, change file ownership, or drop one, here or in Linear. Apply the changes to the task issues (a dropped task's issue is Canceled and loses its `fast-coding` block), re-run `fast-coding tasks`, and only dispatch after an explicit go. Skip this gate only when the user has said in this conversation to run without review.
Green is the implementer's job. Refactor is yours, through review and the verify fix loop, never the implementer refactoring its own green code.

### 4. Dispatch
`fast-coding run --repo <path> --project <name>` runs tasks in dependency order: independent tasks in parallel, one clone and one implementer session (pi by default) each; a task with `after:` starts as soon as that task passes, on top of its branch. Test failures, an over-limit diff, a new document, or a change outside `files:` are fed back into the same session up to `--attempts` (default 3).
The trunk is the branch the user is on when you run it (`--trunk` overrides). That checkout is never switched: clones are separate repos, and every `gh stack` operation runs in a CLI-owned detached worktree under `.fast-coding/<project>/worktrees/.stackroot`, with the stack state mirrored into the user's `.git` so `gh stack view` works from a task branch there.
When the run ends, all passed task branches of the project are rebased into one linear chain on the trunk tip and registered as one stack: `(my-feature) <- fast/<project>/001 <- fast/<project>/002 <- fast/<project>/003`, printed on a `stack ok` line. A later wave grows the same stack; before it starts, the existing layers are rebased onto the current trunk so new tests and task files are present on every base. A rebase conflict stops the chain at that layer with the exact commands to resolve it. `--no-stack` skips registration.
Use `--only 003,004` for a subset.
Run it in the background (`run_in_background`); your job during a run is supervising the crew and keeping Linear true, not typing code, and not polling. Supervision costs zero tokens while nothing happens:
- Start `fast-coding watch --repo <wt> --project <slug>` in the background too. It sleeps until something you must act on happens, prints one `event ...` line, and exits; its exit wakes you. Act on the line, then start `watch` again. Never loop on `status` or `herdr agent list` yourself.
- The event lines, and what you do with each: `task=NNN state=running` moves its Linear issue (the `linear=` field is on the line) to In Progress, with its story and feature (0s); `state=passed` moves it to In Review with a comment naming `branch=`, attempts, and cost, and rolls its story up; `state=failed` or `state=rejected_*` leaves it In Progress with the failure in a comment and goes to step 7; `agent=<name> status=blocked` means read it and steer; `run=ended` means review the stack; `verify=PASS|FAIL` means report, and PASS with every story In Review moves the feature to In Review. A status line is a wake event, not current state: before a decision, confirm with `fast-coding status` and the result file.
- Read before you act: `herdr agent read <slug>-NNN --source recent-unwrapped --lines 80`.
- Steer with one specific instruction: `herdr agent prompt <slug>-NNN "<what to change, which file, which test>"`. The CLI's own re-prompts and yours go to the same agent, so keep yours short and concrete, and never contradict the task issue; if the task is wrong, fix the task and re-run it.
- A stalled agent (working, no output change for a few minutes) gets one nudge, then `fast-coding` times it out into a fresh session by itself; do not kill panes.
- Log each steer as a comment on the task's Linear issue, one line, so the trail is in the ticket and not only in a terminal.
Linear follows the run from your side, since the CLI does not talk to it: right before `run`, move every task you are dispatching to In Progress, and with it its story and the feature (0s). When `run` ends, read `results/NNN.json` and move each passed task to In Review with a comment naming its branch, attempts, and cost; a failed task stays In Progress with a comment that gives the failure in one paragraph (step 7 decides what happens to it). Then roll the stories and the feature up (0s). A user looking at the feature issue in Linear sees the stack's state without asking you.
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
3. **jev acceptance**: every bullet under `## Acceptance criteria` in every task issue becomes one choice question to Jev (TypeSafe): MET, NOT_MET, UNCLEAR, with probabilities, one request per task against that task's own files, then a confirmation call per NOT_MET. Advisory by default, since the tests already cover every criterion; set `acceptance_gate: true` to make confirmed NOT_MET fail the stage.
4. **e2e**: each case drives a real browser with jev-ultrafast to the goal, then runs `assert`, an independent check you write that reads the real DOM or run log. A DONE from the model is never the proof.
5. **fix loop** (`--fix N`, default 2): confirmed findings go to the fast implementer in the repo itself, protected files are reverted if touched, the fix is committed, and every stage runs again. After N rounds it escalates to you with the findings. `--fix 0` reports only.

Every line prints its clock time and duration. The last line is the cost ledger: dollars and tokens per provider (openrouter for implementers, fixes, Mercury reviews, and jev's text helper; cerebras when a task pins it; typesafe for Jev decisions) and the total. `+?` after a provider means tokens were counted but no price is configured; set `prices` in verify.json to price it.

Fix what fails, re-run. Only then tell the user it is done, with the verify output.

### 6a. Browser work goes through `bp` (browser-probe)
Any browser exploration or testing in this loop, by you or by an implementer, uses `bp` from `~/code/browser-probe` (skill `browser-probe`, rules in its `AGENTS.md`). Not the user's real Chrome, not ad hoc Playwright scripts.
- **Exploring** (what does the panel show, did the fill work, record a flow): `bp launch --ext <dir>`, `bp list`, `bp hosts`, `bp snap`, `bp clicktext`, `bp form`, `bp record`. Screenshots land in `shots/` with an `index.md` line each.
- **Driving toward a goal with the model**: `bp goal <url> "<goal> … stop before Submit"`. Same jev policy as verify's e2e, same Chromium.
- **Verify e2e for an extension**: launch the extension's Chromium in `e2e_setup` and point jev at it with `e2e_env`, so `jev_e2e` attaches to that browser instead of the default Chrome:
  ```json
  "e2e_setup": "BP_PORT=9333 bp launch about:blank --ext /path/to/extension/dist --profile /tmp/bp-profile-verify",
  "e2e_setup_wait": 4,
  "e2e_env": {"BU_CDP_URL": "http://127.0.0.1:9333", "BU_NAME": "bp9333"},
  "e2e": [{"name": "greenhouse fill", "url": "https://job-boards.greenhouse.io/...", "goal": "Open the Jobscan panel, click Autofill, wait for the checklist, stop before Submit.",
           "assert": "bp form greenhouse.io | grep -q 'filled [1-9]'"}]
  ```
  A scripted check with no model is a `driver` case: `{"name": "panel renders", "driver": "bp hosts greenhouse.io --min 50 | grep -q Autofill", "env": {"BP_PORT": "9333"}}`.
- One port per extension build. Never let a goal or driver click a real employer Submit; assert on `bp form` output and a screenshot.

### 7. Escalate and clean
A task that exhausts its attempts comes back with its full log. Read the log, then split: write two or three smaller, more specific tasks that each name the exact function, file, and behavior the log shows the implementer missed, give each its own red test, and dispatch those. Never re-dispatch the same task unchanged, and do not pick up the keyboard yourself just because an attempt failed. The exhausted task's issue is Canceled with a comment pointing at the issues that replace it; the new tasks get their own issues, blocked by whatever the old one was blocked by.
Implement by hand only when the blocker is not the task: the provider is down or out of credit, the task cannot be made smaller than one function, or the fix is a one-line change in a file you are already editing. When you do, record it: `fast-coding done --project <name> --only 024,025 --note "provider out of credit"`, so `fast-coding status` shows the truth, and say so in the report.
`fast-coding status --repo <path> [--watch]` shows every project with each task's state, attempts, time, cost, and stack layer; use it to report progress instead of describing it from memory. `fast-coding watch` is how you wait for it to change.
`fast-coding clean --repo <path>` is the post-merge step, run after the reviewer has merged PRs on GitHub (or the user merged locally): it fetches, removes task clones and the CLI's stack worktree, deletes task branches that are proven merged (contained in the trunk or its remote, or a merged PR on GitHub, which also covers squash and rebase merges), and once every layer and the project branch are merged it removes the project's worktree and branch too. Unmerged work is kept and named. It never deletes unmerged layers unless `--delete-unmerged`. Run it whenever the user says PRs were merged, and at the end of a feature. Then move each merged task's issue to Done and roll its story, feature, and epic up (0s): the feature is Done once every layer and the project branch are merged. A task you did by hand (`fast-coding done`) goes to Done with the same note.

## Task issue format

`model:` is `pi:<provider/model>` for the pi harness (the default: lean, ~1K tokens of fixed context per turn), an OpenCode model id, or `claude`. Omit it for the CLI default, which pins gpt-oss-120b to Cerebras through the OpenRouter preset `gpt-oss-120b-cerebras`.
When a gpt-oss attempt errors, times out, is rate-limited, or misses, the task moves to `pi:openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5.3-flash-fast` (Together, then CoreWeave) in a fresh session that carries the failure; fix rounds after the first use it too. `bench` never falls back.
Models, the fallback, and the OpenRouter key come from the active workspace in `~/.fast-coding/config.json` (`fast-coding workspace [name | add | key | remove <name>]`, or `/fast-coding:workspace`; `default` always exists); `run` and `verify` print `workspace <name>` first, so check it before spending.

The issue's title is the task's title. Its description is the brief, then the block the CLI reads, last:

````markdown
## Goal
One paragraph. What to build, where, exact export names.

## Acceptance criteria
- One bullet per behavior. Each is checked by the test.

## Test plan
- How to run: the `test:` command below.
- Covered: which behaviors the test exercises, in words, not the literal cases.
- Holdout: state that the test has cases not listed here (do not list them).

## Constraints
- No new dependencies. Do not edit protected files.

```fast-coding
id: 001
files: extension/deny_list.js
protected: tests/deny_list.test.js
test: node --test tests/deny_list.test.js
model: pi:openrouter-fast/openai/gpt-oss-120b@preset/gpt-oss-120b-cerebras
```
````

- `id` is the stack order a reviewer reads in; ids are unique within the feature.
- `after` is not in the block: it is the issue's "blocked by" links to other tasks of the feature. Each one becomes the layer this task stacks on.
- An issue under the feature without the block is not a task (stories, decision tickets): the CLI ignores it.

## Rules
- Nothing is implemented until the user says so. Intake, wayfinder, stories, the plan, task issues, and tests are all preparation; `fast-coding run` is the first implementing action and it waits for an explicit go on the task list (step 3b), every time, for every wave, even when the user handed you a single task. "Build it" at intake is not that go; the go comes after the user has seen the tasks.
- Tests are the contract. The implementer never edits them.
- Every document you write for a human is shaped by the `i-have-adhd` skill: Linear descriptions and comments (maps, specs, plans, stories, tasks, grilling notes, steers), and the docs you edit after merge. That skill is user-invoked only, so the Skill tool cannot load it; before writing the first document of a session, read `~/.claude/plugins/marketplaces/i-have-adhd/skills/i-have-adhd/SKILL.md` and apply its rules to everything you write from then on. Writing-plans and the task issue format fix the sections; i-have-adhd fixes the shape inside them: first line is the next action, multi-step work is numbered, lists stop at five, no preamble, no recap.
- You steer, you do not type. Talk to the captain in outcomes, not mechanics; empty polls and no-change updates are not progress. Your final message stands alone: what finished, the stack, the cost, and the decision needed.
- Linear is the source of truth and the ticket tracker. What it records as decided is decided: read it before asking the user anything (0b), and write every new answer back to it, so the next session finds it. Nothing written in words is ever a file in the repo: no plan, task, ticket, map, decision, grilling note, or task list, not under `.fast-coding/` and not anywhere else (the only files there are the CLI's JSON: `linear.json`, `verify.json`, and git-ignored `results/`); everything a human would read as a ticket is an issue under the feature issue, and its state is kept true at every step, at every level (0s): a task is Todo when written, In Progress when dispatched, In Review when its layer passed, Done when merged, Canceled when dropped or re-split, and its story, feature, and epic roll up from it in the same step.
- A `PAYMENT REQUIRED` stop is the user's, not yours. When `run` or `verify` exits 3 with that banner, stop everything and tell the user in one short message: which provider refused, the provider's own words, the top-up link the banner printed, and that `fast-coding resume --repo <path> --project <name>` continues from exactly where it stopped (passed tasks keep their branches, remaining tasks run, a halted verify reruns). Do not switch providers, re-dispatch, hand-implement, or retry around a billing stop. When the user says the account is fixed, run `resume`.
- A task branch changes at most 350 lines and never adds a document. These are CLI-enforced; plan tasks that fit, do not fight the guard.
- Never push or submit a stack without the user's explicit permission for that push. `run` registers stacks locally only.
- Fresh session per task. Never chain tasks in one session.
- Keep the target repo's fixed context small: short AGENTS.md, no unneeded MCP servers, no duplicate skills.
- Build a graft graph in the repo (`graft build .`, free, git-ignored). The CLI prepends a `graft ask` context pack with exact `file:line` and source to every implementer and fixer prompt, and tells the model to use `graft ask` and `graft callers` instead of exploring. Without graft the fast model reads whole files and every extra tool call resends the full context at Cerebras prices.
- Report honestly: attempts per task, what escalated, what you changed by hand, and the verify output.
- Always show timing and cost. Paste the CLI's `run start` and `run done` lines, the per-task table, the `verify` stage lines, and the final `cost` line into your report. The user wants to see when it started, how fast it finished, and what each implement cost, every time.
