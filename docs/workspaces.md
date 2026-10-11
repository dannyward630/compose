# Workspaces

A workspace is one OpenRouter account and its settings: which key every call bills to, plus optional models and env.
`default` always exists.

## Commands

```bash
fast-coding workspace                         # list (* = active, keys as their last 4 characters) and the active models
fast-coding workspace personal                # switch; run and verify print `workspace <name>` first
pbpaste | fast-coding workspace add client-x  # create one with the key on the clipboard
pbpaste | fast-coding workspace key client-x  # set or rotate its key; add --linear for its Linear key
fast-coding workspace remove client-x         # delete; removing the active one switches to default
```

From Claude Code: `/fast-coding:workspace`, `/fast-coding:workspace personal`, `/fast-coding:workspace add client-x`.
The slash command never asks for a key in chat; type `! pbpaste | fast-coding workspace key <name>` instead.

- Keys come from piped stdin or a hidden prompt, never an argument.
- A workspace added without a key stops every command while active, instead of billing another account.
- Names are letters, digits, `-`, and `_`; `add`, `key`, `remove`, and `default` are reserved.

## Config

The commands edit `~/.fast-coding/config.json` (mode 600).
The active workspace is merged over the top level:

```json
{"workspace": "work",
 "models": {"implementer": "pi:openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast",
            "fallback": null, "fix": "<default: implementer>",
            "crew": {"planner": {"model": "pi:openai/gpt-6-astra", "effort": "high",
                                 "fallback": [{"model": "claude:claude-opus-5-5", "effort": "high"}]},
                     "groundwork": "claude:claude-opus-5-5", "default": "claude:claude-sonnet-5-5", "small": "claude:claude-haiku-5-5"}},
 "env": {"TYPESAFE_API_KEY": "<any env var the CLI and its tools read>"},
 "workspaces": {"work": {"openrouter_api_key": "sk-or-..."},
                "personal": {"openrouter_api_key": "sk-or-...", "linear_api_key": "lin_api_..."}}}
```

The workspace key reaches pi, OpenCode, the Mercury review, and jev, so every OpenRouter call bills that account.
OpenRouter presets belong to an account: create `glm-5-3-flash-fast` in each workspace's account.
`run` and `resume` send each model one tiny prompt first, so a wrong id or preset stops the run with the provider's message.

A model id names its harness:

| Id | Runs |
|---|---|
| `pi:<provider/model>` | pi |
| `claude:<model-id>` | Claude Code with that model |
| `claude` | Claude Code with its default model |
| anything else | OpenCode |

## Linear key

A workspace's `linear_api_key` lets the CLI keep Linear's states true: tasks In Progress and In Review, stories and the feature rolled up, the feature In Review on verify PASS.
Without it the CLI prints one `linear skipped` line and carries on; a Linear error never stops a run.

## Crew models

`models.crew` picks each crew session's model by role, then `default`.

- An entry is a model id, or `{"model": ..., "effort": "high"}` to set Claude Code's `--effort` (pi's `--thinking` for a `pi:` model).
- An entry may carry a `fallback`: another entry or an ordered list.
- `crew start` probes the primary, then each fallback, once a day each, takes the first that answers, and prints which and why; the last entry is never probed.
- The orchestrator and wayfinder use `planner` when they have no entry; groundwork and test crews use `groundwork`.
- `crew start --model small` (any name under `models.crew`, or a `claude:<model-id>`) overrides the role.

Crew sessions run in pi or Claude Code, so an OpenCode id under `models.crew` stops `crew start`.
A pi crew session loads this repo as its skill but not Claude Code's plugin hooks, so the orchestrator's edit guard does not apply to it.

## Billing halts

Any provider can answer "payment required": OpenRouter, Cerebras or Groq through OpenCode, TypeSafe, or jev's own calls.
`run` and `verify` treat it as a halt, not a failure:

- no attempt is consumed and nothing is retried;
- running tasks finish and no new task starts;
- the banner names the provider, quotes its message, and prints the top-up link; exit code 3.

After topping up, run `fast-coding resume --project <name>`.
Passed tasks keep their branches; a halted verify reruns from its first stage.
`FAST_CODING_FAKE_402=openrouter` simulates a halt for testing.
