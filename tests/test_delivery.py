import hermetic  # first: no test sees the real home
import io, json, os, tempfile, time, unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from test_linear_cmd import fc, URL, KEY
import fc_plan
os.environ["HERDR_ENV"] = ""

TODAY = time.strftime("%Y-%m-%d")
TRACKS = "## Tracks\n\n1. Sign-in: NEB-7, NEB-9\n2. Onboarding: NEB-12 (after Sign-in)\n"


def node(ident, state, *blockers, title=None, parent=None, project="p1"):
    return {"identifier": ident, "title": title or "T " + ident, "url": "u/" + ident, "description": "", "state": {"name": state},
            "parent": {"identifier": parent} if parent else None, "labels": {"nodes": [{"name": "Feature"}]}, "project": {"id": project},
            "inverseRelations": {"nodes": [{"type": "blocks", "issue": {"identifier": b, "state": {"name": s}, "labels": {"nodes": []}}} for b, s in blockers]}}


class Product(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()).resolve()
        (self.repo / ".compose").mkdir()
        (self.repo / ".compose" / "linear.json").write_text(json.dumps({"project": URL, "team": "Engineering"}))
        self.calls, self.created, self.doc_writes, self.page = [], None, [], None
        self.content = TRACKS
        self.docs = [("Product delivery plan", "u/doc"), ("NEB-9: delivery plan", "u/d9")]
        self.nodes = [node("NEB-7", "Done"), node("NEB-9", "Todo", ("NEB-7", "Done")), node("NEB-12", "Todo")]
        self.tracks_file = self.repo / "tracks.md"
        self.tracks_file.write_text(TRACKS)
        story = node("NEB-10", "Todo", parent="NEB-9")
        for mod, name, value in ((fc.fc_config, "LINEAR_KEY", KEY), (fc.fc_config, "WORKSPACE", "work"), (fc.fc_linear, "linear_gql", self.gql),
                                 (fc.fc_linear, "linear_children", lambda ident: [story] if ident == "NEB-9" else [])):
            p = mock.patch.object(mod, name, value); p.start(); self.addCleanup(p.stop)

    def set_docs(self, docs, content):
        if docs is not None:
            self.docs = docs
        self.content = content

    def gql(self, query, variables):
        q = " ".join(query.split())
        self.calls.append((q, variables))
        if "projects(filter" in q:
            return {"projects": {"nodes": [{"id": "p1", "name": "Shop", "url": URL, "teams": {"nodes": [{"id": "t1", "name": "Engineering", "key": "ENG"}]}}]}}
        if "labels: {some" in q:
            return {"issues": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": self.nodes if self.page is None else self.page}}
        if "documents(first" in q:
            return {"project": {"documents": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                                              "nodes": [{"id": "d" + str(n), "title": t, "url": u} for n, (t, u) in enumerate(self.docs)]}}}
        if "document(id" in q:
            return {"document": {"id": "d0", "title": "Product delivery plan", "url": "u/doc", "content": self.content}}
        if "documentCreate" in q:
            self.created = variables
            return {"documentCreate": {"document": {"id": "dnew", "title": variables["title"], "url": "u/new", "content": variables["content"]}}}
        if "documentUpdate" in q:
            self.doc_writes.append(variables["content"])
            return {"documentUpdate": {"success": True}}
        if "issue(id" in q:
            return {"issue": next((n for n in self.nodes if n["identifier"] == variables["id"]), None)}
        raise AssertionError(q)

    def mutations(self):
        return [q for q, _ in self.calls if q.startswith("mutation")]

    def run_verb(self, action, **kw):
        a = SimpleNamespace(**{**dict(repo=str(self.repo), action=action, file=None, quote=None, dry_run=False, json=False), **kw})
        with redirect_stdout(io.StringIO()) as out:
            fc.fc_delivery.cmd_delivery(a)
        return out.getvalue()

    def test_no_document_or_no_tracks_means_no_plan_and_order_says_how_to_start(self):
        for docs, content in (([], ""), (None, fc_plan.product_skeleton())):
            self.set_docs(docs, content)
            self.assertIsNone(fc.fc_delivery.product_plan(self.repo))
            with self.assertRaises(SystemExit) as e:
                self.run_verb("order")
            self.assertEqual(e.exception.code, fc.fc_delivery.NO_PLAN)

    def test_order_prints_one_line_per_entry_and_json_on_request(self):
        out = self.run_verb("order").splitlines()
        self.assertEqual(out[:2], ["1. NEB-10 T NEB-10 (Todo; feature NEB-9, track Sign-in, wave 1)",
                                   "2. NEB-12 T NEB-12 (Todo; feature, track Onboarding, wave 2; waits on NEB-9)"])
        self.assertEqual(json.loads(self.run_verb("order", json=True))[0]["id"], "NEB-10")

    def test_seed_lists_open_features_their_plans_and_a_guess_and_writes_nothing(self):
        self.set_docs([("NEB-9: delivery plan", "u/d9")], "")
        out = self.run_verb("seed")
        self.assertIn("No product delivery plan yet.", out)
        self.assertIn("- NEB-9 T NEB-9 (Todo, blocked by NEB-7), its plan: u/d9", out)
        self.assertIn("A first guess at the tracks, from the blocks Linear holds today; play it back as a guess:\n1. ", out)
        self.assertEqual(self.mutations(), [])

    def test_a_bad_tracks_section_stops_with_its_line(self):
        self.content = "## Tracks\n\n1. Sign-in NEB-7\n"
        with self.assertRaises(SystemExit) as e:
            self.run_verb("order")
        self.assertTrue(e.exception.code.startswith('delivery order: the Tracks section does not parse: line 1: not a track: "1. Sign-in NEB-7"'))

    def test_a_track_id_outside_the_page_is_kept_only_in_this_project(self):
        self.page = [node("NEB-12", "Todo")]
        self.nodes = self.page + [node("NEB-30", "Todo", project="other"), node("NEB-31", "Todo")]
        self.content = "## Tracks\n\n1. A: NEB-12, NEB-30, NEB-31\n"
        got = fc.fc_delivery.read_product(str(self.repo))["features"]
        self.assertEqual(sorted(got), ["NEB-12", "NEB-31"])
