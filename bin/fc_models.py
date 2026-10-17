import json, os, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path
import fc_core, fc_config, fc_claude


def opencode(cwd, model, prompt, session=None, timeout=600):
    """One OpenCode turn. Returns (session, reply_text, tool_calls, usage). Usage comes from step-finish events."""
    # --dir is required: with a git worktree, opencode otherwise resolves the project root to the main checkout and edits it.
    cmd = ["opencode", "run", "--format", "json", "--dir", str(cwd), "--model", model] + (["--session", session] if session else []) + [prompt]
    # stdin must be closed: opencode run reads a piped stdin until EOF and hangs on an open one.
    for attempt in range(4):
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        # Parallel launches race on opencode's shared SQLite file. Back off and retry; nothing has run yet when this happens.
        if p.returncode and "database is locked" in (p.stdout + p.stderr) and attempt < 3:
            time.sleep(0.7 * (attempt + 1) + 0.3 * (hash(str(cwd)) % 5) / 5)
            continue
        break
    sid, text, tools, usage, errors = session, [], 0, {"tokens_in": 0, "tokens_out": 0, "cost": 0.0}, []
    for line in p.stdout.splitlines():
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = sid or ev.get("sessionID")
        part = ev.get("part", {})
        if ev.get("type") == "error":
            err = ev.get("error") or {}
            data = err.get("data") or {}
            payment_check("cerebras/groq via OpenRouter (OpenCode)", data.get("message") or json.dumps(err), data.get("statusCode"))
            errors.append(str(data.get("message") or err.get("name") or err))
        elif ev.get("type") == "text":
            text.append(part.get("text", ""))
        elif ev.get("type") == "tool_use":
            tools += 1
        elif ev.get("type") == "step_finish":
            t = part.get("tokens", {})
            usage["tokens_in"] += t.get("input", 0) + t.get("cache", {}).get("read", 0) + t.get("cache", {}).get("write", 0)
            usage["tokens_out"] += t.get("output", 0) + t.get("reasoning", 0)
            usage["cost"] += part.get("cost") or 0.0
    if p.returncode and not sid:
        raise RuntimeError(f"opencode failed: {p.stderr[-2000:]}")
    if errors and not text and not tools:
        # The model never ran: the provider refused (bad key, payment required, model missing). Retrying is pointless.
        raise RuntimeError(f"provider refused the request: {'; '.join(errors)[-400:]}")
    if model in fc_config.PRICES:
        usage["cost"] = (usage["tokens_in"] * fc_config.PRICES[model][0] + usage["tokens_out"] * fc_config.PRICES[model][1]) / 1e6
    fc_core.LEDGER.add(model.split("/")[0], usage["tokens_in"], usage["tokens_out"], usage["cost"])
    reply = "\n".join(text)
    # A provider 429 makes opencode compact the session into a "Work State / Next Move" summary and stop.
    # That session is unusable afterwards; the caller must wait for the window to reset and start a fresh one.
    if RATE_LIMIT_MARK in reply or "Tokens per minute" in (p.stderr or ""):
        raise RateLimited(usage)
    return sid, reply, tools, usage

RATE_LIMIT_MARK = "exceeded the provider's size limit"

def pi_error(m):
    """The provider's own error text from a pi assistant message that ended with stopReason=error, else None. A missing preset
    is named with the active workspace, since the preset lives in that workspace's OpenRouter account."""
    if m.get("stopReason") != "error":
        return None
    err = str(m.get("errorMessage") or "provider error")
    try:
        meta = json.loads(err.split(": ", 1)[1])["metadata"]
    except (IndexError, KeyError, TypeError, ValueError):
        meta = {}
    if meta.get("presetErrorCode") == "preset_not_found":
        err += f" (preset '{meta.get('presetSlug')}' not found in workspace '{fc_config.WORKSPACE}')"
    return err

def pi_turn(cwd, model, prompt, session=None, timeout=None):
    timeout = timeout or TURN_TIMEOUT
    """One turn through pi (github.com/earendil-works/pi), the lean harness: ~1K tokens of fixed context per turn against
    OpenCode's ~12K. Same contract as opencode(): (session, reply_text, tool_calls, usage). The session lives outside the
    task clone so `git add -A` never commits it. Model ids are pi's `provider/model`, e.g. openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast."""
    sdir = Path(cwd).parent / (Path(cwd).name + ".pi-sessions")
    sdir.mkdir(exist_ok=True)
    import uuid
    sid = session or str(uuid.uuid4())  # --session-id must be a UUID
    env = dict(os.environ)
    if "OPENROUTER_API_KEY" not in env and fc_core.load_env(fc_config.ENV_FILE).get("TEXT_MODEL_API_KEY"):  # pi's custom providers read the key from env
        env["OPENROUTER_API_KEY"] = fc_core.load_env(fc_config.ENV_FILE)["TEXT_MODEL_API_KEY"].strip('"')
    cmd = ["pi", "-p", "--mode", "json", "--session-id", sid, "--session-dir", str(sdir), "--no-extensions", "--no-skills",
           "--no-prompt-templates", "--thinking", "low", "--model", model, *(["--api-key", fc_config.OPENROUTER_KEY] if fc_config.OPENROUTER_KEY else []), prompt]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    text, tools, usage, errors, last = [], 0, {"tokens_in": 0, "tokens_out": 0, "cost": 0.0}, [], None
    for line in p.stdout.splitlines():
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("type")
        if t == "tool_execution_start":
            tools += 1
        elif t == "message_update" and ev.get("usage"):
            last = ev["usage"]  # cumulative within the current assistant message
        elif t == "message_end" and (ev.get("message") or {}).get("role") == "assistant":
            for part in ev["message"].get("content") or []:
                if part.get("type") == "text":
                    text.append(part.get("text", ""))
            if err := pi_error(ev["message"]):
                payment_check("openrouter (pi)", err)
                errors.append(err[:400])
            if last:
                usage["tokens_in"] += last.get("input", 0) + last.get("cacheRead", 0) + last.get("cacheWrite", 0)
                usage["tokens_out"] += last.get("output", 0) + last.get("reasoning", 0)
                usage["cost"] += (last.get("cost") or {}).get("total") or 0.0
                last = None
        elif t == "error" or ev.get("error"):
            payment_check("openrouter (pi)", json.dumps(ev.get("error") or ev))
            errors.append(str(ev.get("error") or ev)[:300])
    if p.returncode and not text and not tools:
        real = [l for l in (p.stderr or "").splitlines() if l.strip() and not l.startswith("Warning:")]
        payment_check("openrouter (pi)", " ".join(real))
        raise RuntimeError(f"pi failed: {' '.join(real)[-400:] or p.stdout.strip()[-400:]}")
    if not text and not tools and not usage["tokens_in"]:
        real = [l for l in (p.stderr or "").splitlines() if l.strip() and not l.startswith("Warning:")]  # pi's session warnings are not the provider's answer
        raise RuntimeError(f"provider refused the request: {'; '.join(errors) or ' '.join(real)[-400:] or 'empty reply with no usage'}")
    if model in fc_config.PRICES:
        usage["cost"] = (usage["tokens_in"] * fc_config.PRICES[model][0] + usage["tokens_out"] * fc_config.PRICES[model][1]) / 1e6
    fc_core.LEDGER.add("openrouter" if "openrouter" in model else model.split("/")[0], usage["tokens_in"], usage["tokens_out"], usage["cost"])
    if "429" in (p.stderr or "") or any("rate" in e.lower() and "limit" in e.lower() for e in errors):
        raise RateLimited(usage)
    return sid, "\n".join(text), tools, usage

def fallback_for(model):
    """The model to switch to after a miss, or None when there is nothing to fall back to (the fallback itself, Claude, or none set)."""
    return fc_config.FALLBACK_MODEL if fc_config.FALLBACK_MODEL and model != fc_config.FALLBACK_MODEL and not fc_claude.is_claude(model) else None


class PaymentRequired(Exception):
    """A provider refused for billing reasons. Nothing retries this: the run halts, the state is saved, the user tops up, `resume` continues."""
    def __init__(self, provider, message):
        super().__init__(f"{provider}: {message}")
        self.provider, self.message = provider, message

PAY_RE = re.compile(r"payment required|insufficient[ _](credits?|quota|funds|balance)|credit balance|out of credits?|exceeded your current quota|"
                    r"billing|\b402\b|account (is )?(suspended|disabled|past due)|top up", re.I)
TOP_UP = {"openrouter": "https://openrouter.ai/settings/credits", "cerebras": "https://cloud.cerebras.ai (Billing)",
          "typesafe": "https://typesafe.ai dashboard (Billing)", "groq": "https://console.groq.com (Billing)"}

def payment_check(provider, text, status=None):
    """Raise PaymentRequired when an HTTP status or an error message says the account cannot pay."""
    if status == 402 or (text and PAY_RE.search(str(text))):
        raise PaymentRequired(provider, str(text)[:300].strip() or f"HTTP {status}")

def http_json(req, provider, timeout=90):
    """urlopen that turns a 402 (or a 200 carrying a billing error) into PaymentRequired instead of a stack trace."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        payment_check(provider, body, e.code)
        raise RuntimeError(f"{provider}: HTTP {e.code} {e.reason}: {body.strip()}") from e
    err = out.get("error") if isinstance(out, dict) else None
    if err:
        payment_check(provider, json.dumps(err), (err.get("code") if isinstance(err, dict) else None))
    return out

class RateLimited(Exception):
    def __init__(self, usage):
        super().__init__("provider rate limit hit; session compacted")
        self.usage = usage


def parse_pi_session(path, seen):
    """Read the pi session JSONL from line `seen` on: assistant text, tool calls, usage, and provider errors of the new turns.
    Same accounting as pi_turn, so the ledger and cost line do not depend on which path ran the task."""
    text, tools, usage, errors = [], 0, {"tokens_in": 0, "tokens_out": 0, "cost": 0.0}, []
    lines = Path(path).read_text().splitlines() if Path(path).exists() else []
    for ln in lines[seen:]:
        try:
            ev = json.loads(ln)
        except json.JSONDecodeError:
            continue
        m = ev.get("message") or {}
        if ev.get("type") != "message" or m.get("role") != "assistant":
            continue
        for part in m.get("content") or []:
            if part.get("type") == "text":
                text.append(part.get("text", ""))
            elif part.get("type") == "toolCall":
                tools += 1
        u = m.get("usage") or {}
        usage["tokens_in"] += u.get("input", 0) + u.get("cacheRead", 0) + u.get("cacheWrite", 0)
        usage["tokens_out"] += u.get("output", 0) + u.get("reasoning", 0)
        usage["cost"] += (u.get("cost") or {}).get("total") or 0.0
        if err := pi_error(m):
            payment_check("openrouter (pi)", err)
            errors.append(err[:400])
    return len(lines), "\n".join(text), tools, usage, errors


_PROBED = {}

def pi_id(model):
    """The --model value for a `pi:<provider/model>` id."""
    return model.split(":", 1)[1]

def pi_key_args(model):
    """pi's --api-key for the workspace's OpenRouter key, only for models routed through OpenRouter (others keep pi's own auth)."""
    return ["--api-key", fc_config.OPENROUTER_KEY] if fc_config.OPENROUTER_KEY and "openrouter" in pi_id(model) else []

def probe_command(model):
    if model.startswith("pi:"):
        return ["pi", "-p", "--mode", "json", "--no-session", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-context-files",
                "--thinking", "off", "--model", pi_id(model), *pi_key_args(model), "Reply with exactly: ok"]
    return ["claude", "-p", "--model", fc_claude.claude_id(model), "--output-format", "json", "Reply with exactly: ok"]

def probe_result(model, p):
    """(ok, why) from a finished probe process: Claude Code reports `is_error` in its JSON; pi streams events, so a clean exit
    plus an assistant text reply is ok and anything else is the error it printed."""
    if model.startswith("pi:"):
        events = []
        for line in p.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        done = [e["message"] for e in events if e.get("type") == "message_end" and (e.get("message") or {}).get("role") == "assistant"]
        failed = next(filter(None, map(pi_error, done)), None)  # a refused model still ends its turn
        replied = any(c.get("type") == "text" and c.get("text") for m in done for c in m.get("content") or [])
        if p.returncode == 0 and replied and not failed:
            return True, "answered"
        return False, (failed or p.stderr or p.stdout or f"exit {p.returncode}").strip()[:160]
    out = json.loads(p.stdout.strip()) if p.stdout.strip().startswith("{") else {}
    ok = p.returncode == 0 and out.get("is_error") is False
    return ok, "answered" if ok else (out.get("result") or p.stderr or p.stdout or f"exit {p.returncode}").strip()[:160]

def model_available(model):
    """Whether the harness named by `model` (a claude:<id> or pi:<provider/model>) can run it on this account: one tiny
    non-interactive turn, cached for the day in ~/.compose/model-probe.json. Returns (ok, why)."""
    mid, today = model.split(":", 1)[1] if ":" in model else "", time.strftime("%Y-%m-%d")
    if not mid:
        return True, "Claude Code's default model"
    if mid in _PROBED:
        return _PROBED[mid]
    try:
        cache = json.loads(fc_config.PROBE_CACHE.read_text()) if fc_config.PROBE_CACHE.exists() else {}
    except (OSError, json.JSONDecodeError):
        cache = {}
    hit = cache.get(mid)
    if hit and hit.get("date") == today:
        _PROBED[mid] = (hit["ok"], hit["why"])
        return _PROBED[mid]
    ok, why, transient = probe_once(model, 60)
    if transient:  # a slow start-up or a busy API says nothing about the account: retry once, longer, and never cache it
        ok, why, transient = probe_once(model, 180)
    _PROBED[mid] = (ok, why)
    if not transient:
        cache[mid] = {"date": today, "ok": ok, "why": why}
        fc_config.PROBE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        fc_core.atomic_write(fc_config.PROBE_CACHE, json.dumps(cache, indent=2))
    return ok, why

TRANSIENT = re.compile(r"overloaded|rate.?limit|too many requests|\b(5\d\d|429)\b|timed? ?out|temporar|try again|unavailable|connection|ECONN", re.I)

def probe_once(model, timeout):
    """(ok, why, transient) from one probe turn. Only a clear answer (ok, or a refusal such as an unknown model) is definite."""
    try:
        p = subprocess.run(probe_command(model), capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=fc_claude.headless_env())
        ok, why = probe_result(model, p)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return False, f"{type(e).__name__}: {e}"[:160], True
    return ok, why, not ok and bool(TRANSIENT.search(why))

def probe_clear():
    """Forget the day's cached probe results so the next pick asks again."""
    fc_config.PROBE_CACHE.unlink(missing_ok=True)
    _PROBED.clear()

def cmd_models(a):
    """`models --probe`: clear the cached probe results and re-probe every model the crew chains name."""
    if not a.probe:
        sys.exit("models --probe clears the day's cached model probes and probes the crew models again")
    probe_clear()
    for model in dict.fromkeys(m for chain in [[(m, None)] for m in fc_config.CREW_MODELS.values()] + list(fc_config.CREW_FALLBACK.values()) for m, _ in chain):
        if fc_claude.is_claude(model) or str(model).startswith("pi:"):
            ok, why = model_available(model)
            print(f"{model}: {'ok' if ok else 'unavailable'} ({why})")


TEST_TIMEOUT = 120  # seconds a task's test may run before it counts as hung; a task's block can set `test_timeout:`
TURN_TIMEOUT = 180  # seconds one implementer turn may take on its own; GLM turns take 10 to 40 s, a hang used to cost 300 s an attempt

def turn_timeout(meta):
    """A turn's wall-time limit: the turn itself plus one run of the task's test, which the implementer runs inside the turn."""
    return TURN_TIMEOUT + int(meta.get("test_timeout") or TEST_TIMEOUT)


def payment_halt(repo, proj, command, remaining, args, err):
    """Save what is left to do, tell the user where to top up, exit 3. `compose resume` picks it up."""
    state = {"command": command, "remaining": remaining, "args": args, "provider": err.provider, "message": err.message,
             "halted_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (proj / "results").mkdir(exist_ok=True)
    fc_core.atomic_write((proj / "results" / "resume.json"), json.dumps(state, indent=2))
    (proj / "results" / "run.json").unlink(missing_ok=True)
    key = next((k for k in TOP_UP if k in err.provider.lower()), None)
    print()
    print(f"PAYMENT REQUIRED  provider: {err.provider}")
    print(f"  {err.message}")
    if key:
        print(f"  top up at: {TOP_UP[key]}")
    if command == "run":
        print(f"  stopped with {len(remaining)} task(s) left: {', '.join(remaining)}. Passed tasks keep their branches.")
    else:
        print("  stopped during verify; task branches are untouched.")
    print(f"  then continue where it stopped:  compose resume --repo {repo} --project {proj.name}")
    sys.exit(3)


def lenient_json(content):
    content = content.strip()
    content = content[content.index("{"):] if "{" in content else content
    try:
        return json.JSONDecoder().raw_decode(content)[0]  # first object; small models append prose
    except json.JSONDecodeError:
        # Common small-model slip: single-quoted JSON.
        return json.JSONDecoder().raw_decode(re.sub(r"(?<![\\\\])'", '"', content))[0]

def fast_env():
    """The env a fast-model call reads: ~/.compose/.env, overridden by the process env (the workspace key)."""
    return {**fc_core.load_env(fc_config.ENV_FILE), **os.environ}

def fast_json(env, system, user, max_tokens=1500, timeout=90):
    """One call to the fast text model in ~/.compose/.env (Mercury 2.5 by default) through OpenRouter. Cost is exact."""
    body = {"model": env.get("TEXT_MODEL", "inception/mercury-2.5"), "max_tokens": max_tokens,
            "response_format": {"type": "json_object"}, "reasoning": {"enabled": False}, "usage": {"include": True},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    req = urllib.request.Request(env.get("TEXT_MODEL_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {env['TEXT_MODEL_API_KEY']}", "Content-Type": "application/json"})
    out = http_json(req, "openrouter (Mercury review)", timeout=timeout)
    u = out.get("usage", {})
    fc_core.LEDGER.add("openrouter", u.get("prompt_tokens", 0), u.get("completion_tokens", 0), u.get("cost"))
    content = ((out.get("choices") or [{}])[0].get("message") or {}).get("content")
    if not content or not str(content).strip():
        raise EmptyReply("model returned an empty reply")
    return lenient_json(str(content))

class EmptyReply(Exception):
    pass

class ConfirmError(Exception):
    pass

def confirm_call(env, system, user, max_tokens=500):
    """The confirm step shared by figma judge, review, and jev acceptance: returns (confirmed, evidence). The model sometimes
    wraps the object in a list, so a one-element list is unwrapped; any other shape is retried once with a stricter instruction,
    then raises ConfirmError, which the caller records as a judge error and never as a verdict."""
    strict = system + ' Reply with exactly one JSON object {"confirmed": bool, "evidence": str} and nothing else: no list, no prose.'
    for attempt, sysmsg in enumerate((system, strict)):
        try:
            v = fast_json(env, sysmsg, user, max_tokens=max_tokens)
        except (ValueError, EmptyReply) as e:
            if attempt:
                raise ConfirmError(f"confirm call failed: {e}")
            continue
        if isinstance(v, list) and len(v) == 1:
            v = v[0]
        if isinstance(v, dict) and "confirmed" in v:
            return bool(v["confirmed"]), str(v.get("evidence", ""))[:300]
    raise ConfirmError("confirm call failed: reply was not a {confirmed, evidence} object")


def jev_ask(env, cfg, state, questions, label):
    """One TypeSafe (Jev) request: choice questions against one state, on the cost ledger. Returns Jev's whole reply."""
    req = urllib.request.Request("https://api.typesafe.ai/v1/systemone",
                                 data=json.dumps({"model": env.get("TYPESAFE_MODEL", "jev-latest"), "state": state,
                                                  "questions": questions}).encode(),
                                 headers={"Authorization": f"Bearer {env['TYPESAFE_API_KEY']}", "Content-Type": "application/json"})
    out = http_json(req, f"typesafe ({label})")
    u = out.get("usage", {}) or {}
    price = (cfg.get("prices") or {}).get("typesafe_per_call")
    fc_core.LEDGER.add("typesafe", u.get("input_tokens") or u.get("prompt_tokens") or u.get("total_tokens") or 0, u.get("output_tokens") or 0,
               price if price is not None else None)
    return out

def reask_criterion(env, cfg, state, choices, rules, row, label):
    """The one re-ask both judges share: an UNCLEAR verdict, or a NOT_MET the confirm call refuted (confirmed=false, not a
    judge error), is put to Jev once more for that criterion alone, with the confirmer's evidence as context. Only a MET reply
    turns the row MET; both verdicts stay on the row. Anything else, and every judge error, is left as it was and still blocks."""
    refuted = row["choice"] == "NOT_MET" and row.get("confirmed") is False and not row.get("judge_error")
    if row["choice"] != "UNCLEAR" and not refuted:
        return row
    instructions = {"criterion": row["criterion"], "task": row["task"], "rules": rules}
    if refuted:
        instructions["context"] = f"An independent check was asked to show this criterion is violated and could not: {row.get('evidence', '')}"
    out = jev_ask(env, cfg, state, {"c0": {"type": "choice", "criteria": choices, "instructions": instructions}}, label + " re-ask")
    ans = (out.get("answers") or {}).get("c0") or {}
    probs = ans.get("probabilities") or {}
    row["first_choice"] = row["choice"]
    row["reask"] = {"choice": ans.get("choice"), "p_met": round(probs.get("MET", 0), 3), "p_not_met": round(probs.get("NOT_MET", 0), 3)}
    if ans.get("choice") == "MET":
        row["choice"] = "MET"
    return row
