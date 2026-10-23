"""Run compose's test suite in parallel: `python3 -m tests.run [-j N] [test_x.py ...]`.

Each tests/test_*.py runs as `python3 -m unittest discover -s tests -p <file>` in a process of its own, N at a time
(-j, else COMPOSE_TEST_JOBS, else a quarter of the cores), the biggest files first. It prints one line per finished file, then
unittest's own failure blocks and its summary for the whole run (`Ran N tests in Ts`, `OK` or `FAILED (failures=, errors=)`), on
stderr like unittest, so the FAIL:/ERROR: lines are the ones fc_gate.FAILING_RE reads. A file whose process dies or prints no
summary is one error named after it. It exits 1 on any failure. `python3 -m unittest discover -s tests` still runs the same
tests, serially."""
import argparse, os, re, signal, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
RAN_RE = re.compile(r"^Ran (\d+) tests? in [\d.]+s$", re.M)
RESULT_RE = re.compile(r"^(?:OK|FAILED)(?: \((.*)\))?$", re.M)
BLOCKS_RE = re.compile(r"^={70}$.*?(?=^-{70}\nRan \d+ tests? in )", re.M | re.S)
COUNTS = ("failures", "errors", "skipped", "expected failures", "unexpected successes")
LIVE = set()


def run_file(path):
    """(file name, tests run, counts by kind, failure blocks, seconds) of one test file run on its own."""
    t0 = time.time()
    p = subprocess.Popen([sys.executable, "-m", "unittest", "discover", "-s", str(TESTS), "-p", path.name], cwd=ROOT, text=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    LIVE.add(p)
    out = p.communicate()[0]
    LIVE.discard(p)
    ran, result = RAN_RE.search(out), list(RESULT_RE.finditer(out))
    counts = {k: int(v) for k, v in re.findall(r"([a-z]+(?: [a-z]+)?)=(\d+)", result[-1].group(1) or "")} if result else {}
    blocks = BLOCKS_RE.search(out)
    text = blocks.group(0) if blocks else ""
    if not ran or not result or (p.returncode and not counts.get("failures") and not counts.get("errors")):
        counts["errors"] = counts.get("errors", 0) + 1
        text += f"\nERROR: {path.name} (exit {p.returncode}, no result)\n" + "\n".join(out.splitlines()[-30:])
    return path.name, int(ran.group(1)) if ran else 0, counts, text, time.time() - t0


def default_jobs():
    """COMPOSE_TEST_JOBS, else a quarter of the cores (at least 1)."""
    return max(1, int(os.environ.get("COMPOSE_TEST_JOBS") or (os.cpu_count() or 4) // 4))


def stop(signum, _frame):
    """End every test process, each in its own session, with the runner."""
    for p in list(LIVE):
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
    os._exit(128 + signum)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m tests.run", description="Run compose's test files in parallel, one process each.")
    ap.add_argument("files", nargs="*", help="test files to run (default: every tests/test_*.py)")
    ap.add_argument("-j", "--jobs", type=int, default=default_jobs())
    a = ap.parse_args(argv)
    paths = sorted(TESTS.glob("test_*.py"), key=lambda p: (-p.stat().st_size, p.name))
    if a.files:
        want = {Path(f).stem.removeprefix("test_") for f in a.files}
        paths = [p for p in paths if p.stem.removeprefix("test_") in want]
        if len(paths) != len(want):
            sys.exit(f"no such test file: {', '.join(sorted(want - {p.stem.removeprefix('test_') for p in paths}))}")
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    t0, total, counts, blocks = time.time(), 0, {}, []
    print(f"running {len(paths)} test files, {a.jobs} at a time", file=sys.stderr)
    with ThreadPoolExecutor(max(1, a.jobs)) as pool:
        for done in as_completed([pool.submit(run_file, p) for p in paths]):
            name, ran, got, block, secs = done.result()
            bad = got.get("failures", 0) + got.get("errors", 0)
            print(f"  {'FAIL' if bad else 'ok  '}  {ran:>5} tests  {secs:6.1f}s  {name}", file=sys.stderr)
            total += ran
            for k, v in got.items():
                counts[k] = counts.get(k, 0) + v
            blocks += [block] if block else []
    for b in blocks:
        print(f"\n{b}", file=sys.stderr)
    bad = counts.get("failures", 0) + counts.get("errors", 0)
    kinds = ", ".join(f"{k}={counts[k]}" for k in COUNTS if counts.get(k))
    print(f"{'-' * 70}\nRan {total} test{'s' * (total != 1)} in {time.time() - t0:.3f}s\n\n"
          + ("FAILED" if bad else "OK") + (f" ({kinds})" if kinds else ""), file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
