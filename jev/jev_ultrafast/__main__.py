"""Run one goal to its end: `python -m jev_ultrafast <url> <goal> [<goal> ...] [--secrets JSON] [--record DIR] [--progress]
[--hold]`.

verify's e2e cases and `bp goal` both run jev this way. The last line printed is always `JEV_RESULT {json}`: status (done,
blocked, or error), stop_reason, elapsed_ms, steps, url, usage, and a compact history of what jev did (step, kind, label,
page_changed). A budget or a crash still ends with that line, so the caller always learns why a run stopped. The exit code
is 0 only when the goal is done.

--secrets maps field labels to env vars ({"Password": "$E2E_PASSWORD"}): the values are read here, from the environment, so
they never sit on a command line, and jev types them itself, so they never reach a model or the history.

--hold keeps the run's tab open after JEV_RESULT, a crashed run's too, until stdin closes: verify's assert reads that tab.
"""

import argparse
import json
import os
import re
import sys
import traceback

from . import Agent


def secret_values(spec, env):
    """{label: value} for {label: "$VAR"}; a literal value or an unset variable is refused, before any browser starts."""
    values = {}
    for label, ref in spec.items():
        m = re.fullmatch(r"\$\{?(\w+)\}?", str(ref))
        if not m:
            raise ValueError(f'secret {label!r} must name an env var, like "$E2E_PASSWORD", never hold the value')
        if not env.get(m.group(1)):
            raise ValueError(f"secret {label!r}: ${m.group(1)} is not set")
        values[label] = env[m.group(1)]
    return values


def usage(state):
    """Calls and tokens per side: TypeSafe's decisions and the text helper's field values."""
    tok = lambda u, *keys: next((u[k] for k in keys if u.get(k)), 0)
    side = lambda calls, *keys: sum(tok(c.get("usage") or {}, *keys) for c in calls)
    dec, txt = state.get("decisions", []), state.get("text_calls", [])
    return {"typesafe_calls": len(dec), "typesafe_in": side(dec, "input_tokens", "prompt_tokens"),
            "typesafe_out": side(dec, "output_tokens", "completion_tokens"), "text_calls": len(txt),
            "text_in": side(txt, "input_tokens", "prompt_tokens"), "text_out": side(txt, "output_tokens", "completion_tokens")}


def result(state, url, error=None):
    """The JEV_RESULT of a run that ended in `state` (None when it never started), or crashed with `error`."""
    state = state or {}
    history = state.get("history", [])
    status = state.get("status") if state.get("status") in {"done", "blocked"} and not error else "error"
    return {
        "status": status,
        "stop_reason": error or state.get("stop_reason"),
        "elapsed_ms": state.get("elapsed_ms", 0),
        "steps": len(history),
        "url": (state.get("page") or {}).get("url", url),
        "usage": usage(state),
        "history": [{"step": h["step"], "kind": h["kind"], "label": h["action"][:80], "page_changed": h.get("page_changed")}
                    for h in history],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m jev_ultrafast", description=__doc__.split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("goals", nargs="+")
    ap.add_argument("--secrets", default="{}", help='JSON {"field label": "$ENV_VAR"}')
    ap.add_argument("--record", help="keep a screenshot of every step in this directory")
    ap.add_argument("--progress", action="store_true", help="print one line per step")
    ap.add_argument("--hold", action="store_true", help="keep the tab open after JEV_RESULT until stdin closes")
    a = ap.parse_args(argv)
    agent, r = None, None

    def failed(e):  # a budget ends the run blocked; anything raised is the harness's failure, said and summed up
        traceback.print_exc()
        return f"{type(e).__name__}: {e}"

    def finish(error=None):
        r = result(agent.snapshot() if agent else None, a.url, error)
        if a.progress and r["status"] != "done":
            print(f"{r['status']}: {r['stop_reason']}", flush=True)
        print("JEV_RESULT " + json.dumps(r), flush=True)
        return r

    try:
        secrets = secret_values(json.loads(a.secrets), os.environ)
        agent = Agent(a.url, a.goals, record_dir=a.record, secrets=secrets)
        with agent:
            error = None
            try:
                for s in agent.run():
                    if a.progress:
                        h = s["history"][-1] if s["history"] else None
                        print(f"{s['elapsed_ms']:>5} ms  {len(s['history'])} actions  {s['status']}"
                              + (f"  {h['kind']} {h['action'][:60]}" if h else ""), flush=True)
            except Exception as e:
                error = failed(e)
            r = finish(error)
            if a.hold:
                sys.stdin.read()
    except Exception as e:
        error = failed(e)
        r = r or finish(error)
    return 0 if r["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
