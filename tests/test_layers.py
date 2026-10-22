import hermetic  # first: no test sees the real home
import argparse, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
from layers_kit import LayersBase, fc
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""


class Layers(LayersBase):
    """A project branch with groundwork and every task's test on it, and task branches above it: the layers regroup all of it."""
    def layers(self):
        return self.git("branch", "--list", "compose/p-layer-*", "--format=%(refname:short)").split()

    def test_groundwork_is_its_own_layer_and_each_test_lands_with_its_task(self):
        out = self.stack()  # default budget 300: tasks with their tests are 105, 125 and 155 lines
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.changed("compose/p-layer-01", "main"), {"lock.txt", "bun.lock", "setup.txt", "stub.txt"})
        self.assertEqual(self.changed("compose/p-layer-02", "compose/p-layer-01"), {"t001.test", "001.src", "t002.test", "002.src"})
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t003.test", "003.src"})
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-003"), "")  # the layers add up to the project's tree
        notes = [l for l in out if l.startswith("layer ")]
        self.assertIn("groundwork x2: 40 lines; generated, not counted: bun.lock (4000 lines)", notes[0])
        self.assertIn("task 001, 002: 230 lines", notes[1])

    def test_a_review_base_that_names_no_branch_stacks_on_the_default_branch(self):
        """A project made before init recorded the branch it started from holds "main" even where the trunk is master: the
        stack sits on the default branch, never on the project branch."""
        self.stack(review_base="master")  # this repo's trunk is main: the mirror of "main" in a master repo
        self.assertEqual(json.loads((self.repo / ".git" / "fake-gh-stack.json").read_text())["trunk"], "main")
        self.assertEqual(self.changed("compose/p-layer-01", "main"), {"lock.txt", "bun.lock", "setup.txt", "stub.txt"})

    def test_test_commits_on_one_file_keep_the_trunks_order_whoever_owns_them(self):
        """Two tasks protect one test file. A commit on it alone would go to the first of them, but it was written on top of a
        commit the second task owns: it follows that commit into the second task's unit, so the layers replay the trunk's order
        on every file and add up instead of conflicting."""
        tasks = [{"id": "001", "protected": ["t001.test", "shared.test"], "files": ["001.src"], "after": ""},
                 {"id": "002", "protected": ["t002.test", "shared.test"], "files": ["002.src"], "after": ""},
                 {"id": "003", "protected": ["t003.test"], "files": ["003.src"], "after": ""}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        self.write("shared.test", "a\n" * 5); self.write("t002.test", "t\n" * 6); self.commit("test 002, with the shared file")  # 002's: two of its files
        self.write("shared.test", "a\n" * 5 + "b\n" * 5); self.commit("more shared tests")  # on 001's file too, written on top of 002's commit
        out = self.stack()
        self.assertEqual([l for l in out if "STOP" in l], [])
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.changed("compose/p-layer-02", "compose/p-layer-01"), {"t001.test", "001.src", "t002.test", "002.src", "shared.test"})
        self.assertEqual(self.git("show", "compose/p-layer-02:shared.test"), "a\n" * 5 + "b\n" * 4 + "b")
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-003"), "")

    def test_groundwork_written_after_a_tasks_test_gets_its_own_layer_above_that_task(self):
        """A commit no task owns, on a file a task's test commit touched before it, cannot replay in the bottom groundwork: it is a
        groundwork layer of its own right above that task, never inside the task's layer. A later commit on a file it touched goes
        to the first task above it that protects the file, not into the task below."""
        tasks = [{"id": "001", "protected": ["t001.test", "shared.test"], "files": ["001.src"], "after": ""},
                 {"id": "002", "protected": ["t002.test"], "files": ["002.src"], "after": ""},
                 {"id": "003", "protected": ["t003.test", "shared.test"], "files": ["003.src"], "after": ""}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        self.write("t002.test", "g\n" + "t\n" * 5); self.write("shared.test", "g\n"); self.commit("guard every test")  # no task owns both
        self.write("shared.test", "g\n" + "a\n" * 5); self.commit("tests for 003")  # protected by 001 and 003, written after the guard
        out = self.stack()
        self.assertEqual([l for l in out if "STOP" in l], [])
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03", "compose/p-layer-04"])
        self.assertEqual(self.changed("compose/p-layer-02", "compose/p-layer-01"), {"t001.test", "001.src", "t002.test", "002.src"})
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t002.test", "shared.test"})
        self.assertEqual(self.changed("compose/p-layer-04", "compose/p-layer-03"), {"t003.test", "003.src", "shared.test"})
        self.assertIn("layer-03  groundwork x1: 2 lines", [l for l in out if l.startswith("layer ")][2])
        self.assertEqual(self.git("diff", "compose/p-layer-04", "compose/p-003"), "")

    def test_a_test_commit_goes_to_the_task_its_test_writer_wrote_it_for(self):
        """Tasks 001 and 003 both protect one test file. 003's test writer, teammate tests-003, commits its test on top of 001's
        within the span of its reports: it lands in 003's layer, not in the first layer whose task protects the file."""
        tasks = [{"id": "001", "protected": ["t001.test", "shared.test"], "files": ["001.src"], "after": ""},
                 {"id": "002", "protected": ["t002.test"], "files": ["002.src"], "after": ""},
                 {"id": "003", "protected": ["t003.test", "shared.test"], "files": ["003.src"], "after": ""}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        self.write("shared.test", "a\n" * 5); self.commit("tests for 001")  # no writer's span holds it: the first task's
        crew = self.proj / "results" / "crew"; crew.mkdir()
        (crew / f"{fc.fc_herdr.agent_name('p', 'tests-003')}.status").write_text("".join(json.dumps({"at": at, "state": "working", "message": m}) + "\n"
            for at, m in (("2026-01-01 10:00:00", "started"), ("2026-01-01 10:05:00", "test ready: 1234567"))))
        self.write("shared.test", "a\n" * 5 + "b\n" * 5); self.git("add", "-A"); self.git("commit", "-qm", "tests for 003", "--date", "2026-01-01T10:02:00")
        out = self.stack()
        self.assertEqual([l for l in out if "STOP" in l], [])
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.git("show", "compose/p-layer-02:shared.test"), "a\n" * 4 + "a")
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t003.test", "003.src", "shared.test"})
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-003"), "")

    def test_a_test_commit_skips_an_earlier_one_on_its_file_it_does_not_build_on(self):
        """Task 004 has not passed: the test its writer made rides in the top layer. 001's test comes after it on the same file, in
        another part of it: it still lands in 001's layer. One that edits 004's test follows that test into the top layer."""
        tasks = [{"id": "001", "protected": ["t001.test", "shared.test"], "files": ["001.src"], "after": ""},
                 {"id": "002", "protected": ["t002.test"], "files": ["002.src"], "after": ""},
                 {"id": "003", "protected": ["t003.test"], "files": ["003.src"], "after": ""},
                 {"id": "004", "protected": ["t004.test", "shared.test"], "files": ["004.src"], "after": ""}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        part = lambda a, b: f"class A\n{a}" + "-\n" * 8 + f"class B\n{b}"
        self.write("shared.test", part("", "")); self.write("stub.txt", "s\n" * 21); self.commit("a part of the test file for each task")
        crew = self.proj / "results" / "crew"; crew.mkdir()
        (crew / f"{fc.fc_herdr.agent_name('p', 'tests-004')}.status").write_text("".join(json.dumps({"at": at, "state": "working", "message": m}) + "\n"
            for at, m in (("2026-01-01 10:00:00", "started"), ("2026-01-01 10:05:00", "test ready: 1234567"))))
        self.write("shared.test", part("", "b\n" * 5)); self.git("add", "-A"); self.git("commit", "-qm", "tests for 004", "--date", "2026-01-01T10:02:00")
        self.write("shared.test", part("a\n" * 5, "b\n" * 5)); self.commit("tests for 001")
        self.write("shared.test", part("a\n" * 5, "b\n" * 4 + "c\n")); self.commit("fix a test of 004")  # 001 owns it too
        out = self.stack()
        self.assertEqual([l for l in out if "STOP" in l], [])
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.git("show", "compose/p-layer-02:shared.test") + "\n", part("a\n" * 5, ""))
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t003.test", "003.src", "shared.test"})
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-003"), "")

    def test_a_redone_test_writer_owns_only_the_commits_of_its_own_runs_not_the_gap_between_them(self):
        """Tests-003 ran at 10:10 and again at 12:00. Tests-001, redone at 11:00 in between, made the commit at 11:02 on their shared
        file: it lands in 001's layer, not in 003's, whose first and last report would otherwise span it."""
        tasks = [{"id": "001", "protected": ["t001.test", "shared.test"], "files": ["001.src"], "after": ""},
                 {"id": "002", "protected": ["t002.test"], "files": ["002.src"], "after": ""},
                 {"id": "003", "protected": ["t003.test", "shared.test"], "files": ["003.src"], "after": ""}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        crew = self.proj / "results" / "crew"; crew.mkdir()
        for t, runs in (("001", (("10:00:00", "started"), ("10:05:00", "test ready"), ("10:06:00", "done"), ("11:00:00", "started"), ("11:05:00", "done"))),
                        ("003", (("10:10:00", "started"), ("10:15:00", "done"), ("12:00:00", "started"), ("12:05:00", "done")))):
            (crew / f"{fc.fc_herdr.agent_name('p', f'tests-{t}')}.status").write_text("".join(
                json.dumps({"at": f"2026-01-01 {at}", "state": "done" if m == "done" else "working", "message": m}) + "\n" for at, m in runs))
        part = lambda a, b: f"class A\n{a}" + "-\n" * 8 + f"class B\n{b}"
        for at, a, b in (("10:02:00", "a\n" * 5, ""), ("10:12:00", "a\n" * 5, "b\n" * 5), ("11:02:00", "a\n" * 4 + "x\n", "b\n" * 5)):
            self.write("shared.test", part(a, b)); self.git("add", "-A"); self.git("commit", "-qm", f"tests at {at}", "--date", f"2026-01-01T{at}")
        out = self.stack()
        self.assertEqual([l for l in out if "STOP" in l], [])
        self.assertEqual(self.git("show", "compose/p-layer-02:shared.test") + "\n", part("a\n" * 4 + "x\n", ""))
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t003.test", "003.src", "shared.test"})
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-003"), "")

    def test_a_task_over_the_budget_is_never_split(self):
        out = self.stack(review_layer_lines=130)
        self.assertEqual(len(self.layers()), 4)
        self.assertEqual(self.changed("compose/p-layer-04", "compose/p-layer-03"), {"t003.test", "003.src"})
        self.assertIn("task 003: 155 lines; over the 130-line budget", out[-1])

    def test_a_submitted_stack_keeps_each_task_in_its_layer_when_sizes_change(self):
        self.stack(review_layer_lines=300)
        fc.fc_layers.record_layers(self.proj, [{"branch": b, "tasks": t} for b, t in (("compose/p-layer-01", ["groundwork"]), ("compose/p-layer-02", ["001", "002"]), ("compose/p-layer-03", ["003"]))])
        self.git("checkout", "-q", "compose/p-003")
        self.write("003.src", "c\n"); self.commit("shrink 003")  # 003 now fits with 001 and 002, so a regroup would merge layers 02 and 03
        self.git("checkout", "-q", "compose/p")
        self.stack(review_layer_lines=300)
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t003.test", "003.src"})

    def test_a_task_new_since_the_submit_gets_a_layer_above(self):
        self.stack()
        fc.fc_layers.record_layers(self.proj, [{"branch": b, "tasks": t} for b, t in (("compose/p-layer-01", ["groundwork"]), ("compose/p-layer-02", ["001"]))])
        self.stack()
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.changed("compose/p-layer-02", "compose/p-layer-01"), {"t001.test", "001.src"})
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t002.test", "002.src", "t003.test", "003.src"})

    def test_a_rebuild_from_unchanged_commits_keeps_the_hashes(self):
        self.stack()
        before = self.git("rev-parse", "compose/p-layer-01", "compose/p-layer-02")
        self.stack()
        self.assertEqual(self.git("rev-parse", "compose/p-layer-01", "compose/p-layer-02"), before)

    def test_the_gh_stack_is_the_layers_on_the_real_base(self):
        self.stack()
        wt = fc.fc_worktree.stack_worktree(self.repo, self.proj, "compose/p")
        subprocess.run(["git", "checkout", "-q", "compose/p-layer-02"], cwd=wt, check=True)
        data = json.loads(subprocess.run(["gh", "stack", "view", "--json"], cwd=wt, capture_output=True, text=True).stdout)
        self.assertEqual(data["trunk"], "main")
        self.assertEqual([b["name"] for b in data["branches"]], self.layers())

    def stop(self, breaks):
        """Run `compose stack` after a first good build and `breaks`; return its STOP lines, having checked that it exits non-zero and
        changes no layer branch, recorded layer or gh stack."""
        self.stack()
        breaks()
        fc.fc_layers.record_layers(self.proj, [{"branch": b, "tasks": [b]} for b in self.layers()])
        refs = lambda: self.git("for-each-ref", "--format=%(refname) %(objectname)", "refs/heads/compose/p-layer-*")
        before = (refs(), (self.proj / "layers.json").read_text(), (self.repo / ".git" / "fake-gh-stack.json").read_text())
        calls = lambda: [c for c in (self.repo / ".git" / "fake-gh-calls").read_text().splitlines() if not c.startswith("pr view")]  # reading a PR's state changes nothing
        out, seen = [], calls()
        with mock.patch.object(fc.fc_core, "say", out.append), self.assertRaises(SystemExit) as e:
            fc.fc_ship.cmd_stack(argparse.Namespace(repo=str(self.repo), project="p", trunk="compose/p", submit=False, update=False))
        self.assertTrue(e.exception.code)
        self.assertEqual((refs(), (self.proj / "layers.json").read_text(), (self.repo / ".git" / "fake-gh-stack.json").read_text()), before)
        self.assertEqual(calls(), seen)
        return [l for l in out if "STOP" in l]

    def test_a_project_branch_behind_its_base_stops_the_stack_with_layers_and_gh_stack_untouched(self):
        def main_moves_on():
            self.git("checkout", "-q", "main"); self.write("setup.txt", "main\n"); self.commit("main moves on"); self.git("checkout", "-q", "compose/p")
        stops = self.stop(main_moves_on)
        main = self.git("rev-parse", "--short", "main")
        self.assertEqual(len(stops), 1)
        self.assertIn(f"compose/p conflicts with main {main} in setup.txt; the layers and the stack are left as they were. "
                      "Rebase compose/p onto main, then re-run", stops[0])

    def test_a_checkout_on_a_task_branch_stops_the_stack_and_keeps_every_layer(self):
        for at in ("compose/p-003", "compose/p-002"):  # all task branches are in HEAD, or only the ones below
            with self.subTest(at):
                stops = self.stop(lambda: self.git("checkout", "-q", at))
                self.assertEqual(len(stops), 1)
                self.assertIn(f"HEAD is on {at}, one of the project's own branches, not on compose/p", stops[0])
                self.git("checkout", "-q", "compose/p")

    def test_a_detached_head_that_holds_task_branches_stops_the_stack_too(self):
        stops = self.stop(lambda: self.git("checkout", "-q", "--detach", "compose/p-003"))
        self.assertEqual(len(stops), 1)
        self.assertIn("HEAD holds the unmerged task branches compose/p-001, compose/p-002, compose/p-003, which would be left out of the stack", stops[0])

    def test_a_chain_rebase_that_stops_stops_the_stack_verify_and_top_before_they_act_on_the_layers_below_it(self):
        def task_003_conflicts_with_002():
            self.git("checkout", "-q", "-B", "compose/p-003", "compose/p")
            self.write("002.src", "other\n"); self.write("003.src", "c\n"); self.commit("task 003 redone"); self.git("checkout", "-q", "compose/p")
        stops = self.stop(task_003_conflicts_with_002)
        why = "compose/p-003 conflicts when rebased onto compose/p-002 in 002.src; the layers below it are kept. Resolve by hand: git checkout compose/p-003 && git rebase --onto compose/p-002 "
        self.assertEqual(len(stops), 1); self.assertIn(why, stops[0])
        a = argparse.Namespace(repo=str(self.repo), project="p", fix=0, skip_review=True, skip_e2e=True, detach=False)
        said = {}
        for cmd in (fc.fc_verify.cmd_verify, fc.fc_status.cmd_top):
            out = said[cmd.__name__] = []
            with self.subTest(cmd.__name__):
                with mock.patch.object(fc.fc_core, "say", out.append), \
                        mock.patch.object(fc.fc_verify, "run_stages", side_effect=AssertionError("a stage ran")), self.assertRaises(SystemExit) as e:
                    cmd(a)
                self.assertEqual(e.exception.code, 1)
        self.assertTrue(said["cmd_verify"][-1].startswith("verify FAIL  nothing verified or recorded: " + why), said["cmd_verify"])
        self.assertFalse((self.proj / "results" / "verify.json").exists())

    def hold_stack_top(self, kind="verify"):
        """A verify of project p alive in another process, as `compose verify` records it, and the worktree it stands in at the stack top."""
        proc = subprocess.Popen(["sleep", "60"]); self.addCleanup(proc.wait); self.addCleanup(proc.kill)
        live = fc.fc_update.live_dir(); live.mkdir(parents=True, exist_ok=True)
        (live / f"{proc.pid}.json").write_text(json.dumps({"pid": proc.pid, "kind": kind, "project": "p", "repo": str(self.repo), "since": "21:01"}))
        return proc

    def test_stack_top_commands_refuse_while_a_verify_holds_the_stack_top_and_leave_it_where_it_is(self):
        self.stack()
        wt, _, _ = fc.fc_verify.verify_root(self.repo, self.proj, {})
        top = lambda: self.git("-C", str(wt), "branch", "--show-current")
        at = top(); self.assertEqual(at, "compose/p-003")
        proc = self.hold_stack_top()
        ns = lambda **kw: argparse.Namespace(repo=str(self.repo), project="p", trunk="compose/p", **kw)
        for name, cmd, args in (("stack", fc.fc_ship.cmd_stack, ns(submit=False, update=False)), ("stack --submit", fc.fc_ship.cmd_stack, ns(submit=True, update=False)),
                                ("top", fc.fc_status.cmd_top, ns(detach=False)), ("top --detach", fc.fc_status.cmd_top, ns(detach=True)),
                                ("reword", fc.fc_ship.cmd_reword, ns(set=["abc=Add it"], as_is=False))):
            with self.subTest(name), self.assertRaises(SystemExit) as e:
                cmd(args)
            self.assertIn(f"verify is running on p (pid {proc.pid}, since 21:01)", str(e.exception))
            self.assertEqual(top(), at)
        proc.kill(); proc.wait()  # the verify ended: the stack runs again
        self.stack()

    def test_a_verify_whose_checkout_moved_off_its_branch_during_a_stage_is_void_and_records_nothing(self):
        self.stack()
        wt = fc.fc_worktree.stack_worktree(self.repo, self.proj, "compose/p")
        def stack_moves_it(*a, **k):
            self.git("-C", str(wt), "checkout", "-q", "--detach", "compose/p")
            return True, {"checks": []}, ""
        a = argparse.Namespace(repo=str(self.repo), project="p", fix=0, skip_review=True, skip_e2e=True, detach=False)
        out = []
        with mock.patch.object(fc.fc_core, "say", out.append), mock.patch.object(fc.fc_verify, "run_stages", side_effect=stack_moves_it), self.assertRaises(SystemExit) as e:
            fc.fc_verify.cmd_verify(a)
        self.assertEqual(e.exception.code, 1)
        self.assertTrue(any(l.startswith("verify VOID  nothing verified or recorded: ") and "compose/p-003" in l and "detached" in l for l in out), out)
        self.assertFalse((self.proj / "results" / "verify.json").exists())

    def test_layers_that_do_not_add_up_to_the_chain_stop_the_stack_with_layers_and_gh_stack_untouched(self):
        real, broken = fc.fc_layers.review_units, mock.patch.object(fc.fc_layers, "review_units", lambda *a: real(*a)[:-1])
        stops = self.stop(broken.start)  # the top task's unit goes missing
        broken.stop()
        self.assertEqual(stops, ["stack  STOP  the layers differ from compose/p-003 in 003.src, t003.test; the layers and the stack are left as they were"])

    def submit(self):
        """Run `compose stack --submit`; return its lines and exit code (0 when it returned)."""
        out = []
        with mock.patch.object(fc.fc_core, "say", out.append):
            try:
                fc.fc_ship.cmd_stack(argparse.Namespace(repo=str(self.repo), project="p", trunk="compose/p", submit=True, update=False))
            except SystemExit as e:
                return out, e.code
        return out, 0

    def test_a_base_ahead_of_its_upstream_warns_and_a_submit_stops_with_nothing_changed(self):
        self.git("update-ref", "refs/remotes/origin/main", "main"); self.git("branch", "-q", "--set-upstream-to=origin/main", "main")
        self.git("checkout", "-q", "main")
        for n in ("1", "2"):
            self.write(f"unpushed{n}.txt", "u\n"); self.commit(f"unpushed {n}")
        self.git("checkout", "-q", "compose/p")
        self.assertIn("stack  WARN  main is 2 commits ahead of origin/main, so the PRs would carry them; --submit stops until main is pushed", self.stack())
        refs = lambda: self.git("for-each-ref", "--format=%(refname) %(objectname)", "refs/heads/compose/p*")
        before = (refs(), (self.repo / ".git" / "fake-gh-stack.json").read_text(), (self.repo / ".git" / "fake-gh-calls").read_text())
        out, code = self.submit()
        self.assertEqual(code, 1)
        self.assertEqual(out, ["stack  STOP  main is 2 commits ahead of origin/main, so the PRs would carry them; nothing was built or pushed. "
                               "Push main, or wait until origin/main has them, then re-run"])
        self.assertEqual((refs(), (self.repo / ".git" / "fake-gh-stack.json").read_text(), (self.repo / ".git" / "fake-gh-calls").read_text()), before)

    def test_a_base_even_with_or_behind_its_upstream_or_without_one_submits_without_a_word(self):
        for upstream in ("none", "even", "behind"):
            if upstream != "none":
                self.git("update-ref", "refs/remotes/origin/main", "main"); self.git("branch", "-q", "--set-upstream-to=origin/main", "main")
            if upstream == "behind":
                self.git("checkout", "-q", "-b", "elsewhere", "main"); self.write("theirs.txt", "t\n"); self.commit("pushed by someone else")
                self.git("update-ref", "refs/remotes/origin/main", "elsewhere"); self.git("checkout", "-q", "compose/p")
            (self.proj / "verify.json").write_text(json.dumps({"review_base": "main"}))
            calls = self.repo / ".git" / "fake-gh-calls"
            seen = len(calls.read_text().splitlines()) if calls.exists() else 0
            out, code = self.submit()
            self.assertEqual(code, 0, upstream)
            self.assertFalse([l for l in out if "WARN" in l or "STOP" in l], upstream)
            self.assertIn("stack submit --auto", calls.read_text().splitlines()[seen:], upstream)

    def test_stack_without_submit_prints_each_layers_pr_title_and_body_and_calls_no_gh_pr(self):
        (self.proj / "verify.json").write_text(json.dumps({"review_base": "main"}))
        cache = json.loads((self.proj / "results" / "tasks.json").read_text())
        (self.proj / "results" / "tasks.json").write_text(json.dumps({**cache, "feature": {"title": "Build it", "description": "Fixes o/r#9."}}))
        out = []
        with mock.patch.object(fc.fc_core, "say", out.append):
            fc.fc_ship.cmd_stack(argparse.Namespace(repo=str(self.repo), project="p", trunk="compose/p", submit=False, update=False))
        prs = [l for l in out if l.startswith("pr ")]
        self.assertEqual([l.split()[1] for l in prs], self.layers())
        for i, l in enumerate(prs, 1):
            self.assertIn(f"({i}/3)", l.splitlines()[0])
            self.assertIn("## What changed", l)
            self.assertNotRegex(l, r" lines|attempt")  # no size line or attempt count reaches a reviewer
        self.assertIn("## What changed\n    - Build 001\n    - Build 002\n\n", prs[1])  # one line per task, its test commit folded in
        self.assertIn("- Part of o/r#9", prs[1])  # as submit writes it: the issue is fixed by the layer with its last task
        self.assertIn("- Fixes o/r#9", prs[2])
        calls =(self.repo / ".git" / "fake-gh-calls").read_text().splitlines()
        self.assertFalse([c for c in calls if not c.startswith("stack ")])
        self.assertFalse((self.proj / "pr_text.json").exists())

    def preview(self, **cfg):
        """`compose stack`'s pr lines without --submit: ({branch: its pr line and body}, the other pr lines)."""
        (self.proj / "verify.json").write_text(json.dumps({"review_base": "main", **cfg}))
        out = []
        with mock.patch.object(fc.fc_core, "say", out.append):
            fc.fc_stack.register_stack(self.repo, self.proj, "compose/p", preview=True)
        prs = [l for l in out if l.startswith("pr ")]
        return {l.split()[1]: l for l in prs if l.split()[1] in self.layers()}, [l for l in prs if l.split()[1] not in self.layers()]

    def test_a_layers_written_pr_text_replaces_its_title_why_and_what_changed_and_compose_keeps_the_facts(self):
        cache = json.loads((self.proj / "results" / "tasks.json").read_text())
        (self.proj / "results" / "tasks.json").write_text(json.dumps({**cache, "feature": {"title": "Build it", "description": "Fixes o/r#9."}}))
        self.pr_file("001-002", self.WRITTEN)
        self.pr_file("groundwork", "# Prepare the build\n\n## Why\nIt needs stubs.\n\n## What changed\n- Add stubs\n\n## Notes\nmore\n")
        prs, rest = self.preview()
        self.assertEqual(rest, [])
        self.assertEqual(prs["compose/p-layer-02"],
                         "pr     compose/p-layer-02  Keep the toggle's state across reloads (2/3)  [written: .compose/p/pr/001-002.md]\n"
                         "    ## Why\n    The toggle forgot its state on every reload.\n    This stores it.\n    - Part of o/r#9\n\n"
                         "    ## What changed\n    - Store the toggle's state\n    - Read it back on load\n\n"
                         "    ## How it was tested\n    - `make 001`\n    - `make 002`\n\n    ## Tickets\n    - ENG-001\n    - ENG-002")
        self.assertIn("Build 003 (3/3)  [generated: write .compose/p/pr/003.md]\n", prs["compose/p-layer-03"])
        self.assertIn("- Fixes o/r#9", prs["compose/p-layer-03"])
        self.assertIn("  [generated: .compose/p/pr/groundwork.md refused: after the title it must be `## Why` then `## What changed`, nothing else]\n",
                      prs["compose/p-layer-01"])
        self.assertNotIn("Prepare the build", prs["compose/p-layer-01"])

    def test_a_pr_text_file_follows_its_tasks_to_a_new_layer_and_one_whose_tasks_were_regrouped_is_never_applied(self):
        self.pr_file("003", self.WRITTEN)
        self.pr_file("001-002", self.WRITTEN.replace("Keep the toggle's", "Show the panel's"))
        prs, rest = self.preview(review_layer_lines=1)  # two groundwork layers, then one layer per task
        self.assertEqual(list(prs), [f"compose/p-layer-0{i}" for i in range(1, 6)])
        self.assertIn("Keep the toggle's state across reloads (5/5)  [written: .compose/p/pr/003.md]", prs["compose/p-layer-05"])
        self.assertIn("[generated: write .compose/p/pr/groundwork-2.md]", prs["compose/p-layer-02"])
        self.assertFalse([l for l in prs.values() if "Show the panel's" in l])
        self.assertEqual(rest, ["pr     .compose/p/pr/001-002.md matches no layer, so no PR uses it; the layers' files are "
                                "groundwork.md, groundwork-2.md, 001.md, 002.md, 003.md"])

    def test_pr_text_is_a_title_why_and_bullets_and_anything_else_is_refused_with_the_reason(self):
        f = Path(tempfile.mkdtemp()) / "001.md"
        self.assertIsNone(fc.fc_stack.pr_text(f, 72))
        f.write_text(self.WRITTEN.replace("\n\n## Why", "\n\n\n## Why\n").replace("on load\n", "on load\n\n\n"))
        self.assertEqual(fc.fc_stack.pr_text(f, 72), ("Keep the toggle's state across reloads",
                         ["The toggle forgot its state on every reload.", "This stores it."], ["- Store the toggle's state", "- Read it back on load"]))
        for text, why in [("Keep it\n## Why\nx\n## What changed\n- y", "line 1 must be `# <title>`"),
                          ("# JS-7: Keep it\n## Why\nx\n## What changed\n- y", "ticket key or (i/n)"),
                          ("# Keep it (2/3)\n## Why\nx\n## What changed\n- y", "ticket key or (i/n)"),
                          ("# " + "x" * 73 + "\n## Why\nx\n## What changed\n- y", "the title is 73 characters, at most 72"),
                          ("# Keep it\nintro\n## Why\nx\n## What changed\n- y", "`## Why` then `## What changed`, nothing else"),
                          ("# Keep it\n## What changed\n- y\n## Why\nx", "`## Why` then `## What changed`, nothing else"),
                          ("# Keep it\n## Why\nx\n## What changed\n- y\n### More\n", "`## Why` then `## What changed`, nothing else"),
                          ("# Keep it\n## Why\n\n## What changed\n- y", "must not be empty"),
                          ("# Keep it\n## Why\nx\nFixes o/r#9\n## What changed\n- y", "compose adds the Fixes and Part of lines"),
                          ("# Keep it\n## Why\nx\n## What changed\n- y\nz", "must be a `- ` bullet")]:
            f.write_text(text)
            with self.assertRaises(ValueError) as e:
                fc.fc_stack.pr_text(f, 72)
            self.assertIn(why, str(e.exception), text)


if __name__ == "__main__":
    unittest.main()
