---
name: fast-coding
description: The full fast loop for a feature, from first question to verified stacked branches. Find the way with wayfinder until the decisions are settled, as tickets on the repo's Linear project, plan, split into tiny numbered tasks with tests, fan the tasks out to parallel implementers (pi running GLM 5.3 Flash through an OpenRouter preset; OpenCode and Claude available per task), verify locally with jev-ultrafast browser runs and a Mercury review, register each chain as a gh stack, keep every task's Linear issue in step, and inside herdr run the implementers as named agents in a per-project space that the orchestrator steers. Use when the user says "fast-coding", "fast loop", "fan out", or asks to build a feature or prototype fast. Works in any repo.
---

# fast-coding

You are the orchestrator, or, inside herdr, the first mate who hands the project to one (0h). The implementer is pi running GLM 5.3 Flash (through the OpenRouter preset `glm-5-3-flash-fast`); OpenCode or Claude can take a task via `model:`. Verification is local; nothing is pushed.
This skill is the whole flow: the moment the user invokes it with a task, start at step 0 and carry it through to verified, stacked branches.

| Who | Does | Never does |
|---|---|---|
| You (orchestrator; the first mate likewise) | Find the way with the user (wayfinder), write the spec, the plan, and every task as Linear issues and move them through its states, brief crew for the acceptance tests and any other code, dispatch, review diffs, run verify, re-split escalated tasks into smaller ones, submit the stack when told | Write or edit any code, test, config, or repo doc, not one line (crew do, Rules); merge anything: a human reviewer merges the PRs on GitHub |
| Crew (Claude sessions in the project's space, 0h) | Acceptance tests and the stubs and groundwork they need, escalated work, conflict fixes, docs after merge, wayfinder questions, research; a toolsmith (briefed by the first mate) fixes fast-coding itself on a branch | Plan, re-scope their brief, address the captain except through `report` and their own pane |
| Implementer (fast model via pi or OpenCode; inside herdr a named pi agent in its own pane of the `implementers` tab) | One task issue's brief, the named files, until its test passes, under 350 changed lines, adding no documents | Edit protected files, plan, touch other tasks, address the captain |
| `fast-coding verify` | Checks, jev-ultrafast browser e2e (through `bp` for extensions), Mercury diff review | Push, open PRs, run CI |

## Workflow

### 0L. Pick the path first: lite or full
The full path below (Linear tree, wayfinder, crews, gates, a gh stack) pays off on big, risky work and costs more than it saves on small work.
Before step 0, classify the work.
The captain's own words decide it first: "homework", "take-home", "prototype", "quick", "spike", or "lite" picks lite directly, with no size estimate.
Otherwise it is **lite** only when all four hold:
1. **Small**: one feature, and the plan you can already see comes to about 12 tiny tasks or fewer. Count tiny one-file tasks, not features or screens: a homework-sized spec with server and client sides is often 9 or 10 tiny tasks and is still lite.
2. **Reversible**: a wrong call costs a re-run, not an incident. No production data or real-data migrations, auth, payments, security boundaries, or public APIs others depend on. Homework, prototypes, demos, internal tools, and local-only changes qualify.
3. **Clear destination**: the request (a README, a ticket, the captain's words) says what done is, and every open decision has a recommended option you would defend.
4. **One area**: one repo, one feature, no epic, no coordination with other teams or projects.
Any doubt on any criterion means full.
The first report names the path and the reason in one line, with a one-word override, e.g. "Lite path: homework-sized (about 5 tasks), reversible, the README settles done. Say `full` to switch." The captain's `full` or `lite` wins either way.

**What lite skips** (deltas on the full path; every step not named here runs as written):
- **0, 0s (Linear)**: no Linear tree and no state roll-ups. `fast-coding init --lite` writes `linear.json` as `{"feature": "<slug>", "lite": true}`. An issue the captain handed you gets one comment with the plan and one with the outcome; nothing is created under it.
- **0b (wayfinder)**: skipped, no question agents. You take the recommended option on every open decision yourself.
- **0g and 3 (crews)**: the same split as the full path: one `groundwork` crew (toolchain, stubs, e2e cases, the contract), then `fast-coding testcrews` writes the tests in parallel. No throwaway reference implementation: the red check and your read of every test are the proof.
- **1 and 2 (plan, tasks)**: same content, no issues. Pipe it to `fast-coding sync` yourself in the usual JSON: feature `id` is the slug and its `description` is the plan; each issue's `id` is its task id (`001`), its `description` the brief ending with the `fast-coding` block, and `blockedBy` the task ids it truly needs.
- **3b (gate)**: none. Dispatch as soon as `fast-coding tasks` shows no WARNING.
- **4 (run)**: tasks never get rebased into one chain. A task with one `after:` builds on that task's branch; a task with several builds on a merge of them, and a merge conflict there stops that task with the branches named (split the files differently). `run` registers no gh stack, and there is no Linear to move.
- **6 (verify)**: `verify` first lands every task on the project branch, dependencies first, by cherry-picking each task's own commits (linear history with the tasks' plain messages, no merge commits), and verifies the project branch itself. Its fix rounds act only on failing checks and failing e2e; review and acceptance findings are printed and recorded for you to weigh, never auto-fixed and never a FAIL.
- **Delivery**: the verified project branch, `fast-coding/<slug>`, is the result: one branch for one PR when the captain asks.

**What lite keeps**: its own worktree (0a), tiny tasks with tests written first, parallel implementers, your review of every layer (5), the full verify with e2e (6), the captain's quality bar (1), and nothing pushed.

**Decisions on the lite path are taken, then reported once.**
Pick the recommended option for every open decision, including what 0g finds.
Send them in one batched report as the run starts: a numbered list, each with the decision, the option taken, one line of why, and the main alternative.
The captain overrides any of them by number; an override after code exists becomes a new task or a re-run of the affected ones.

**Escalate to full mid-way** the moment any of these happens:
- `fast-coding tasks` prints `WARNING LITE PROJECT HAS N TASKS` (more than 12)
- a decision turns out irreversible or has no defensible default
- a second wave looms, or the captain says `full`
To escalate: create the Linear feature, stories, and task issues from what exists (the plan and every brief with its block), rewrite `linear.json` as `{"feature": "<issue id>"}`, re-sync, ask the decisions that need the captain as one request, and continue at the step you were on. Passed layers keep.

### 0. Know the repo's Linear project
Lite path (0L): skip this step.
Everything that would be a ticket lives on Linear, never as files in the repo: the feature, its decision tickets, its tasks.
Read `.fast-coding/linear.json` at the repo root: `{"project": "<Linear project URL>", "team": "Engineering"}`.
If it does not exist, ask the user for the link to the Linear project this repo's work belongs to, write the file with that URL and the team `Engineering` (unless the user names another) in the user's checkout, and never commit it.
`fast-coding init` ignores `.fast-coding/` and `graft/` in every checkout before anything else, and copies this file into the project worktree.
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
| **epic** | top-level issue, label `Epic`; its description is the wayfinder map | a wayfinder map while in fog; once its features are known, a set of projects (one per feature) the first mate runs together | decision tickets (`wayfinder:<type>`) and features, as sub-issues |
| **feature** | label `Feature`; sub-issue of its epic, or top-level when there is no epic | one fast-coding project: worktree, plan, one stack | stories; its description is the settled spec (or the map, when the feature is small enough to be its own map) |
| **story** | label `Story`; sub-issue of its feature | a contiguous group of layers in the feature's stack | tasks; its description is one user-visible slice with acceptance criteria |
| **task** | label `Task`; sub-issue of its story | one task issue (with its `fast-coding` block), one stack layer | goal, acceptance criteria, test plan |

A feature with one obvious slice still gets one story, so tasks always have the same parent shape. A bug or improvement is a feature with one story. Fewer levels is always right when the work is small: an epic exists only when wayfinder finds fog (more than one feature's worth of open decisions).

### 0j. What you were given decides where you start
Fast-coding accepts a Linear project link, an issue (epic, feature, story, or task, by URL or identifier such as `ENG-123`), a loose idea, or a loose idea plus the level the user names ("this is a story"). Resolve the level from the issue's label, else from its parent chain, else from the user's word; when none of these settle it, ask. Then:
- **project link, nothing else**: list its open epics and features and ask which one, or whether this is new work.
- **epic**: the epic is taken through to done as a unit, but it is never one project: each feature is its own project (0a), with its own worktree, orchestrator, stack, and final PR. Which path depends on whether its features are known:
  - **Fog** (you cannot yet name the features the epic needs): work the map with wayfinder ("work through the map"), one decision ticket per session, graduating features out of the fog. Once every feature can be named, switch to the settled path.
  - **Settled** (the features exist as sub-issues, or can be named from the map): create one project per feature and start an orchestrator for each (0h), all at once. Each orchestrator runs its groundwork (0g) and collects its feature's open decisions; the first mate waits for all of them and sends the captain every decision across the epic as one request (Rules: ask once), then forwards each answer to its orchestrator. A feature starts from trunk unless it truly needs another feature's code (it calls, imports, or edits what that feature builds), the same rule as a task's `after:`: then `fast-coding init --project <slug> --after <other-slug>` starts its branch from that feature's project branch, so its stack sits on top. Independent features run in parallel.
- **feature**: if its map is not clear, wayfinder it (step 0b). If it has no stories, write them with the user: one issue per user-visible slice, acceptance criteria in the description, in the order they should ship. Then plan (step 1) and split (step 2) under each story.
- **story**: its feature is the parent; use or create that project. Write tasks for this story only; other stories' tasks are not touched.
- **task**: it belongs to a story that belongs to a feature; dispatch that task alone (`run --only NNN`) through the 3b gate.
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
- tab **`implementers`**: one pane per running task, labeled **`NNN <title>`**, holding the task's interactive pi agent named **`<slug>-NNN`**, with state labels (`attempt 2/3`, `rejected_size`) and tokens (`model`, `cost`) on its pane. A passed task's pane closes; a missed one stays to read and steer
- tab **`verify`**, rebuilt by each verify run: one pane per stage (`checks`, `e2e <name>`, `review`, `jev`), reported `working`, then `idle` ok or `blocked` FAIL
`<slug>` is the project's (0a); until a project exists it is a kebab-case name for the map in the user's words.
**Three roles, like firstmate** (github.com/kunchenguid/firstmate). The captain is the user.
- **First mate**: the session the captain started. It stays in the pane it was started in and is the captain's one point of contact. It takes the intake (0L, 0, 0j), names the path and its reason in its first report to the captain, and creates the project (0a), then hands the project to an orchestrator and only relays from then on. It never moves, and one first mate can run several projects.
- **An epic as a unit** (0j, settled path): the first mate creates every feature's project and orchestrator, runs one `watch` per project, and relays as above. It reports at epic level: features verified X of N, total cost and wall time, and which feature waits on what. It keeps the epic's Linear state in step with its features (0s). It still writes no code and does no orchestrator's work.
- **Orchestrator**: a Claude session in the project's space, started by the first mate right after `init`: `fast-coding crew start --repo <wt> --project <slug> --role orchestrator --title orchestrator --brief -` with a brief on stdin naming the project, the worktree, the feature issue, what the captain asked, the path (0L), and "invoke the fast-coding skill and continue from 0b" (lite: "lite path, continue from 0g"). It runs everything from there on. It reports up with `fast-coding report`, and the captain can also type into its pane directly.
- **Crew**: sessions the orchestrator starts in the same space: wayfinder question agents (0b), helpers (researchers, writers, reviewers), and the implementers `run` starts.
The CLI directs the captain's attention, not you: every `needs-user` or `blocked` report pops a herdr notification naming the tab and badges that pane `needs you`, and never steals focus. When the captain says "take me there", run `fast-coding crew focus --project <slug> --role <role>`.
The first mate's loop: `fast-coding watch --repo <wt> --project <slug> --from orchestrator` in the background; on each `event crew=<slug>-orchestrator` line, tell the captain the outcome in one or two sentences (needs-user: the question and its recommendation, and that the captain may answer here or in the orchestrator's tab); forward the captain's answer with `herdr agent prompt <slug>-orchestrator "<answer>"`; start `watch` again. Read the orchestrator with `herdr agent read <slug>-orchestrator --source recent-unwrapped --lines 80` before relaying anything unclear. Do not do the orchestrator's work yourself.
**When fast-coding itself fails** (the CLI crashes, behaves wrongly, or lacks what the project needs), the two jobs split:
- The orchestrator unblocks its own project with a crew workaround, never edits the fast-coding repo, and reports `fast-coding report ... tool-bug "<symptom, evidence, workaround used>"`. Every crew brief says the same.
- The first mate owns the tool. A tool-bug report from any crew wakes its `watch` and lands in `~/.fast-coding/tool-bugs.jsonl` with the CLI's commit and repo path (`cli_repo`). It briefs a toolsmith: `fast-coding crew start --project <slug> --role toolsmith --cwd <cli_repo> --brief -` with the report and evidence. A `--cwd` in another repo gets its own worktree on a new branch under that repo's `.claude/worktrees/` (the brief names it), so the repo's checkout, which every session runs, never switches branches. If Claude Code has never trusted that repo, `crew start` stops and says so: ask the captain to run `claude` there once and accept the prompt; never accept it for them. The toolsmith reproduces the bug, fixes the root cause with a test, runs the full suite, commits on its own branch, never merges or pushes, and reports `done` with the branch.
- The first mate asks the captain one line: "toolsmith fixed <X> on branch <B>, tests pass, merge?". On yes it fast-forwards the fast-coding repo's main to the branch, removes the toolsmith's worktree (`git worktree remove`), then tells each active orchestrator: "fast-coding updated; re-read SKILL.md in full now".
The orchestrator reports at every point the captain should hear about: `needs-user` for the one upfront decision request and for a task list that departs from the settled spec (3b), any question it must ask itself, and a payment halt; `working` when a run starts and when it ends; `done` when the stack is verified, with the stack, cost, and decision needed.
The orchestrator watches its own crew: plain `fast-coding watch` wakes on every task, run, verify, and crew event except its own reports.
Every crew session is started with `fast-coding crew start --role <role> --title "<tab label>" --brief -`: its own tab in the project's space, a Claude session named `<slug>-<role>`, briefed with how to report. `fast-coding crew list` shows each with its model and last report.
The model comes from `models.crew` in `~/.fast-coding/config.json`: the role's entry, else `default`. The orchestrator gets the most judgment (Sonnet at high effort, or a stronger model), because its judgment (reviewing layers, catching a test-gaming fix, root-causing a failure) saves whole verify cycles. Groundwork and tests crews write code against a clear brief, where Sonnet is enough and faster. A mechanical crew (a revert, a stack or port fix, a one-command job) is started with `--model small`, Haiku, since speed is all it needs.
Nothing is closed by hand: a crew session's tab closes by itself when the turn that reported `done` ends, so a crew reports `done` only when nothing is left for it (work waiting on your review is `working`).
The orchestrator's own `done` runs `fast-coding teardown`, which closes the implementers tab, the verify tab, and every crew tab whose last report is `done`; `shell`, `status`, and the orchestrator stay, and crew not yet done are left open and named.
`fast-coding crew stop --role <role>` remains for closing one early; it refuses a session that has not reported `done`, and `--force` is for the captain's say-so only.
The harness's in-process subagent tool (Claude's `Agent`) has no pane, so herdr cannot show it: inside herdr it is not used.
Names match `[a-z][a-z0-9_-]{0,31}` and are unique among live agents.
Outside herdr there is no first mate: the session the captain started is the orchestrator, the CLI commands run headless, wayfinder questions are asked one at a time in this session, and helpers are the harness's own subagents.

### 0a. Put the work in a project, in its own worktree
A project is one feature: its own git worktree and branch, one plan, one set of tasks, one gh stack. The moment the user invokes you with a task, decide which project it belongs to before anything else:
- Run `fast-coding projects --repo <path>`. If the request continues a feature that already has a project (same spec, same area of the code, or the user names it), use that project: new tasks get the next ids and become new layers of its stack.
- Otherwise create one: `fast-coding init --repo <path> --project <slug>`, where `<slug>` is a short kebab-case name for the feature in the user's words (`custom-dropdowns`, `workday-login`), not the repo's name and not a date. This creates branch `fast-coding/<slug>` from the branch the user is on and a worktree `../fast-coding-<slug>` next to the repo, with `.fast-coding/<slug>/` there, untracked.
Before anything else it ignores the tool's files: `graft/` and `.fast-coding/` go into an existing `.gitignore` as one commit of its own (`Ignore local tool directories`), and into the repo's `info/exclude` (with graft's `.ignore`) whether or not a `.gitignore` exists, so no tool file ever enters the branch.
Projects created before this keep their already-tracked `.fast-coding/<slug>/`; nothing about them changes.
Tell the user the project name and the worktree path in your first reply.
- Inside herdr, right after `init` and the feature issue exist, hand the project to its orchestrator (0h) and become the first mate. The rest of this skill is the orchestrator's.
- A lite project (0L) is made with `init --lite` and has no feature issue; the rest of 0a holds.
- Every project is one **feature issue** on Linear (label `Feature`, title in the user's words, under its epic when there is one). Create it if the user did not hand you one, and record its identifier in `.fast-coding/<slug>/linear.json` as `{"feature": "ENG-123"}`. Its stories, their tasks, and any decision tickets are its sub-issues, so the whole feature reads as one tree in Linear.
- From then on everything you do in code for this project happens in that worktree: acceptance tests, every commit, every `fast-coding` command (`--repo <worktree>`, or any checkout with `--project <slug>`: the CLI resolves it). Everything written in words (grilling notes, the plan, tasks, decisions) goes to Linear, never to a file (Rules). The user's own checkout and branch are never touched. Several projects can run at the same time, each in its own worktree with its own stack.
- The stack's trunk is `fast-coding/<slug>`; PRs target it, and one final PR takes the project branch to the user's branch.
- A project made with `init --after <other-slug>` starts from `fast-coding/<other-slug>`, records it as `review_base` in its `verify.json`, and shows `(after <other-slug>)` in `projects` and `status`. Its final PR targets that project's branch until that one merges, then the user's branch. `clean` counts a merge into either.
- Never mix two features in one project, and never spread one feature over two. If a request is really two features, make two projects and say so.
`fast-coding status --repo <path>` shows every project in every worktree with all its tasks; `--project <name>` shows one; `--watch` follows a run live. Use these when reporting progress.

### 0b. Find the way first when the decisions are not written down
Lite path (0L): skip this step; you take the recommended options and report them once.
A settled spec is a feature issue whose description says the way is clear: no open decision sub-issues, and `## Not yet specified` empty. A repo file (`DESIGN.md`, a PRD) counts too when the user points at it.
If none exists for this piece of work, do not plan yet: invoke the `wayfinder` skill with the epic (or the feature, when it is its own map) as the map (it is user-invocable only; when the Skill tool does not list it, read `~/.claude/skills/wayfinder/SKILL.md` and follow it). Wayfinder's tracker is Linear here, and this is how its operations map:
- the **map** is the epic issue, or the feature issue when there is no epic; its description is the map body (Destination, Notes, Decisions so far, Not yet specified, Out of scope)
- a **ticket** is a sub-issue of the map, labelled `wayfinder:<type>` (`research`, `prototype`, `grilling`, `task`), body `## Question`
- **blocking** is Linear's native "blocked by" relation (`save_issue` with `blockedBy`), so the frontier shows in Linear's own UI
- the **frontier** is `list_issues` on the feature's sub-issues: open, no unresolved blockers, unassigned
- **claim** by assigning the ticket to the user; **resolve** by posting the answer as a comment, setting the state to Done, and appending the one-line gist to the map's Decisions so far
- a **file** wayfinder or a skill it loads would write (`GRILLING.md`, research notes, a findings summary, a decision log) is a **Linear document** in the repo's project instead (`save_document` with the project from `.fast-coding/linear.json`), titled after its map and purpose (`<map>: grilling`), linked from the map's Notes; add to it with `save_document` rather than writing anything to disk. A file the user hands you stays where it is and is linked as a project resource.
- a **prototype** ticket about how a screen or a flow should look is drawn in Frame0 through the `frame0` MCP server (low-fi wireframes: `create_frame` with the device kind, text, rectangles, icons from `search_icons`, `create_connector` between frames for a flow, one page per ticket named after the ticket). Frame0 must be running with its API server on (Settings > API Server > Run on start); if the tools fail to connect, say so and wait rather than describing the design in words. Export the page with `export_page_as_image`, attach the image to the ticket (`prepare_attachment_upload` then `create_attachment_from_upload`), and walk the user through it in the grilling; the resolution comment names the Frame0 page. Logic or stub prototypes still go in code on a throwaway branch.
Wayfinder resolves one ticket per session, with the user, one question at a time and your recommendation on each; the grilling it runs is HITL, never answer for the user.
Inside herdr, frontier tickets that do not block each other are asked in parallel, one question agent each:
1. Chart the map yourself. The frontier is every open ticket with no unresolved blocker.
2. Per frontier ticket: `fast-coding crew start --role q-<ticket id> --title "<ticket title>" --brief -`, briefed with the ticket id and link, the map's id, the 0b Linear lookup rules, and: "invoke wayfinder for this one ticket; grill the captain in this pane, one question at a time with your recommendation; before every question, not only the first, re-read the map's Decisions so far and the resolution comments of tickets Done since your last look (other question agents are resolving tickets in parallel), and drop or reword any question they answer; when resolved, comment the answer on the ticket, set it Done, and append its one-line gist to the map's Decisions so far with a `save_issue` patch append, never a whole-description write; then report done."
3. Start at most three at once, so the captain is never juggling more; queue the rest.
4. Each question agent reports `needs-user` as it starts asking; relay that up as one `needs-user` naming every open question tab, so the captain knows where to answer.
5. On each `done`: the CLI has already forwarded its decision to every other open question agent. Its tab has closed itself; re-read the map, recompute the frontier (a resolved ticket can unblock others), and start the next. When a decision changes another open ticket's whole question, re-brief that agent yourself with `herdr agent prompt`.
6. When the frontier is empty and Not yet specified is empty, the way is clear: continue to step 1.
A ticket that blocks another is never asked in parallel with it. Research and prototype tickets are crew too, without the grilling. When it reports no fog (the way is already clear in one sitting), its grilling is the spec: write the decisions into the map's Decisions so far and continue to step 1.
Before any question reaches the user (charting, grilling, story writing), look for its answer in Linear first:
1. the map's Decisions so far and Notes, and the description and comments of the feature, its epic, and the story at hand
2. the resolution comments of Done tickets under the map (`list_issues` with the map as parent, then `list_comments`)
3. a `list_issues` search, scoped to the project in `.fast-coding/linear.json`, for the question's key terms, since another epic or feature may have decided it
A decision found there is settled: state it with its ticket's name and link, build on it, and do not ask again.
Ask only when Linear is silent, or when two recorded decisions conflict; then quote both and ask which one stands.
"We need to make decisions" from the user is fog, whatever deliverables the same request lists: a PRD, epics, user flows or a tech doc asked for up front are what the map and its resolved tickets become after the grilling, not drafts written around decisions you picked.
When the user cannot answer (a harness note says so, or no reply comes): chart the map, post the first question on its ticket, say so, and stop; the session ends at the question and 0r resumes it.

### 0g. Groundwork and the smoke check run while the captain answers
A captain answer takes minutes; nothing should wait on it that does not need it. The moment the project exists, before or alongside the first question, start one `groundwork` crew from the CLI's template, adding only what is specific to this project (the schema, the stub signatures, the wiring):
`fast-coding groundwork --project <slug> --extra - <<'EOF' | fast-coding crew start --project <slug> --role groundwork --title groundwork --brief -`
The template already carries the steps below, the e2e port rules, and phase C (the contract); never rewrite them by hand.
1. Install the repo's dependencies in the project worktree (task clones and verify borrow them).
2. Build and start the app on the current toolchain, the way a user would (`yarn build`, `go build ./...`, start the server and probe one URL), and run the existing tests. Unit tests passing is not proof the app runs.
3. Write each smoke command that passed into `verify.json` `checks` (build, plus a start-and-probe one-liner when starting differs from building), so every verify re-proves it.
4. Report what is broken (a dependency that fails on current Node or Go, a toolchain bump) as decisions with a recommendation, not fixes.
5. Once the captain decides, the groundwork crew applies dependency and toolchain changes itself with the package manager (`yarn upgrade`, a `resolutions` entry, `go get`), proves the smoke checks, and commits to the trunk before `run`. Dependency bumps, lockfile edits, and toolchain changes are never implementer tasks.
Its findings join the captain's one upfront request (Rules: ask once); they never surface after a run as a second wave.
An autonomous mode is never a mandate to decide for the user; the lite path (0L) is the one exception, for reversible decisions only, each reported.
It writes the e2e cases with the smoke checks; the acceptance tests are step 3's, written in parallel from the contract it leaves.
Helpers in this phase read research, draft ticket Questions, or draw a prototype whose decision is settled; none writes a document that carries an open decision.
Research the user points at (notes, a folder of findings) feeds the map's Notes; it is not the spec.
If a spec exists, read it and do not reopen its decisions. Open a decision ticket only for what it leaves open that the plan needs.

### 0r. Pick up where the last session stopped
Everything is on disk, so a restart is a non-event. At the start of a session on an existing project, before anything else: `fast-coding status --repo <wt> --project <slug>` and `fast-coding watch ... --now`, which prints the current state as event lines, then reconcile the Linear tree against them (0s). Then:
- `run INTERRUPTED` or a task `interrupted`: the previous run died with you. `fast-coding resume` re-runs what did not pass, in fresh agents, keeping passed layers. Reconcile Linear from the `--now` lines first, so the issues say what the disk says, parents included (0s).
- `HALTED ... payment required`: the user's stop; say so and wait for the word to `resume`.
- `run live`: another orchestrator session owns it. Supervise with `watch`, do not start a second run.
- Inside herdr, as the first mate: `fast-coding crew list --project <slug>`. A live `<slug>-orchestrator` owns the project: resume the relay loop (0h) and do nothing else. None, or its tab is closed: start it again with `crew start --role orchestrator`, briefed to continue from 0r.
- As the orchestrator: `crew list` too; live question agents and helpers keep their work, so watch them rather than starting duplicates.
- Herdr agents of a dead run are closed by the next run of their task; do not close them by hand.

### 1. Plan from the spec
Input is the feature issue's map and resolved tickets, plus `DESIGN.md`, a PRD, whatever the repo already had.
Read all of it. Then invoke `superpowers:writing-plans` for how to write the plan, but not where: the plan is a `## Plan` section in the feature issue's description (`save_issue`), never a file. Writing-plans' own save path does not apply.
`<project>` is a short slug for this piece of work, one repo can hold several; `.fast-coding/<project>/linear.json` holds `{"feature": "<feature issue id>"}` and is how the CLI finds the plan and the tasks.
The plan follows writing-plans conventions: numbered steps, each with files touched, the test that proves it, and explicit dependencies.
Decisions already made in the spec are not reopened.
The plan states the captain's quality bar up front, as acceptance criteria on the stories and tasks it touches, never as a later polish wave:
- anything user-facing looks finished and pixel-picky: spacing, alignment, readable type, and styled loading, empty, error, and success states
- the app builds and starts on the current toolchain (the 0g smoke checks stay green)
A second wave for polish or a toolchain fix the first wave could have seen is a planning miss.
The plan also states the simplicity bar, and every layer review holds the code to it:
- the simplest code that meets the requirements: no hardening, defensive flags, helpers, or extras the requirements do not ask for (signal handling, closed-state guards, retry layers)
- no wrapper scripts or shims when pinning a version or a documented setting works
- acceptance criteria name the required behavior and its real edge cases, never hardening beyond the requirements
The plan's `## Design facts` (deliberate choices a reviewer might flag: a single DB connection, credentials from env, stdout as the log) go into `verify.json` `review_context` now, before the first verify, so review never re-litigates them.

### 2. Split into tasks
Turn each plan step into a task issue on Linear (format below). There is no task file: the CLI reads the issue.
Tasks are tiny. A task is one function, one component, or one resolver: something the fast model finishes in one short turn, well under a minute. Small tasks pass first try; every miss so far was on the biggest task of its wave. When a task is not obviously tiny, split it; three tiny tasks finish sooner than one medium task that misses.
A task is right-sized when all of these hold:
- one or two files in `files:`, one test command, at most five acceptance criteria
- its brief (the issue description) stays under 2500 characters. `fast-coding tasks` prints `WARNING TASK TOO BIG` for a task over either limit: split it before 3b, never ship it to the gate
- no open design choices; every "how" is stated or obvious from the named files
- the whole task plus the files it touches fits comfortably in 20K tokens
- its branch will change at most 350 lines (added plus deleted). The CLI rejects a bigger branch, so size the task for it
- it adds no documents. Implementers never create .md, .txt, .rst, or docs/ files; the CLI rejects a branch that does. Docs are crew work after the reviewer has merged the PRs, only when the user asked for them
- it names every file it may touch in `files:`. The CLI rejects a change to any other file, so a task that needs a new file lists it. Two tasks never share a file; a shared file means they are one task or one is `after:` the other
- it is independent of other pending tasks, or its `after:` names the task whose code it needs. An `after:` task branches from that task's tip, so its code is there
Dependencies are only for code a task needs: it calls a function, imports a type, or edits a file that another task creates or owns. Never add `after:` for reading order, story order, or "the server before the client": every `after:` makes a task wait, and unrelated tasks must run in parallel. Review order comes from ids, not from `after:`. A pure function, a component, and a store method usually depend on nothing. `fast-coding tasks` prints the run waves and a `WARNING SERIAL CHAIN` when most tasks wait on one another; cut every edge that is not a real code need before 3b.
If its test cannot be written, it is not a task yet. Split further, or brief a crew session for it whole.
A task is a **task issue** on Linear: a sub-issue of its story, labelled `Task`, state Todo, its title the task's title, its description the brief (Goal, Acceptance criteria, Test plan, Constraints) ending with the `fast-coding` block, and `blockedBy` set to the issue of each task it builds on. That one issue is the CLI's contract, the implementer's brief, and where humans watch and edit the work.
The CLI never calls Linear; you hand it what Linear says. **Sync** right before every `tasks`, `run`, `resume`, and `verify`, so an edit anyone made in Linear is what runs:
1. `get_issue` on the feature (from `.fast-coding/<project>/linear.json`) for its id, title, and description.
2. `list_issues` with the feature as `parentId`, then with each story as `parentId`, for the ids only: `list_issues` truncates descriptions, and the block is at the end.
3. `get_issue` on every one of those issues with fields `id`, `title`, `description`, `status`, `relations`.
4. Pipe it in: `fast-coding sync --repo <wt> --project <slug> <<'EOF'` then `{"feature": {"id", "title", "description"}, "issues": [{"id", "title", "description", "status", "blockedBy": <relations.blockedBy as returned>}]}` then `EOF`. Pass every description whole, exactly as `get_issue` returned it; the CLI hands it to the implementer as the brief.
The commands refuse to start without a sync, and `sync` refuses a feature other than `linear.json`'s.
One feature, one stack. The project's tasks become the layers of a single `gh stack` on the branch the user invoked you from, in `after:` order and then id order: foundational code at the bottom, code that depends on it above, one concern per layer. Number tasks in the order a reviewer should read them. Independent tasks still run in parallel from trunk; the CLI rebases them into the one chain only when it registers the stack after the run.

### 3. Write the tests first (red)
The acceptance tests are the contract, so you specify every one, but crew write them, one per task, all at once.
The groundwork crew lays the ground first (0g): schema, codegen, stubs that compile, the e2e cases, and a contract file (`.fast-coding/<slug>/results/contract.md`, never committed) that pins every type, signature, value-or-pointer shape, fixture, and test path a test writer would otherwise guess.
When it reports `stubs ready`, run `fast-coding testcrews --project <slug>`: one `tests-NNN` crew per task (the `tests` or `groundwork` model under `models.crew`), each briefed with its task issue, the holdout rule below, its `protected:` path, and the contract. They commit only their own file. `--print` shows the briefs; `--only` picks tasks.
Parallel writers without the contract guessed shared types differently and wrote tests that fail on correct code; with it, writing every test takes about as long as writing one.
Groundwork that is real code, not a stub, is a task of its own (`000`) for `run`, not part of any brief.
For anything with a UI or a server, the browser e2e (the `e2e_setup` and `e2e` cases in `verify.json`, each with an `assert` that checks the real DOM or log) comes from the groundwork crew, before `run`, so the first verify drives the finished app; never "add e2e after the run".
Each crew reports `working "test ready"` once its file is committed, not `done`, since `done` closes its tab.
Read every test once they are all in (`git show`), send changes back with `herdr agent prompt <slug>-tests-NNN "..."` until each tests what its issue says, then tell each to report `done`.
List each test under `protected:`. The CLI rejects any attempt that changes a protected file.
It must fail on HEAD; `run` refuses a task whose test already passes.
Tests are proportional to the code they test:
- one test file per unit under test (a component, a resolver, a store), extended in place by later tasks and waves; never a new file per wave or per fix (`Questions.again.test.js`, `styles.polish.test.js` are wrong)
- they cover the behavior the requirements name plus its real edge cases; never CSS values, contrast math, or tooling wrappers (unless the wrapper is the deliverable)
- test code stays in the same order of magnitude as the product code; the tests crew is briefed with this and you send back anything bigger
Include holdout cases the task issue does not list. The implementer is told they exist, so it has to implement the behavior rather than the examples. The deny-list task showed why: given only the listed labels, the fast model wrote one literal regex per label.
Commit the tests before dispatching; independent tasks branch from HEAD, stacked tasks from their lower layer.

### 3b. The task list goes to the captain; it waits only when it departs from what they settled
Lite path (0L): no gate; fix every WARNING, then dispatch. `WARNING LITE PROJECT HAS N TASKS` means escalate to full.
Run `fast-coding tasks --repo <path> --project <name>`: every task's id, title, the files it owns, what it builds on, and its test, in stack order, then the run waves, with a warning for any file two tasks claim, any task too big, and a serial chain. Fix every WARNING first.
Then compare the list with the spec the captain settled (the map's Decisions so far and the stories):
- **It matches** (it builds exactly the settled scope, with no new or dropped scope, no dependency bump, no toolchain change, no decision the captain has not made): report `working` with the `tasks` output and one line per task on what its holdout cases cover, and dispatch right away. The captain can still stop it from the report.
- **It departs** in any of those ways: report `needs-user` with the list, each departure named, and your recommendation, and dispatch only after the captain's go.
The captain may combine, split, reorder, re-own, or drop tasks, here or in Linear, before or during a run. Apply the changes to the task issues (a dropped task's issue is Canceled and loses its `fast-coding` block), re-run `fast-coding tasks`, and re-run what changed. When the captain has said to review every task list, the gate is always a stop.
Green is the implementer's job. Refactor goes through review and the verify fix loop, whose fixer is the fast model; never the implementer refactoring its own green code, and never you typing it.

### 4. Dispatch
`fast-coding run --repo <path> --project <name>` runs tasks in dependency order: independent tasks in parallel, one clone and one implementer session (pi by default) each; a task with `after:` starts as soon as that task passes, on top of its branch. Test failures, an over-limit diff, a new document, or a change outside `files:` are fed back into the same session up to `--attempts` (default 3); a long test failure is fed back with a fast model's few-line summary of what failed ahead of the raw tail.
Each clone, and the worktree verify runs in, borrows the main checkout's git-ignored installs (`node_modules` at any depth, `vendor`, `.venv`) as symlinks that never show in `git status`, and graft never edits `.gitignore` there. So install dependencies once in the project worktree before `run`; do not patch test commands to link them.
The trunk is the branch the user is on when you run it (`--trunk` overrides). That checkout is never switched: clones are separate repos, and every `gh stack` operation runs in a CLI-owned detached worktree under `.fast-coding/<project>/worktrees/.stackroot`, with the stack state mirrored into the user's `.git` so `gh stack view` works from a task branch there.
When the run ends, all passed task branches of the project are rebased into one linear chain on the trunk tip and registered as one stack: `(my-feature) <- fast/<project>/001 <- fast/<project>/002 <- fast/<project>/003`, printed on a `stack ok` line. A later wave grows the same stack; before it starts, the existing layers are rebased onto the current trunk so new tests and task files are present on every base. A rebase conflict stops the chain at that layer with the exact commands to resolve it. `--no-stack` skips registration, and a lite project (0L) never registers one.
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
You are the senior engineer over the fast models. Review each layer the moment its `state=passed` event arrives, while the rest of the run continues, not after the run: a task stacked on it starts right away, so a bad layer caught late has been built on.
`run` ends with a `NNN triage clean|flag: <reason>` line per passed task: a fast model checked each diff against its brief and the simplicity bar, all at once (`fast-coding triage` repeats it). Read flagged layers in full and skim the clean ones (file list and diffstat); a flag is a pointer, never a verdict, and a clean is not a pass.
Read `.fast-coding/<project>/results/NNN.json` and the layer's own diff: `git diff <base>..fast/<project>/NNN`, where `base` is in the result (`HEAD` or the lower task's branch). `gh stack view --json` from a task branch shows the chain.
Passing is not done. Reject scope creep, gamed tests, site-specific hacks, over-engineering (anything past the plan's simplicity bar), and poor quality; a rejected layer is re-split or fixed, then re-run, and every task stacked on it re-runs on the new layer (`run --only <its id and theirs> --redo`). Comment the rejection on the task's issue in one paragraph. You never merge, locally or on GitHub. When the user says so, `fast-coding stack --submit` pushes the stack and opens one draft PR per layer; a human reviewer reads them bottom-up and decides on GitHub whether the stack merges. `gh stack merge` is the reviewer's tool, not yours.

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
  "review": true, "review_base": "main", "fix_model": "pi:openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast",
  "review_context": "Design facts reviewers must respect, e.g. test credentials come from env by design and never reach the server."
}
```
e2e runs at the same time as review and jev acceptance, right after checks, since those two only wait on model calls.
Each e2e stage gets two fresh free ports, `$E2E_PORT` and `$E2E_CLIENT_PORT`, in the environment of `e2e_setup`, `driver` and `assert`, and expanded in `url` and `goal`.
Use them; never hardcode a port, unless the app itself pins one (then keep that one and nothing else fixed).
Start servers in `e2e_setup` with a plain `&`; never free ports there with `lsof | kill`.
The stage ends everything it started when it ends, pass or fail: the setup's process group, and anything left listening on its ports or the browser's CDP port, so no server or browser outlives a round.
A failure that is the harness's (a jev or browser crash, a missing tool, a port in use) is reported as `TOOL ERROR`, retried once, and never handed to a fix round; only app failures are.
1. **checks**: lint, unit tests, and the 0g smoke checks, exact and cheap, run first. Formatting is already done: `run` formats each passed task's own files (gofmt, the repo's installed prettier) before committing, and keeps the unformatted version if formatting would break the test.
2. **review**: parallel fast-model reviews (Mercury 2.5 via the jev-ultrafast `.env`), one per perspective, then a confirmation call per high or medium finding that must quote the code. Unconfirmed findings are dropped and shown as dropped. Only confirmed highs fail the stage.
3. **jev acceptance**: every bullet under `## Acceptance criteria` in every task issue becomes one choice question to Jev (TypeSafe): MET, NOT_MET, UNCLEAR, with probabilities, one request per task against that task's own files, then a confirmation call per NOT_MET. Advisory by default, since the tests already cover every criterion; set `acceptance_gate: true` to make confirmed NOT_MET fail the stage.
4. **e2e**: each case drives a real browser with jev-ultrafast to the goal, then runs `assert`, an independent check (written by the tests crew) that reads the real DOM or run log. A DONE from the model is never the proof.
5. **fix loop** (`--fix N`, default 2): confirmed findings go to the fast implementer in the repo itself, protected files are reverted if touched, the fix is committed, and every stage runs again. A fixer has the tasks' scope: a round that touches any file the stack does not already change (a lockfile, `setupTests.js`, a new `package-lock.json`) is reverted whole and verify ends FAIL. Treat that FAIL as an environment problem for crew, not a finding. After N rounds it escalates to you with the findings. `--fix 0` reports only.

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
A task that exhausts its attempts comes back with its full log. Read the log, then split: write two or three smaller, more specific tasks that each name the exact function, file, and behavior the log shows the implementer missed, have the tests crew give each its own red test, and dispatch those. Never re-dispatch the same task unchanged, and do not pick up the keyboard yourself just because an attempt failed. The exhausted task's issue is Canceled with a comment pointing at the issues that replace it; the new tasks get their own issues, blocked by whatever the old one was blocked by.
When the blocker is not the task (the fast provider is down, or the task cannot be made smaller than one function), the work still goes to crew, never to your keyboard: set `model: claude` in the task's block and `run --only` it, or brief a crew session for it. Work crew did outside `run` is recorded with `fast-coding done --project <name> --only 024,025 --note "provider out of credit; done by <slug>-<role>"`, so `fast-coding status` shows the truth, and the report says so.
A rebase conflict while stacking (`after: ... could not be chained`) is crew work too: brief one with the two branches and the conflicting files.
`fast-coding status --repo <path> [--watch]` shows every project with each task's state, attempts, time, cost, and stack layer; use it to report progress instead of describing it from memory. `fast-coding watch` is how you wait for it to change.
`fast-coding clean --repo <path>` is the post-merge step, run after the reviewer has merged PRs on GitHub (or the user merged locally): it fetches, removes task clones and the CLI's stack worktree, deletes task branches that are proven merged (contained in the trunk or its remote, or a merged PR on GitHub, which also covers squash and rebase merges), and once every layer and the project branch are merged it removes the project's worktree and branch too. Unmerged work is kept and named. It never deletes unmerged layers unless `--delete-unmerged`. Run it whenever the user says PRs were merged, and at the end of a feature. Then move each merged task's issue to Done and roll its story, feature, and epic up (0s): the feature is Done once every layer and the project branch are merged. A task you did by hand (`fast-coding done`) goes to Done with the same note.

## Task issue format

`model:` is `pi:<provider/model>` for the pi harness (the default: lean, ~1K tokens of fixed context per turn), an OpenCode model id, `claude:<model-id>` for Claude Code on that model, or bare `claude` for Claude Code's default. A Claude model is always written with its `claude` prefix, never as a bare id, so it is never mistaken for a pi or OpenCode model. Omit it for the CLI default, `pi:openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast` (GLM 5.3 Flash; the preset pins Together, then CoreWeave). gpt-oss-120b on Cerebras was the default until 2026-10-10 and was dropped for missing too often.
Leave `model:` unset. A task that seems to need a stronger model is a task to split, or work for groundwork (dependencies, toolchain). Setting `model: claude` (or any non-default model) on a planned task is a captain decision: it goes into the one upfront request with the reason, never only into a later report.
There is no fallback by default. When `models.fallback` is set, an attempt that errors, times out, is rate-limited, or misses moves the task to it in a fresh session that carries the failure; fix rounds after the first use it too. `bench` never falls back.
`run` and `resume` probe every model they may call (each task's, and the fallback) with one tiny prompt before cloning anything; a wrong model id or preset slug stops the run there with the provider's message.
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
model: pi:openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast
```
````

- `id` is the stack order a reviewer reads in; ids are unique within the feature.
- `after` is not in the block: it is the issue's "blocked by" links to other tasks of the feature. Each one becomes the layer this task stacks on, and makes it wait, so link only a task whose code this one needs.
- An issue under the feature without the block is not a task (stories, decision tickets): the CLI ignores it.

## Rules
- On the lite path (0L) the captain settles by default: the recommended options you took and reported. Everything else below holds there too.
- Nothing is implemented beyond what the captain settled. Intake, wayfinder, stories, the plan, task issues, and tests are all preparation; `fast-coding run` is the first implementing action. It starts without a further go when the task list matches the settled spec, and waits for an explicit go whenever it departs from it (step 3b), every wave.
- Tests are the contract. The implementer never edits them.
- A failure of fast-coding itself is a `tool-bug` report, never a silent workaround and never an edit to the fast-coding repo from a project (0h): the project works around it, the first mate's toolsmith fixes the tool, and the captain approves the merge.
- Commit messages describe the change itself, in plain words (`Save submissions in one transaction`). Crew and the orchestrator never mention fast-coding, waves, task ids, crews, Linear, or the process in a commit message; the CLI's own commits follow the same rule.
- The first mate and the orchestrator never write or edit code: no source, test, stub, fixture, build or CI config, generated file, or repo doc, not even a one-line fix. They read code to review it, write Linear, write the CLI's JSON (`.fast-coding/linear.json`, `.fast-coding/<slug>/linear.json`, `verify.json`), and run `fast-coding`, `git` reads, and `herdr` (on the lite path, `verify` merges the task branches into the project branch itself). Every change to the repo is crew work or a task for `run`. For the orchestrator a hook enforces it: its tab carries `FAST_CODING_ROLE=orchestrator`, and the plugin's `fast-coding guard` denies its Write and Edit calls inside a repository. Do not route around the hook through Bash.
- Every document you write for a human is shaped by the `i-have-adhd` skill: Linear descriptions and comments (maps, specs, plans, stories, tasks, grilling notes, steers), and the briefs you give crew. That skill is user-invoked only, so the Skill tool cannot load it; before writing the first document of a session, read `~/.claude/plugins/marketplaces/i-have-adhd/skills/i-have-adhd/SKILL.md` and apply its rules to everything you write from then on. Writing-plans and the task issue format fix the sections; i-have-adhd fixes the shape inside them: first line is the next action, multi-step work is numbered, lists stop at five, no preamble, no recap.
- You steer, you do not type. Talk to the captain in outcomes, not mechanics; empty polls and no-change updates are not progress. Your final message stands alone: what finished, the stack, the cost, and the decision needed.
- Every captain round-trip stalls the whole project, so ask once, up front. Start groundwork and the smoke check (0g) first, so its toolchain and dependency findings are in hand; then send every decision you can see coming (scoring, toolchain, dependency bumps, the quality bar where it is unclear) as one `needs-user` with a numbered list and your recommendation on each, instead of one question, a wait, then the next. Keep groundwork running while it waits. Ask mid-run only when the run cannot continue without the answer.
- The CLI's own config is yours to fix without asking: a wrong model id, preset slug, or typo in `~/.fast-coding/config.json` `models`, `verify.json`, or `linear.json`. Fix it, re-run, and mention it in your next report. Switching to a different model or provider, keys, and anything that costs money are still the captain's.
- Linear is the source of truth and the ticket tracker. What it records as decided is decided: read it before asking the user anything (0b), and write every new answer back to it, so the next session finds it. Nothing written in words is ever a file in the repo: no plan, task, ticket, map, decision, grilling note, or task list, not under `.fast-coding/` and not anywhere else (the only files there are the CLI's JSON: `linear.json`, `verify.json`, and `results/`, all git-ignored and never committed); everything a human would read as a ticket is an issue under the feature issue, and its state is kept true at every step, at every level (0s): a task is Todo when written, In Progress when dispatched, In Review when its layer passed, Done when merged, Canceled when dropped or re-split, and its story, feature, and epic roll up from it in the same step.
- A `PAYMENT REQUIRED` stop is the user's, not yours. When `run` or `verify` exits 3 with that banner, stop everything and tell the user in one short message: which provider refused, the provider's own words, the top-up link the banner printed, and that `fast-coding resume --repo <path> --project <name>` continues from exactly where it stopped (passed tasks keep their branches, remaining tasks run, a halted verify reruns). Do not switch providers, re-dispatch, hand-implement, or retry around a billing stop. When the user says the account is fixed, run `resume`.
- A task branch changes at most 350 lines and never adds a document. These are CLI-enforced; plan tasks that fit, do not fight the guard.
- Never push or submit a stack without the user's explicit permission for that push. `run` registers stacks locally only.
- Fresh session per task. Never chain tasks in one session.
- Keep the target repo's fixed context small: short AGENTS.md, no unneeded MCP servers, no duplicate skills.
- Build a graft graph in the repo (`graft build .`, free, git-ignored). The CLI prepends a `graft ask` context pack with exact `file:line` and source to every implementer and fixer prompt, and tells the model to use `graft ask` and `graft callers` instead of exploring. Without graft the fast model reads whole files and every extra tool call resends the full context.
- Report honestly: attempts per task, what escalated, what crew did outside `run`, and the verify output.
- Always show timing and cost. Paste the CLI's `run start` and `run done` lines, the per-task table, the `verify` stage lines, and the final `cost` line into your report. The user wants to see when it started, how fast it finished, and what each implement cost, every time.
