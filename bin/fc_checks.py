"""Read-only machine checks the setup steps table and doctor use. No network, no writes."""
import datetime, os, re, shutil, subprocess
from pathlib import Path
import platform
import fc_core


def owned_links(checkout):
    """[(name, link, target)] for the three links compose owns: compose CLI link, compose skill link, bp link."""
    checkout, home = Path(checkout), Path.home()
    return [("compose CLI link", home / ".local/bin/compose", checkout / "bin/compose"),
            ("compose skill link", home / ".claude/skills/compose", checkout),
            ("bp link", home / ".local/bin/bp", checkout / "bp/bin/bp.mjs")]

def command_copies(key, checkout):
    raise NotImplementedError

def commands_ok(key, checkout):
    raise NotImplementedError

def hooks_ok(key, checkout):
    raise NotImplementedError

def link_state(path):
    """("ok", target) when path resolves to something that exists, ("dangling", raw link text), or ("missing", None)."""
    path = Path(path)
    if path.exists():
        return ("ok", str(path.resolve()))
    if path.is_symlink():
        return ("dangling", os.readlink(path))
    return ("missing", None)

def local_bin_on_path():
    """True when ~/.local/bin is one of the PATH entries."""
    return str(Path.home() / ".local/bin") in os.environ.get("PATH", "").split(os.pathsep)

def gh_authed():
    """True when `gh auth status` exits 0; False when it does not, hangs past 20 s, or gh is absent."""
    try:
        return fc_core.sh(["gh", "auth", "status"], Path.home(), check=False, timeout=20).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

def rerere_set():
    """True when `git config --global --get rerere.enabled` prints true."""
    try:
        return fc_core.sh(["git", "config", "--global", "--get", "rerere.enabled"], Path.home(), check=False).stdout.strip() == "true"
    except FileNotFoundError:
        return False

def jev_synced(checkout):
    """True when <checkout>/jev/.venv exists."""
    return (Path(checkout) / "jev/.venv").exists()

def chromium_installed():
    """True when the newest Playwright chromium-<n> has its Chrome for Testing binary (as bp/bin/bp.mjs:11-12 finds it)."""
    cache = Path.home() / "Library/Caches/ms-playwright"
    versions = sorted((d for d in os.listdir(cache) if re.fullmatch(r"chromium-\d+", d)), key=lambda d: -int(d[9:])) if cache.is_dir() else []
    if not versions:
        return False
    arch = "arm64" if platform.machine() == "arm64" else "x64"
    return (cache / versions[0] / f"chrome-mac-{arch}/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing").exists()

LOAD_FACTOR = 2  # the 5-minute load average that is "far above" the core count: this many times it
CRASH_RESTARTS, CRASH_WINDOW = 3, 120  # a container restarted this many times, the last one under this many seconds ago, is in a crash loop

def battery_report():
    """What `pmset -g batt` prints; empty off macOS, without pmset, and when it does not answer within 10 s."""
    if not shutil.which("pmset"):
        return ""
    try:
        return fc_core.sh(["pmset", "-g", "batt"], None, timeout=10, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""

def on_battery():
    """True when `pmset -g batt` says the Mac runs on its battery; False on AC power, off macOS, and without pmset."""
    return "Battery Power" in battery_report()

LOW_BATTERY = 30  # percent: on battery below this, run, resume, verify and crew start refuse without --force

def battery_stop(force=False):
    """The line that stops a start while the Mac runs on its battery below LOW_BATTERY percent, with why and how to override;
    None on AC power, at or above it, when the charge cannot be read, with `force`, and under COMPOSE_NO_PREFLIGHT=1."""
    if force or os.environ.get("COMPOSE_NO_PREFLIGHT"):
        return None
    out = battery_report()
    if "Battery Power" not in out or not (m := re.search(r"(\d+)%", out)) or int(m[1]) >= LOW_BATTERY:
        return None
    return (f"the Mac is on battery at {m[1]}%, below {LOW_BATTERY}%: it can die or sleep in the middle of the work; plug it in, "
            "or run again with --force to start anyway")

def busiest_process():
    """(cpu percent, command name) of the process using the most CPU right now, else None."""
    try:
        out = fc_core.sh(["ps", "-Ao", "pcpu=,comm=", *(["-r"] if platform.system() == "Darwin" else ["--sort=-pcpu"])], None, timeout=10, check=False).stdout
        cpu, _, comm = out.strip().splitlines()[0].strip().partition(" ")
        return float(cpu), comm.strip().rsplit("/", 1)[-1]
    except (OSError, subprocess.TimeoutExpired, IndexError, ValueError):
        return None

def restarting_containers():
    """Names of the docker containers stuck in a crash loop (restarting now, or restarted CRASH_RESTARTS times and started under
    CRASH_WINDOW seconds ago). Empty when docker is not installed, not running, or does not answer within 10 s: never an error."""
    if not shutil.which("docker"):
        return []
    try:
        ids = fc_core.sh(["docker", "ps", "-q", "--filter", "status=running", "--filter", "status=restarting"], None, timeout=10, check=False)
        if ids.returncode or not ids.stdout.split():
            return []
        rows = fc_core.sh(["docker", "inspect", "--format", "{{.Name}}|{{.State.Status}}|{{.RestartCount}}|{{.State.StartedAt}}", *ids.stdout.split()],
                          None, timeout=10, check=False).stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return []
    now, looping = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), []
    for row in rows:
        name, _, rest = row.partition("|")
        status, restarts, started = (rest.split("|") + ["", "0", ""])[:3]
        try:
            age = (now - datetime.datetime.strptime(started[:19], "%Y-%m-%dT%H:%M:%S")).total_seconds()
            recent = int(restarts) >= CRASH_RESTARTS and age < CRASH_WINDOW
        except ValueError:
            recent = False
        if status == "restarting" or recent:
            looping.append(name.lstrip("/"))
    return looping

def machine_warnings():
    """One WARNING line per thing that makes long work lie or stop, each with the fix: a Mac on battery (closing the lid sleeps
    it, which caffeinate cannot prevent), a 5-minute load average above LOAD_FACTOR times the cores (naming the busiest process),
    and docker containers in a crash loop (they burn the CPU a verify's timings and e2e cases need). Read-only; never raises."""
    out = []
    if on_battery():
        out.append("WARNING: the Mac is on battery: closing the lid will sleep it and stop the work, which keeping it awake cannot prevent; plug it in or leave the lid open")
    cores = os.cpu_count() or 1
    try:
        load = os.getloadavg()[1]
    except OSError:
        load = 0
    if load > LOAD_FACTOR * cores:
        top = busiest_process()
        out.append(f"WARNING: load average {load:.0f} on {cores} cores: checks and e2e run slow and time out"
                   + (f"; busiest process is {top[1]} at {top[0]:.0f}% CPU, stop it or wait" if top else ""))
    for name in restarting_containers():
        out.append(f"WARNING: docker container {name} keeps restarting and burns CPU, so a verify measures the machine, not the code: docker stop {name}")
    return out
