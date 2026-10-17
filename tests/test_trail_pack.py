import subprocess, tempfile, unittest
from pathlib import Path
from tests.test_trail_setup import fc, repo_with, FakeGraft, FakeTrail  # noqa: F401


class GraftPack(FakeGraft):
    """Implementer and fixer prompts get a pack wherever graft keeps the graph: graft/, or .trail/cache/ once graft 0.23
    moved the repo to trail. trail's learning banner is not part of it."""
    def repo_on_trail(self):
        repo, _ = repo_with({"server/main.go": "package main\n"})
        (repo / ".trail" / "cache").mkdir(parents=True)
        (repo / ".trail" / "cache" / "INDEX.md").write_text("index")
        return repo

    def assert_pack(self, pack, query):
        self.assertEqual(pack, f'graft ask — "{query}"  (lexical)\n\n1. main · function  [symbol]\n   server/main.go:L1-L1')

    def test_a_graph_in_trail_cache_gives_a_pack_without_banners(self):
        self.assert_pack(fc.fc_implement.graft_pack(self.repo_on_trail(), "main"), "main")

    def test_a_task_clone_gets_the_trail_graph_and_keeps_it_out_of_git(self):
        repo = self.repo_on_trail()
        clone = Path(tempfile.mkdtemp()) / "clone"
        subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True)
        fc.fc_worktree.ready_checkout(repo, clone)
        self.assert_pack(fc.fc_implement.graft_pack(clone, "entry point", repo=repo), "entry point")
        self.assertTrue((clone / ".trail" / "cache" / "INDEX.md").exists())
        self.assertFalse((clone / "graft").exists())
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=clone, capture_output=True, text=True).stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
