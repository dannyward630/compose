"""post_json against a fake model provider on localhost: how it rides out a busy provider. No paid APIs."""

import json
import threading
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jev_ultrafast import model


@pytest.fixture
def provider(monkeypatch):
    """A local provider answering each POST with the next scripted (status, headers); the last one repeats. Sleeps are
    recorded, not slept, and the jitter is its upper bound, so every wait is exact."""
    script, seen, waits = [], [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            status, headers = script.pop(0) if len(script) > 1 else script[0]
            body = json.dumps({"ok": True} if status == 200 else {"error": "busy"}).encode()
            self.send_response(status)
            for k, v in {"Content-Type": "application/json", "Content-Length": str(len(body)), **headers}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(model.time, "sleep", waits.append)
    monkeypatch.setattr(model.random, "uniform", lambda low, high: high)
    yield f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions", script, seen, waits
    server.shutdown()


def test_a_burst_of_429s_is_waited_out_with_growing_backoff(provider):
    url, script, seen, waits = provider
    script += [(429, {})] * 5 + [(200, {})]
    assert model.post_json(url, "k", {"n": 1}) == {"ok": True}
    assert len(seen) == 6 and all(b == {"n": 1} for b in seen)
    assert waits == [0.5, 1.0, 2.0, 4.0, 8.0]  # doubling, the jitter at its upper bound


def test_retry_after_in_seconds_or_as_a_date_is_honoured(provider):
    url, script, _, waits = provider
    script += [(429, {"Retry-After": "3"}), (503, {"Retry-After": formatdate(model.time.time() + 600, usegmt=True)}), (200, {})]
    with pytest.raises(RuntimeError, match=r"HTTP 503 and asked to wait (599|600)s, past"):  # past the budget: give up now, not in ten minutes
        model.post_json(url, "k", {})
    assert waits == [3.0 + 0.5]  # the provider's wait, then a little jitter so callers it turned away do not return together
    script[:] = [(529, {"Retry-After": "2"}), (200, {})]
    waits.clear()
    assert model.post_json(url, "k", {}) == {"ok": True}
    assert waits == [2.5]


def test_a_provider_that_stays_busy_is_given_up_on_within_the_budget(provider):
    url, script, seen, waits = provider
    script += [(429, {})]
    with pytest.raises(RuntimeError, match=r"Model provider returned HTTP 429 \d+ times over \d+s; no action executed"):
        model.post_json(url, "k", {})
    assert sum(waits) <= model.RETRY_BUDGET and max(waits) <= model.RETRY_MAX_WAIT
    assert len(seen) == len(waits) + 1
    script[:] = [(429, {"Retry-After": "0"})]  # a provider that says "now" forever still ends
    seen.clear()
    with pytest.raises(RuntimeError, match="HTTP 429"):
        model.post_json(url, "k", {})
    assert len(seen) == model.RETRY_TRIES


def test_an_error_that_is_not_busy_fails_at_once(provider):
    url, script, seen, waits = provider
    script += [(400, {"Retry-After": "1"})]
    with pytest.raises(RuntimeError, match=r"^Model provider returned HTTP 400; no action executed\.$"):
        model.post_json(url, "k", {})
    assert (len(seen), waits) == (1, [])
