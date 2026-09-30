---
name: fast-coding
description: Plan with a frontier model, implement with parallel OpenCode instances on a fast model (Qwen 3.8 27B on Cerebras), verify locally with jev-ultrafast browser runs and a Mercury review. Use when the user says "fast-coding", "fast loop", "fan out to opencode", or wants a spec such as GRILLING.md and DESIGN.md turned into a plan and tiny numbered tasks that cheap fast models implement while Claude plans, tests, reviews, and verifies. Works in any repo.
---

# fast-coding

You are the orchestrator. OpenCode on a fast model is the implementer. Verification is local; nothing is pushed.

| Who | Does | Never does |
|---|---|---|
| You (frontier) | Read the spec, write the plan, split into tasks, write each acceptance test, dispatch, review diffs, run verify, merge, take over escalated tasks | Type implementation a task file covers |
| OpenCode (fast) | One task file, the named files, until its test passes | Edit protected files, plan, touch other tasks |
| `fast-coding verify` | Checks, jev-ultrafast browser e2e, Mercury diff review | Push, open PRs, run CI |

## Workflow

### 1. Plan from the spec
Input is whatever the repo has: `GRILLING.md`, `DESIGN.md`, a ticket, a PRD.
Read all of it. Then invoke `superpowers:writing-plans` and write the plan to `.fast-coding/<project>/plan.md` (run `fast-coding init --project <name>` first).
`<project>` is a short slug for this piece of work, one repo can hold several.
The plan follows writing-plans conventions: numbered steps, each with files touched, the test that proves it, and explicit dependencies.
Decisions already made in the spec are not reopened.

### 2. Split into tasks
Turn each plan step into `.fast-coding/<project>/tasks/NNN-slug.md` (format below).
A task is right-sized when all of these hold:
- one to three files, one test command, under ten acceptance criteria
- no open design choices; every "how" is stated or obvious from the named files
- the whole task plus the files it touches fits comfortably in 40K tokens
- it is independent of other pending tasks, or its `after:` lists the ids it needs merged first
If you cannot write its test, it is not a task yet. Split further or do it yourself.

### 3. Write the tests first
The acceptance test is yours. List it under `protected:`. The CLI rejects any attempt that changes a protected file.
Commit tests and task files before dispatching; worktrees branch from HEAD.

### 4. Dispatch
`fast-coding run --repo <path> --project <name>` runs every task in parallel, one worktree and one OpenCode session each, feeding test failures back into the same session up to `--attempts` (default 3).
Use `--only 003,004` for a subset. Run `after:`-dependent tasks in a later wave once their prerequisites are merged.

### 5. Review
Read `.fast-coding/<project>/results/NNN.json` and `git diff main..fast/<project>/NNN`.
Passing is not done. Reject scope creep, gamed tests, site-specific hacks, and poor quality. Merge what is good.

### 6. Verify
`fast-coding verify --repo <path> --project <name>` runs `.fast-coding/<project>/verify.json`:
```json
{
  "checks": ["uv run ruff check .", "node --test tests/"],
  "e2e": [{"name": "greenhouse fill", "url": "https://...", "goal": "Fill the application ... stop before Submit.",
           "assert": "python scripts/check_greenhouse.py"}],
  "review": true, "review_base": "main"
}
```
- `checks`: lint and unit tests, run in the repo.
- `e2e`: each case drives a real browser with jev-ultrafast to the goal, then runs `assert`, an independent check you write that reads the real DOM or run log. A DONE from the model is never the proof.
- `review`: the merged diff and the plan go to the fast text model configured in `~/code/jev-ultrafast/.env` (Mercury 2.5 by default), which returns pass/fail with concrete issues. Treat its findings as leads to check, not verdicts.
Fix what fails, re-run. Only then tell the user it is done, with the verify output.

### 7. Escalate and clean
A task that exhausts its attempts comes back with its full log. Fix it yourself using that log; do not re-dispatch it unchanged.
`fast-coding clean --project <name>` removes worktrees and branches after merging.

## Task file format

```markdown
---
id: 001
title: Submit deny list
files: extension/deny_list.js
protected: tests/deny_list.test.js
test: node --test tests/deny_list.test.js
model: cerebras/qwen-3.8-27b
after:
---

## Goal
One paragraph. What to build, where, exact export names.

## Acceptance criteria
- One bullet per behavior. Each is checked by the test.

## Constraints
- No new dependencies. Do not edit protected files.
```

## Rules
- Tests are the contract. The implementer never edits them.
- Fresh session per task. Never chain tasks in one session.
- Keep the target repo's fixed context small: short AGENTS.md, no unneeded MCP servers, no duplicate skills.
- Report honestly: attempts per task, what escalated, what you changed by hand, and the verify output.
- Always show timing. Paste the CLI's `run start` and `run done` lines and the per-task table into your report, and the `verify` lines with their durations. The user wants to see when it started and how fast it finished every time.
