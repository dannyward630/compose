"""The compose version a project runs on: the CLI commit and each skill file's hash, pinned when the project starts (init, the first
crew start, run, verify) and renewed only by `compose update` between phases. Low in the rank so every starter can pin without
reaching up to fc_update."""
import hashlib, json, time
from pathlib import Path
import fc_core, fc_config, fc_hooks


def pins_dir():
    return fc_config.CONFIG_PATH.parent / "pins"

def cli_commit():
    return fc_core.sh(["git", "rev-parse", "--short", "HEAD"], Path(__file__).resolve().parents[1], check=False).stdout.strip() or "unknown"

def pin_file(proj):
    proj = Path(proj).resolve()
    return pins_dir() / f"{proj.name}-{hashlib.sha1(str(proj).encode()).hexdigest()[:8]}.json"

def pin(proj, repo=None, renew=False):
    """Record the compose version `proj` runs on: the CLI commit and each skill file's hash, when the project starts (init, the first
    crew start, run, verify). A pin already there stays, so a project keeps the version it began with until `update` renews it."""
    proj = Path(proj).resolve()
    f = pin_file(proj)
    if f.exists() and not renew:
        try:
            return json.loads(f.read_text())
        except (OSError, ValueError):
            pass
    try:
        skill = fc_hooks.skill_hashes()
    except (FileNotFoundError, OSError):
        skill = {}
    d = {"project": proj.name, "proj": str(proj), "repo": str(Path(repo).resolve()) if repo else str(proj.parents[1]),
         "commit": cli_commit(), "at": time.strftime("%Y-%m-%d %H:%M:%S"), "skill": skill}
    f.parent.mkdir(parents=True, exist_ok=True)
    fc_core.atomic_write(f, json.dumps(d))
    return d

def pinned():
    """Every pinned project whose directory still exists; the pin of a cleaned project is removed."""
    found = []
    for f in sorted(pins_dir().glob("*.json")) if pins_dir().exists() else []:
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            f.unlink(missing_ok=True)
            continue
        if isinstance(d, dict) and d.get("proj") and Path(d["proj"]).exists():
            found.append(d)
        else:
            f.unlink(missing_ok=True)
    return found

def skill_name(path):
    """A skill file as the team lead knows it: `sections/0b.md`, `SKILL.md`."""
    try:
        return str(Path(path).relative_to(fc_hooks.SKILL_DIR.resolve()))
    except ValueError:
        return Path(path).name
