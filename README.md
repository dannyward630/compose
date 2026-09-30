# fast-coding

A frontier model plans and reviews.
Parallel OpenCode instances on a fast model implement.
Verification is local.

- `SKILL.md` is the orchestrator's instructions, linked into `~/.claude/skills/fast-coding`.
- `bin/fast-coding` is the dispatcher, linked into `~/.local/bin/fast-coding`. Python stdlib only.

```bash
fast-coding init   --repo . --project <name>   # .fast-coding/<name>/{tasks,results,verify.json}
fast-coding run    --repo . --project <name>   # one worktree + one OpenCode session per task, in parallel
fast-coding verify --repo . --project <name>   # checks, jev-ultrafast e2e, Mercury diff review
fast-coding clean  --repo . --project <name>
```

Implementer model: `cerebras/qwen-3.8-27b` through OpenCode, configured in `~/.config/opencode/opencode.jsonc`.
Reviewer model: whatever `~/code/jev-ultrafast/.env` names as `TEXT_MODEL`, Mercury 2.5 by default.
Browser e2e: jev-ultrafast's `Agent`, with an independent `assert` command per case.

First real run: the submit deny list in `~/code/jev-autofill-test`, passed on attempt 2 in 11.7 seconds.
