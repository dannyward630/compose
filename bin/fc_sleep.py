import re, subprocess, time
import fc_core, fc_tasks, fc_crew


SLEEP_GAP = 90  # seconds between two watch ticks that mean the Mac slept: a tick comes every 2 s, and a slow herdr call adds a few
RUN_SLACK = 900  # a run whose log was written this long before the sleep began, or later, was alive when the Mac went to sleep
RESUME_WITHIN = 900  # seconds after a wake in which a run found dead is the sleep's doing: the connections it held dropped, then it failed

def hm(t):
    return time.strftime("%H:%M:%S", time.localtime(t))

def wake_window(last, now, gap=SLEEP_GAP):
    """(start, end) of a sleep: the wall clock jumped by `gap` or more between two ticks of the watch loop, which only waits 2 s."""
    return (last, now) if last and now - last >= gap else None

def resume_command(repo, proj):
    return f"compose resume --repo {repo} --project {proj.name}"

def unsafe_to_resume(proj, marker, window):
    """Why a run found dead should not be resumed by itself, or None. Alive at the sleep, no payment halt waiting on the product owner."""
    if (proj / "results" / "resume.json").exists():
        return "the run halted on a payment limit, which is the product owner's call"
    try:
        wrote = (proj / "results" / "run.log").stat().st_mtime
    except OSError:
        return "there is no results/run.log to say when it died"
    if wrote < window[0] - RUN_SLACK:
        return f"its log was last written at {hm(wrote)}, long before the sleep: it died of something else"
    started = None
    try:
        started = time.mktime(time.strptime(marker.get("started_at"), "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        pass
    if started is None or started > window[0]:
        return "it started after the Mac went to sleep, so the sleep did not end it"
    return None

def run_after_wake(repo, proj, window, now=None):
    """The event for a run that died soon after a wake: `compose resume` started by itself when that is safe, else the exact
    command to run. Once per run (the guard file is created exclusively, so two watchers do not both resume it). A run Ctrl-C
    stopped is left alone: that was deliberate."""
    now = now or time.time()
    marker = fc_tasks.run_marker(proj)
    if not marker or not window or now - window[1] > RESUME_WITHIN or fc_tasks.run_ended(proj) != "crashed":
        return []
    guard = proj / "results" / ("sleep-" + re.sub(r"\W", "-", str(marker.get("started_at"))) + ".json")
    try:
        guard.open("x").close()
    except FileExistsError:
        return []
    cmd, slept = resume_command(repo, proj), f"the Mac slept {hm(window[0])} to {hm(window[1])}"
    if why := unsafe_to_resume(proj, marker, window):
        return [f"event sleep=run-lost {slept} and the run (started {marker.get('started_at')}) died; not resumed because {why}; resume it yourself: {cmd}"]
    subprocess.Popen([str(fc_crew.CLI_REPO / "bin" / "compose"), "resume", "--repo", str(repo), "--project", proj.name],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return [f"event sleep=resumed {slept} and the run (started {marker.get('started_at')}) died with it; `{cmd}` started by itself (log: results/resume.log)"]

def wake_events(repo, proj, woke, last, now):
    """(events, woke) for one tick of the watch loop. `woke` is the [start, end] of the last sleep this watcher saw, kept in its
    memory: a run found dead a minute after the wake is still the sleep's. The wake itself is one event naming the window."""
    window = wake_window(last, now)
    ev = [f"event sleep=woke from={hm(window[0])} to={hm(window[1])} slept={fc_core.fmt(window[1] - window[0])}  "
          f"(the Mac slept: silence is measured from the wake)"] if window else []
    woke = list(window) if window else woke
    return ev + run_after_wake(repo, proj, woke, now), woke
