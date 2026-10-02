---
name: fast-coding
description: The full fast loop for a feature, from first question to verified stacked branches. Grill the user until the decisions are settled (GRILLING.md), plan, split into tiny numbered tasks with tests, fan the tasks out to parallel implementers (pi running gpt-oss-120b, pinned to Cerebras by an OpenRouter preset; OpenCode and Claude available per task), verify locally with jev-ultrafast browser runs and a Mercury review, register each chain as a gh stack. Use when the user says "fast-coding", "fast loop", "fan out", or asks to build a feature or prototype fast. Works in any repo.
---

# fast-coding

You are the orchestrator. The implementer is pi running gpt-oss-120b on Cerebras (through the OpenRouter preset `gpt-oss-120b-cerebras`); OpenCode or Claude can take a task via `model:`. Verification is local; nothing is pushed.
This skill is the whole flow: the moment the user invokes it with a task, start at step 0 and carry it through to verified, stacked branches.

| Who | Does | Never does |
|---|---|---|
| You (orchestrator) | Grill the user, write the spec and plan, split into tasks, write each acceptance test, dispatch, review diffs, run verify, merge, take over escalated tasks | Type implementation a task file covers |
| Implementer (fast model via pi or OpenCode) | One task file, the named files, until its test passes, under 350 changed lines, adding no documents | Edit protected files, plan, touch other tasks |
| `fast-coding verify` | Checks, jev-ultrafast browser e2e, Mercury diff review | Push, open PRs, run CI |

## Workflow

### 0. Grill first when the decisions are not written down
Look for a settled spec in the repo: `GRILLING.md` or `DESIGN.md` (or any file a grilling session produced, such as `docs/decisions/` from `grill-with-docs`).
If none exists for this piece of work, do not plan yet: invoke the `grilling` skill (or `grill-with-docs` when the user wants ADRs and a glossary as a by-product) and interview the user until the decision tree is resolved, one question at a time, with your recommendation on each.
Record the outcome in `GRILLING.md` in the repo, with absolute paths for every folder it names, then continue to step 1.
If a spec exists, read it and do not reopen its decisions. Grill only the decisions it leaves open that the plan needs.

### 1. Plan from the spec
Input is `GRILLING.md`, `DESIGN.md`, a ticket, a PRD, whatever step 0 left or the repo already had.
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
- its branch will change at most 350 lines (added plus deleted). The CLI rejects a bigger branch, so size the task for it
- it adds no documents. Implementers never create .md, .txt, .rst, or docs/ files; the CLI rejects a branch that does. Docs are the orchestrator's, edited by hand after merge, only when the user asked for them
- it is independent of other pending tasks, or its `after:` names the task it builds on. A task with `after:` becomes the next layer of that task's stack: it branches from the lower task's tip and its PR shows only its own diff
If you cannot write its test, it is not a task yet. Split further or do it yourself.
Design chains the way `gh stack` wants them: foundational code at the bottom, code that depends on it above, one concern per layer, strictly linear. Two tasks that both need the same lower task are siblings; only one can stack on it, the other waits for the merge.

### 3. Write the tests first (red)
The acceptance test is yours. List it under `protected:`. The CLI rejects any attempt that changes a protected file.
It must fail on HEAD; `run` refuses a task whose test already passes.
Include holdout cases the task file does not list. The implementer is told they exist, so it has to implement the behavior rather than the examples. The deny-list task showed why: given only the listed labels, the fast model wrote one literal regex per label.
Commit tests and task files before dispatching; independent tasks branch from HEAD, stacked tasks from their lower layer.
Green is the implementer's job. Refactor is yours, through review and the verify fix loop, never the implementer refactoring its own green code.

### 4. Dispatch
`fast-coding run --repo <path> --project <name>` runs tasks in dependency order: independent tasks in parallel, one clone and one OpenCode session each; a task with `after:` starts as soon as that task passes, on top of its branch. Test failures, an over-limit diff, or a new document are fed back into the same session up to `--attempts` (default 3).
Use `--only 003,004` for a subset. When the run ends, every chain of passed branches is registered as a `gh stack` (`(main) <- fast/<project>/001 <- fast/<project>/002`), printed on a `stack ok` line. `--no-stack` skips that, `--trunk` changes the base.
Nothing is pushed. `fast-coding stack --submit` runs `gh stack submit --auto`, which pushes every branch and opens draft PRs: run it only when the user has explicitly asked for that push.

### 5. Review
Read `.fast-coding/<project>/results/NNN.json` and the layer's own diff: `git diff <base>..fast/<project>/NNN`, where `base` is in the result (`HEAD` or the lower task's branch). `gh stack view --json` from a task branch shows the chain.
Passing is not done. Reject scope creep, gamed tests, site-specific hacks, and poor quality. Merge what is good, bottom layer first; `gh stack merge <pr> --yes` merges a PR and everything below it once PRs exist.

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
A task that exhausts its attempts comes back with its full log. Fix it yourself using that log; do not re-dispatch it unchanged.
`fast-coding clean --project <name>` removes worktrees and branches after merging. Stacks registered for merged branches disappear with them; `gh stack sync --prune` tidies the GitHub side if PRs were submitted.

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
- A task branch changes at most 350 lines and never adds a document. These are CLI-enforced; plan tasks that fit, do not fight the guard.
- Never push or submit a stack without the user's explicit permission for that push. `run` registers stacks locally only.
- Fresh session per task. Never chain tasks in one session.
- Keep the target repo's fixed context small: short AGENTS.md, no unneeded MCP servers, no duplicate skills.
- Build a graft graph in the repo (`graft build .`, free, git-ignored). The CLI prepends a `graft ask` context pack with exact `file:line` and source to every implementer and fixer prompt, and tells the model to use `graft ask` and `graft callers` instead of exploring. Without graft the fast model reads whole files and every extra tool call resends the full context at Cerebras prices.
- Report honestly: attempts per task, what escalated, what you changed by hand, and the verify output.
- Always show timing and cost. Paste the CLI's `run start` and `run done` lines, the per-task table, the `verify` stage lines, and the final `cost` line into your report. The user wants to see when it started, how fast it finished, and what each implement cost, every time.
