"""snapshot.js in a real headless Chromium, through jev's own Browser: what jev offers its model, and what its input does.
No paid APIs. Skipped without Playwright's Chromium."""

import glob
import json
import os
import platform
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from browser_harness import _ipc, admin, helpers

from jev_ultrafast.browser import Browser


def chromium():
    if os.environ.get("BP_CHROME"):
        return os.environ["BP_CHROME"]
    arch = "arm64" if platform.machine() == "arm64" else "x64"
    found = sorted(glob.glob(os.path.expanduser(
        f"~/Library/Caches/ms-playwright/chromium-*/chrome-mac-{arch}/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")))
    return found[-1] if found else None


CHROME = chromium()
pytestmark = pytest.mark.skipif(not CHROME or not Path(CHROME).exists(), reason="Playwright Chromium not installed")


@pytest.fixture(scope="module")
def cdp():
    """A headless Chromium on a free port (port 0: it writes the one it took), its own profile and harness daemon name."""
    profile = tempfile.mkdtemp(prefix="jev-snapshot-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--user-data-dir={profile}", "--no-first-run", "--remote-debugging-port=0",
                               "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port, deadline = None, time.monotonic() + 15
    while not port and time.monotonic() < deadline:
        time.sleep(0.1)
        f = Path(profile) / "DevToolsActivePort"
        port = f.exists() and f.read_text().split("\n")[0].strip()
    # browser-harness reads BU_NAME once, at import; a run gets it from its environment, this module sets it after the
    # import. A name of its own, never "default": that daemon may be attached to the user's own Chrome.
    env = {"BU_CDP_URL": f"http://127.0.0.1:{port}", "BU_NAME": f"jev-snapshot-{os.getpid()}"}
    saved = {k: os.environ.get(k) for k in env}
    names = {m: m.NAME for m in (admin, helpers)}
    os.environ.update(env)
    for m in names:
        m.NAME = env["BU_NAME"]
    # One daemon for the module, so no Browser owns it: a daemon asked to shut down lingers 15 s before its stopper
    # gives up waiting, so the module ends its own with a plain SIGTERM instead.
    admin.ensure_daemon()
    daemon = _ipc.identify(env["BU_NAME"], timeout=5.0)
    yield
    if daemon:
        os.kill(daemon, signal.SIGTERM)
    _ipc.pid_path(env["BU_NAME"]).unlink(missing_ok=True)
    _ipc.cleanup_endpoint(env["BU_NAME"])
    chrome.terminate()
    chrome.wait(10)
    for k, v in saved.items():
        os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)
    for m, name in names.items():
        m.NAME = name
    shutil.rmtree(profile, ignore_errors=True)


@pytest.fixture
def open_page(cdp, tmp_path):
    opened = []

    def open_page(html):
        f = tmp_path / f"page{len(opened)}.html"
        f.write_text("<!doctype html>" + html)
        opened.append(Browser(f.as_uri()))
        return opened[-1]

    yield open_page
    for b in opened:
        b.close()


def kinds(page):
    return [(a["kind"], a["label"]) for a in page["actions"]]


def test_a_password_field_is_offered_as_a_secret_whose_value_never_leaves_the_page(open_page):
    b = open_page("<form><label>Email <input type=email></label><label>Password <input type=password></label>"
                  "<button>Log in</button></form>")
    page = b.observe(screenshot=False)
    password = next(a for a in page["actions"] if a["kind"] == "fill" and a["label"] == "Password")
    assert (password["secret"], password["value"]) == (True, "")
    b.act(password, page, text="pw-Sekr3t!")
    after = b.observe(screenshot=False)
    assert next(a for a in after["actions"] if a["label"] == "Password")["value"] == "[filled]"
    assert after["fingerprint"] != page["fingerprint"]
    assert "pw-Sekr3t!" not in json.dumps(after)
    assert b.evaluate("document.querySelector('input[type=password]').value") == "pw-Sekr3t!"


def scroll(b, page, which="scroll_down"):
    b.act(next(a for a in page["actions"] if a["id"] == which), page)
    time.sleep(0.3)
    return b.observe(screenshot=False)


def test_the_document_scrolls_as_before(open_page):
    b = open_page("<div style='height:3000px'>long</div>")
    page = b.observe(screenshot=False)
    assert ("scroll", "Scroll down") in kinds(page) and ("scroll", "Scroll up") not in kinds(page)
    after = scroll(b, page)
    assert after["scroll"]["y"] == 560 and after["fingerprint"] != page["fingerprint"]
    assert ("scroll", "Scroll up") in kinds(after)


def test_content_that_scrolls_inside_a_container_gets_scroll_actions_and_moves(open_page):
    # A fixed-height body around an overflow:auto main: jev offered no scroll, never saw the button, and ended blocked.
    b = open_page("<style>html,body{height:100%;margin:0;overflow:hidden} header{height:60px}"
                  "main{height:calc(100% - 60px);overflow:auto}</style><header>Top</header>"
                  "<main><div style='height:1500px'>long</div><button>Bottom button</button></main>")
    page = b.observe(screenshot=False)
    assert ("scroll", "Scroll down") in kinds(page) and ("click", "Bottom button") not in kinds(page)
    for _ in range(5):
        if ("click", "Bottom button") in kinds(page):
            break
        before, page = page, scroll(b, page)
        assert page["fingerprint"] != before["fingerprint"]  # a container's scroll is a page change
    assert ("click", "Bottom button") in kinds(page) and ("scroll", "Scroll up") in kinds(page)
    assert b.evaluate("document.querySelector('main').scrollTop") > 0 and page["scroll"]["y"] == 0


def test_a_scroll_container_away_from_the_wheel_point_takes_the_wheel_at_its_center(open_page):
    b = open_page("<style>html,body{height:100%;margin:0;overflow:hidden} nav{width:300px;height:100%;overflow:auto}</style>"
                  "<nav><div style='height:2000px'>menu</div><a href='#end'>Last link</a></nav>")
    page = b.observe(screenshot=False)
    down = next(a for a in page["actions"] if a["id"] == "scroll_down")
    assert down["x"] < 300
    scroll(b, page)
    assert b.evaluate("document.querySelector('nav').scrollTop") > 0
