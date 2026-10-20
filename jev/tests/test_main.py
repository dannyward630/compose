"""`python -m jev_ultrafast`: the one way verify's e2e cases and `bp goal` run jev. No browser, no paid APIs."""

import json

import pytest

from jev_ultrafast import __main__ as runner


class FakeAgent:
    """Yields the given statuses as snapshots, one action each, then raises `fail` if given."""

    made = []

    def __init__(self, url, goals, *, record_dir=None, secrets=None, statuses=("done",), fail=None, reason=None):
        self.url, self.goals, self.record_dir, self.secrets = url, goals, record_dir, secrets
        self.statuses, self.fail, self.reason, self.history = statuses, fail, reason, []
        self.status = "ready"
        FakeAgent.made.append(self)

    def snapshot(self):
        return {"status": self.status, "stop_reason": self.reason if self.status == "blocked" else None,
                "elapsed_ms": 10 * len(self.history), "history": list(self.history),
                "page": {"url": self.url + "#after"}, "decisions": [{"usage": {"input_tokens": 7, "output_tokens": 2}}],
                "text_calls": []}

    def run(self):
        for status in self.statuses:
            self.history.append({"step": len(self.history) + 1, "kind": "click", "action": "Next " * 30, "page_changed": False})
            self.status = status
            yield self.snapshot()
        if self.fail:
            raise self.fail

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def run(monkeypatch, capsys, *args, **agent):
    FakeAgent.made.clear()
    monkeypatch.setattr(runner, "Agent", lambda url, goals, **kw: FakeAgent(url, goals, **kw, **agent))
    code = runner.main(["http://app.test/", "Log in", *args])
    out, err = capsys.readouterr()
    lines = out.strip().splitlines()
    assert lines[-1].startswith("JEV_RESULT ")
    return code, json.loads(lines[-1][len("JEV_RESULT "):]), out, err


def test_a_reached_goal_exits_0_with_its_result_and_a_compact_history(monkeypatch, capsys):
    code, r, _, _ = run(monkeypatch, capsys, statuses=("ready", "done"))
    assert code == 0
    assert (r["status"], r["stop_reason"], r["steps"], r["url"]) == ("done", None, 2, "http://app.test/#after")
    assert r["usage"]["typesafe_calls"] == 1 and r["usage"]["typesafe_in"] == 7
    assert r["history"][0] == {"step": 1, "kind": "click", "label": ("Next " * 30)[:80], "page_changed": False}


def test_a_blocked_run_exits_1_and_says_why(monkeypatch, capsys):
    code, r, _, _ = run(monkeypatch, capsys, statuses=("ready", "blocked"), reason="The last 3 actions did not change the page")
    assert (code, r["status"], r["stop_reason"], r["steps"]) == (1, "blocked", "The last 3 actions did not change the page", 2)


def test_a_crash_still_ends_with_a_result_its_traceback_and_the_steps_taken(monkeypatch, capsys):
    # A raise used to end the script before JEV_RESULT, so verify kept nothing of the run and skipped the assert.
    code, r, _, err = run(monkeypatch, capsys, statuses=("ready",), fail=RuntimeError("Model provider returned HTTP 500"))
    assert (code, r["status"], r["stop_reason"], r["steps"]) == (1, "error", "RuntimeError: Model provider returned HTTP 500", 1)
    assert "Traceback" in err and "/jev_ultrafast/" in err  # verify's tool-error label reads the path


def test_progress_prints_a_line_per_step_and_the_stop_reason(monkeypatch, capsys):
    _, _, out, _ = run(monkeypatch, capsys, "--progress", statuses=("ready", "blocked"), reason="Stopped at the 60-action budget")
    lines = out.splitlines()
    assert lines[0] == "   10 ms  1 actions  ready  click " + "Next " * 12 and "2 actions  blocked" in lines[1]
    assert lines[2] == "blocked: Stopped at the 60-action budget"


def test_secrets_are_read_from_the_env_and_never_printed(monkeypatch, capsys):
    monkeypatch.setenv("E2E_PASSWORD", "pw-Sekr3t!")
    code, _, out, err = run(monkeypatch, capsys, "--secrets", json.dumps({"Password": "${E2E_PASSWORD}"}))
    assert code == 0 and FakeAgent.made[0].secrets == {"Password": "pw-Sekr3t!"}
    assert "pw-Sekr3t!" not in out + err


@pytest.mark.parametrize("ref, said", [("hunter2", "must name an env var"), ("$E2E_NOT_SET", "$E2E_NOT_SET is not set")])
def test_a_literal_or_unset_secret_stops_before_any_browser(monkeypatch, capsys, ref, said):
    monkeypatch.delenv("E2E_NOT_SET", raising=False)
    code, r, _, _ = run(monkeypatch, capsys, "--secrets", json.dumps({"Password": ref}))
    assert (code, r["status"], r["steps"]) == (1, "error", 0)
    assert said in r["stop_reason"] and not FakeAgent.made
