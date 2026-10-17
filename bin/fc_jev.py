import shlex, json, os, re, signal, subprocess, time
from pathlib import Path
import fc_core, fc_config, fc_models, fc_implement


JEV_TIMEOUT = 150  # seconds one jev e2e case may run; a wandering jev used its whole 60-action budget in run 6

TOOL_ERROR_RE = re.compile(r"JEV_GAVE_UP|/jev_ultrafast/|/browser_harness/|command not found|address already in use|EADDRINUSE|"
                           r"No module named|Chromium not found|did not open the debug port", re.I)


def tool_error(output):
    """A failure the harness caused (a jev or browser crash, a missing tool, a port taken), not the app: retried once and
    never handed to a fixer, who could only 'fix' it by bending the app toward the harness."""
    return bool(TOOL_ERROR_RE.search(output or ""))

def stop_group(proc):
    """End a setup command and everything it started in its process group, even after the shell itself exited
    (its pid is the group id, so `getpgid` on a reaped leader is not needed)."""
    for sig, wait in ((signal.SIGTERM, 3), (signal.SIGKILL, 0)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):  # macOS answers EPERM for a group left with only its zombie leader
            break
        deadline = time.time() + wait
        while time.time() < deadline:
            proc.poll()  # reap the leader so the group can empty
            try:
                os.killpg(proc.pid, 0)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(0.1)
    proc.poll()

def kill_listeners(ports):
    """Kill whatever listens on these ports: servers and browsers a setup detached from its process group (`&`, `bp launch`)."""
    for port in ports:
        pids = fc_core.sh(f"lsof -ti tcp:{int(port)} -sTCP:LISTEN", ".", check=False).stdout.split()
        if pids:
            fc_core.sh(["kill", "-9", *pids], ".", check=False)

def harness_daemons(name):
    """Pids of the browser-harness daemons running under BU_NAME=`name`. A daemon carries no name on its command line, only
    in its environment, and jev never sets BU_NAME, so the daemons its runs start inherit the stage's: matching the name
    finds exactly one stage's daemons, never another project's stage or the product owner's running at the same time."""
    found = set()
    for pid in fc_core.sh("pgrep -f browser_harness.daemon", ".", check=False).stdout.split():
        try:
            env = Path(f"/proc/{pid}/environ").read_bytes().decode(errors="replace").split("\0")
        except OSError:  # macOS: `ps -E` appends the environment to the command
            env = fc_core.sh(["ps", "-Eww", "-o", "command=", "-p", pid], ".", check=False).stdout.split()
        if f"BU_NAME={name}" in env:
            found.add(pid)
    return found

def end_new_daemons(name, before):
    """restart_daemon starts a fresh browser-harness daemon and jev's own runs leave theirs: end every daemon under the
    stage's BU_NAME that was not running before the stage, never one that was (a project may share one through e2e_env)."""
    new = harness_daemons(name) - before
    if new:
        fc_core.sh(["kill", *new], ".", check=False)
    return new

def e2e_ports(cfg, env):
    """The ports an e2e stage may leave a listener on: the fresh ones it hands out, every case URL's, and the CDP port of a
    browser the setup launches (BU_CDP_URL)."""
    urls = [c.get("url", "") for c in cfg.get("e2e", [])] + [env.get("BU_CDP_URL", "")]
    return {int(env["E2E_PORT"]), int(env["E2E_CLIENT_PORT"])} | {int(m) for u in urls for m in re.findall(r"://[^/:]+:(\d+)", u)}

def expand_ports(text, env):
    return re.sub(r"\$\{?(E2E_PORT|E2E_CLIENT_PORT)\}?", lambda m: env[m.group(1)], text) if isinstance(text, str) else text

def driver_e2e(case, repo):
    """Run the project's own browser driver command, with optional setup/teardown commands (e.g. start a local server)."""
    env = {**fc_core.clean_env(), **{k: str(v) for k, v in (case.get("env") or {}).items()}}
    setup = None
    if case.get("setup"):
        setup = subprocess.Popen(case["setup"], shell=True, cwd=repo, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(case.get("setup_wait", 3))
    try:
        p = subprocess.run(case["driver"], shell=True, cwd=repo, env=env, capture_output=True, text=True,
                           timeout=case.get("timeout", 600), stdin=subprocess.DEVNULL)
        out, err, code = p.stdout, p.stderr, p.returncode
        if not code and case.get("assert"):  # the independent check runs after every case, same env and cwd as the driver
            a = subprocess.run(case["assert"], shell=True, cwd=repo, env=env, capture_output=True, text=True,
                               timeout=case.get("timeout", 600), stdin=subprocess.DEVNULL)
            out, err, code = out + a.stdout, err + a.stderr, a.returncode
    finally:
        if setup:
            stop_group(setup)
    if p.returncode and re.search(r"\b402\b|payment required|insufficient credits", p.stdout + p.stderr, re.I):
        raise fc_models.PaymentRequired("jev e2e (TypeSafe or text model)", (p.stderr or p.stdout).strip()[-300:])
    r = {"name": case.get("name"), "exit": code, "stdout": fc_core.scrub(out)[-4000:], "stderr": fc_core.scrub(err)[-2000:]}
    m = re.search(r"^E2E_RESULT (\{.*\})$", out, re.M)
    if m:
        r["run"] = json.loads(m.group(1))
    return r

def jev_e2e(case, repo):
    """Drive a real browser with jev (jev/, run in its own uv project) to a goal, then run the case's independent assert command.
    A case with a `driver` key runs that command instead (the project's own browser driver)."""
    if case.get("driver"):
        return driver_e2e(case, repo)
    script = ("import json,os,sys,subprocess\nfrom jev_ultrafast import Agent\n"
              f"with Agent({case['url']!r}, {case['goal']!r}) as a:\n"
              "    last=None\n    for s in a.run(): last=s\n"
              "    dec=last['decisions']; txt=last['text_calls']\n"
              "    tok=lambda u,*k: next((u[x] for x in k if u.get(x)), 0)\n"
              "    side=lambda calls,*k: sum(tok(c.get('usage') or {},*k) for c in calls)\n"
              "    usage={'typesafe_calls':len(dec),'typesafe_in':side(dec,'input_tokens','prompt_tokens'),'typesafe_out':side(dec,'output_tokens','completion_tokens'),"
              "'text_calls':len(txt),'text_in':side(txt,'input_tokens','prompt_tokens'),'text_out':side(txt,'output_tokens','completion_tokens')}\n"
              "    print('JEV_RESULT '+json.dumps({'status':last['status'],'elapsed_ms':last['elapsed_ms'],'steps':len(last['history']),'url':last['page']['url'],'usage':usage}))\n"
              "    sys.stdout.flush()\n"
              f"    sys.exit(subprocess.call({case['assert']!r}, shell=True, cwd={str(repo)!r}, env={{k: v for k, v in os.environ.items() if k not in {sorted(fc_core.SECRET_VARS)!r}}}))\n")
    # case["env"] (verify.json e2e_env merged with the case's env) reaches jev: set BU_CDP_URL/BU_NAME there to point
    # browser-harness at a `bp`-launched Chromium that has the extension under test loaded.
    env = {**os.environ, **{k: str(v) for k, v in (case.get("env") or {}).items()}}
    limit = int(case.get("timeout") or JEV_TIMEOUT)
    env_file = ["--env-file", str(fc_config.ENV_FILE)] if fc_config.ENV_FILE.exists() else []
    p = fc_implement.timed(shlex.join(["uv", "run", "--quiet", *env_file, "python", "-c", script]), fc_config.JEV_DIR, limit, env=env)
    r = {"name": case.get("name"), "exit": p.returncode, "stdout": p.stdout[-3000:], "stderr": p.stderr[-2000:]}
    m = re.search(r"^JEV_RESULT (\{.*\})$", p.stdout, re.M)
    if p.returncode == 124:  # killed at the limit: jev wandered or stuck, a harness failure, retried once, never fixed
        r["stderr"] = f"JEV_GAVE_UP: jev did not reach its goal within {limit}s\n" + r["stderr"]
    if m:
        r["run"] = json.loads(m.group(1))
        if r["run"].get("status") != "done":
            r["stderr"] = f"JEV_GAVE_UP: jev ended {r['run'].get('status')} after {r['run'].get('steps')} steps\n" + r["stderr"]
        u = r["run"]["usage"]
        prices = case.get("prices") or {}
        ts_cost = u["typesafe_calls"] * prices["typesafe_per_call"] if "typesafe_per_call" in prices else None
        fc_core.LEDGER.add("typesafe", u["typesafe_in"], u["typesafe_out"], ts_cost, calls=u["typesafe_calls"])
        fc_core.LEDGER.add("openrouter", u["text_in"], u["text_out"], None, calls=u["text_calls"])  # jev's text helper does not return $
    return r
