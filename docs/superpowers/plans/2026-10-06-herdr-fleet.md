# herdr fleet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inside herdr, every fast-coding project is a space, every task a tab with a named interactive pi agent the orchestrator can steer, and verify a tab of stage panes.

**Architecture:** One `herdr()` subprocess helper in `bin/fast-coding`. A fourth implementer backend `herdr_pi()` behind the existing `implementer()` seam, selected when `HERDR_ENV=1` and the model is `pi:`. Usage, reply text, and errors are parsed from pi's session JSONL instead of `pi -p` stdout. Topology helpers (`herdr_space`, `herdr_status_tab`, `herdr_verify_panes`) are called from `init`, `run_tasks`, `verify`, and `clean`. Everything is best-effort and silent outside herdr.

**Tech Stack:** Python 3 stdlib, herdr CLI 0.9.x, pi with the herdr extension, unittest.

**Spec:** `docs/superpowers/specs/2026-10-06-herdr-fleet-design.md`

## Global Constraints

- Agent names match `[a-z][a-z0-9_-]{0,31}` and are unique among live agents.
- The headless pi, OpenCode, and Claude paths are byte-for-byte unchanged outside herdr.
- No new dependencies. Tests run with `python3 -m unittest discover -s tests`.
- Never focus a pane, tab, or space the user did not ask to see: every create uses `--no-focus`.
- Herdr failures never fail a run: `herdr()` returns `None` on error unless `check=True`.

## Review Focus

1. A task re-run while its agent from the previous run is still alive: `agent start` would fail with a duplicate name. `herdr_pi` closes the old tab first. Tested in `test_agent_name_and_reuse`.
2. `agent prompt --wait` timing out while pi keeps working: the backend sends `esc`, closes the tab, and raises `subprocess.TimeoutExpired` so `run_task` takes its existing fresh-session path.
3. A pi turn that ends with `stopReason: error` (provider refusal, 402): parsed from the session file and passed through `payment_check`, so a billing stop still halts the run. Tested in `test_parse_pi_session_error`.
4. Multi-line prompts of several KB pasted through `agent prompt`: verified live in Task 6 with a real context pack.
5. The repo not being open as a herdr space, so `worktree open --cwd` has no group: fall back to `workspace create --cwd <wt> --label <slug>`.

---

### Task 1: herdr helper and agent naming

**Files:**
- Modify: `bin/fast-coding` (new section `# ---------- herdr ----------` after `claude_once`)
- Create: `tests/test_herdr.py`, `tests/__init__.py`

**Interfaces:**
- Produces: `HERDR: bool`, `herdr(*args, check=False, timeout=120) -> dict|None` (the `result` object), `agent_name(slug, tid) -> str`.

- [ ] Write `tests/test_herdr.py` with a loader that imports `bin/fast-coding` via `importlib.machinery.SourceFileLoader`, and:

```python
def test_agent_name(self):
    self.assertEqual(fc.agent_name("custom-dropdowns", "001"), "custom-dropdowns-001")
    self.assertEqual(fc.agent_name("Workday Login!", "012"), "workday-login-012")
    long = fc.agent_name("a" * 40, "003")
    self.assertEqual(len(long), 32); self.assertTrue(long.endswith("-003"))
    self.assertTrue(fc.agent_name("9lives", "001").startswith("fc-9lives"))
def test_herdr_noop_outside(self):
    with mock.patch.dict(os.environ, {"HERDR_ENV": ""}):
        self.assertIsNone(fc.herdr("agent", "list"))
```

- [ ] Run `python3 -m unittest discover -s tests -v`; expect AttributeError.
- [ ] Implement:

```python
def herdr_env():
    return os.environ.get("HERDR_ENV") == "1" and bool(os.environ.get("HERDR_SOCKET_PATH"))

def herdr(*args, check=False, timeout=120):
    """One herdr CLI call. Returns the JSON `result`, or None when not inside herdr or the call failed (unless check)."""
    if not herdr_env():
        return None
    try:
        p = subprocess.run(["herdr", *map(str, args)], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        if check: raise RuntimeError(f"herdr {' '.join(map(str, args[:2]))}: {e}")
        return None
    try:
        out = json.loads((p.stdout or p.stderr or "{}").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        out = {}
    if p.returncode or "error" in out:
        if check: raise RuntimeError(f"herdr {' '.join(map(str, args[:2]))}: {(out.get('error') or {}).get('code') or p.stderr.strip()[-200:]}")
        return None
    return out.get("result", out)

def agent_name(slug, tid):
    s = re.sub(r"[^a-z0-9_-]+", "-", slug.lower()).strip("-")
    if not re.match(r"[a-z]", s): s = "fc-" + s
    return f"{s[:32 - len(tid) - 1]}-{tid}"
```

- [ ] Run tests; expect pass. Commit `herdr: cli helper and agent naming`.

### Task 2: parse a pi session file

**Files:** `bin/fast-coding`, `tests/test_herdr.py`

**Interfaces:**
- Produces: `parse_pi_session(path, seen) -> (seen, text, tools, usage, errors)`; `usage` has `tokens_in`, `tokens_out`, `cost`.

- [ ] Test with three JSONL lines (an assistant message with one `toolCall` and usage `{"input":100,"output":10,"cacheRead":5,"cacheWrite":0,"reasoning":2,"cost":{"total":0.01}}`, an assistant text message, and an assistant message with `stopReason: "error", errorMessage: "402 Payment Required"`): first call from `seen=0` returns tools 1, tokens_in 105, tokens_out 12, cost 0.01, text joined; second call from the returned `seen` returns nothing new; the error line raises `PaymentRequired` through `payment_check("openrouter (pi)", ...)`.
- [ ] Run; expect failure. Implement by reading the file, skipping `seen` lines, and applying the same accounting as `pi_turn` (`message.role == "assistant"`: text parts, `toolCall` parts counted, `usage` added; `stopReason == "error"`: `payment_check` then append `errorMessage`). Return the new line count as `seen`.
- [ ] Run; pass. Commit `herdr: parse pi session turns`.

### Task 3: topology helpers

**Files:** `bin/fast-coding`

**Interfaces:**
- Produces: `herdr_space(wt, slug) -> workspace_id|None` (cached in `HERDR_SPACES`), `herdr_status_tab(space, slug)`, `herdr_find_space(wt) -> id|None`.

- [ ] `herdr_space`: `herdr("worktree", "open", "--cwd", <main repo of wt>, "--path", wt, "--label", slug, "--no-focus")`; read `result.workspace.workspace_id`; on `None`, `herdr_find_space(wt)` (match `worktree list` entries by path, then `workspace list` by label), then `workspace create --cwd wt --label slug --no-focus`. Cache.
- [ ] `herdr_status_tab`: skip if `tab list --workspace space` has a tab labelled `status`; else `tab create --workspace space --label status --cwd wt --no-focus` then `pane run <root_pane> "<sys.argv[0]> status --repo <wt> --project <slug> --watch"`.
- [ ] Call both from `cmd_init` (after the commit) and from `run_tasks` (before `run start`). Manual check in Task 6. Commit `herdr: project space and status tab`.

### Task 4: the herdr_pi backend

**Files:** `bin/fast-coding` (`implementer`, new `herdr_pi`, `run_task` progress hook)

**Interfaces:**
- `implementer(cwd, model, prompt, session=None, task=None)`; `task = {"proj": Path, "meta": dict, "space": str}`; routes to `herdr_pi` when `herdr_env() and task and task["space"] and model.startswith("pi:")`.
- `herdr_pi(cwd, model, prompt, session, task) -> (session, text, tools, usage)`; `session = {"name","pane","tab","sfile","seen"}`.

- [ ] Start path (session is None): close a live agent of the same name (`agent get name` → its `tab_id` → `tab close`); `tab create --workspace space --label "NNN title" --cwd cwd --env OPENROUTER_API_KEY=<key> --no-focus`; `agent start name --kind pi --pane <root> --timeout 60000 -- --tui-mode regular --no-extensions -e ~/.pi/agent/extensions/herdr-agent-state.ts --no-skills --no-prompt-templates --thinking low --session-id <uuid> --session-dir <cwd>.pi-sessions --model <model>` with `check=True`; `sfile` from `result.agent.agent_session.value`; `pane report-metadata <pane> --source fast-coding --title "NNN title" --token model=<short model>`.
- [ ] Prompt path: `agent prompt name <prompt> --wait --timeout 300000`. Error `timeout` → `agent send-keys name esc`, `tab close`, raise `subprocess.TimeoutExpired("herdr agent prompt", 300)`. Error `agent_blocked` → `send-keys esc`, retry once. Then `parse_pi_session(sfile, seen)`; `LEDGER.add` and `PRICES` exactly like `pi_turn`; raise `RuntimeError` when no text, tools, or tokens; return.
- [ ] In `run_task`: pass `task={"proj": proj, "meta": meta, "space": HERDR_SPACES.get(proj.name)}`; after each attempt call `herdr_label(session, f"attempt {attempt}/{attempts}", cost)` which does `pane report-metadata --state-label working=... --token cost=$x`; at the end `herdr_label(session, status, cost)` with `--state-label idle="<status>"`.
- [ ] Unit test `test_implementer_routes_headless_outside_herdr` (mock `pi_turn`, env without HERDR) stays green. Commit `herdr: pi implementers run as named herdr agents`.

### Task 5: verify panes and clean

**Files:** `bin/fast-coding` (`run_stages`, `cmd_verify`, `clean_project`)

- [ ] `herdr_verify_panes(space, wt, names)`: `tab create --label "verify HH:MM"`, root pane is `names[0]`, `pane split <prev> --direction down --no-focus` for the rest; `pane report-agent <pane> --source fast-coding --agent <name> --state idle --message pending` each; returns `{name: pane}`.
- [ ] In `run_stages`, around each stage (`checks`, each e2e case by name, `review`, `jev`): `pane report-agent --state working`, then `--state idle --message ok` or `--message FAIL`. Only when the dict is non-empty.
- [ ] In `clean_project`, when the project worktree is removed: `herdr_find_space(wt)` → `workspace close <id>`.
- [ ] Commit `herdr: verify stage panes, clean closes the space`.

### Task 6: live end-to-end in this herdr session

- [ ] Scratch repo `/tmp/fc-herdr-demo` with a tiny node module and one failing `node --test` test; `fast-coding init --project demo-greeting`; confirm a `demo-greeting` space with a `status` tab appears in `herdr workspace list` / `tab list`.
- [ ] One task file with a real goal; `fast-coding run --project demo-greeting`; confirm a tab `001 ...` with agent `demo-greeting-001` in `herdr agent list`, state labels change, the task passes, cost is non-zero in the result and the ledger line.
- [ ] Steer: while a second deliberately vague task runs, `herdr agent prompt demo-greeting-002 "..."` from this pane and confirm pi takes it.
- [ ] `fast-coding verify` with `review: false`, one check; confirm the `verify` tab and its stage panes.
- [ ] `fast-coding clean --delete-unmerged`; confirm the space is gone. Remove the scratch repo.

### Task 7: skill and README

**Files:** `SKILL.md`, `README.md`

- [ ] SKILL.md step 0: herdr detection line (`HERDR_ENV=1`, invoke the `herdr` skill, `herdr agent rename $HERDR_PANE_ID <slug>-orchestrator` and `pane rename` to `<slug> orchestrator`); step 4: run in the background and steer (watch `herdr agent list`, read a blocked or stalled agent, `agent prompt` one specific instruction, log it as a comment on the task's Linear issue); roles table: orchestrator steers, never types; firstmate rules: status is a wake event, read one-line state, final message stands alone.
- [ ] README: a "In herdr" section with the topology table from the spec.
- [ ] Commit `docs: herdr fleet in the skill and README`.
