# fast-coding

A frontier model plans and reviews.
Parallel OpenCode instances on a fast model implement.
Verification is local.

- `SKILL.md` is the orchestrator's instructions, linked into `~/.claude/skills/fast-coding`.
- `bin/fast-coding` is the dispatcher, linked into `~/.local/bin/fast-coding`. Python stdlib only.

```bash
fast-coding init   --repo . --project <name>   # .fast-coding/<name>/{tasks,results,verify.json}
fast-coding run    --repo . --project <name>   # one worktree + one OpenCode session per task, in parallel
fast-coding verify --repo . --project <name>   # checks, confirmed Mercury review, Jev acceptance, jev e2e, fix loop, cost
fast-coding clean  --repo . --project <name>
```

## How the loop works

```
                          ORCHESTRATOR  (Claude, frontier)
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  spec (GRILLING.md, DESIGN.md, ticket)                                   │
  │     │                                                                    │
  │     ▼                                                                    │
  │  plan.md ──▶ tasks/001.md 002.md 003.md ...   (goal, ACs, test plan)     │
  │                  │                                                       │
  │                  ▼                                                       │
  │  write tests/*.test.js  (RED on HEAD, holdout cases inside, protected)   │
  │                  │                                                       │
  │              git commit                                                  │
  └──────────────────┼───────────────────────────────────────────────────────┘
                     │  fast-coding run
                     ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  DISPATCH   one worktree + one OpenCode session per task, in parallel    │
  │                                                                          │
  │   task 001              task 002              task 003                   │
  │   ┌────────────┐        ┌────────────┐        ┌────────────┐            │
  │   │ test RED?  │        │ test RED?  │        │ test RED?  │  no ──▶ skip│
  │   │    yes     │        │    yes     │        │    yes     │  (already   │
  │   │     ▼      │        │     ▼      │        │     ▼      │   green)    │
  │   │ ┌────────┐ │        │ ┌────────┐ │        │ ┌────────┐ │            │
  │   │ │OpenCode│ │        │ │OpenCode│ │        │ │OpenCode│ │            │
  │   │ │ Qwen   │ │        │ │ Qwen   │ │        │ │ Qwen   │ │  Cerebras  │
  │   │ │Cerebras│ │        │ │Cerebras│ │        │ │Cerebras│ │  ~2000 t/s │
  │   │ └───┬────┘ │        │ └───┬────┘ │        │ └───┬────┘ │            │
  │   │     ▼      │        │     ▼      │        │     ▼      │            │
  │   │ run test   │        │ run test   │        │ run test   │            │
  │   │ protected  │        │ protected  │        │ protected  │            │
  │   │ untouched? │        │ untouched? │        │ untouched? │            │
  │   │  │      │  │        │            │        │            │            │
  │   │ GREEN  RED─┼─┐      │    ...     │        │    ...     │            │
  │   │  │      ▲  │ │ feed failure back, same session, ≤3 attempts          │
  │   │  │      └──┼─┘      │            │        │            │            │
  │   │  ▼         │        │            │        │            │            │
  │   │ commit on  │        │            │        │            │            │
  │   │ fast/001   │        │            │        │            │            │
  │   └────────────┘        └────────────┘        └────────────┘            │
  │                                                                          │
  │   results/NNN.json  +  per-task time  +  $ cost                          │
  └──────────────────┬───────────────────────────────────────────────────────┘
                     │
                     ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  ORCHESTRATOR REVIEW   git diff main..fast/NNN                           │
  │     accept ──▶ git merge        reject / exhausted ──▶ fix by hand       │
  └──────────────────┬───────────────────────────────────────────────────────┘
                     │  fast-coding verify        (all local, nothing pushed)
                     ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  VERIFY PIPELINE                                                         │
  │                                                                          │
  │  1 checks      lint + unit tests                        exact, cheap     │
  │       │                                                                  │
  │  2 review      Mercury x4 in parallel ──▶ confirm each finding           │
  │                correctness security spec docs    (must quote the code)   │
  │                dropped ─── unconfirmed                                   │
  │       │        confirmed high ──▶ FAIL                                   │
  │  3 jev         one choice question per acceptance criterion             │
  │                MET / NOT_MET / UNCLEAR with probabilities   ~0.3 s       │
  │       │                                                                  │
  │  4 e2e         jev-ultrafast drives a real browser to the goal          │
  │                then YOUR assert reads the real DOM                       │
  │       │                                                                  │
  │       ▼                                                                  │
  │   all ok? ── yes ──▶ PASS  +  time  +  cost per provider  +  total       │
  │       │                                                                  │
  │       no                                                                 │
  │       ▼                                                                  │
  │  5 fix loop    confirmed findings ──▶ OpenCode/Qwen in the repo          │
  │                protected files reverted if touched, commit, rerun 1-4    │
  │                ≤ N rounds ──▶ still failing ──▶ ESCALATE to orchestrator │
  └──────────────────────────────────────────────────────────────────────────┘

  Who decides what
    frontier (Claude)   plan, tests, review, merge, refactor, escalations
    fast (Qwen)         green only, one task, one session, never tests
    Mercury             raise findings, then confirm or drop them
    Jev                 score acceptance criteria, drive the browser
    CLI                 red check, protected-file guard, timing, cost ledger
```

Implementer model: `cerebras/qwen-3.8-27b` through OpenCode, configured in `~/.config/opencode/opencode.jsonc`.
Reviewer model: whatever `~/code/jev-ultrafast/.env` names as `TEXT_MODEL`, Mercury 2.5 by default.
Browser e2e: jev-ultrafast's `Agent`, with an independent `assert` command per case.
Acceptance review: Jev (TypeSafe) answers one MET/NOT_MET/UNCLEAR question per acceptance criterion.
Every run and verify ends with a cost line per provider and a total.

First real run: the submit deny list in `~/code/jev-autofill-test`, passed on attempt 2 in 11.7 seconds.
