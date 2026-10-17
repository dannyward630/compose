import ast
import hashlib
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"

RANK = ("fc_core", "fc_config", "fc_tasks", "fc_linear", "fc_claude", "fc_models", "fc_herdr", "fc_worktree", "fc_layers", "fc_change", "fc_frame0", "fc_crew", "fc_init", "fc_figma", "fc_briefs", "fc_implement", "fc_jev", "fc_verify", "fc_run", "fc_status", "fc_spec", "fc_watch", "fc_yolo", "fc_bench")
MODULES = {
    "fc_core": ("now", "fmt", "say", "Ledger", "LEDGER", "sh", "worktrees", "project_config", "project_branch", "commit_convention", "COMMIT_TYPES", "typed", "commit_rule", "all_projects", "project_dir", "atomic_write", "digests", "figma_key", "current_branch", "load_env", "free_port", "port_listening", "report_time", "project_after"),
    "fc_config": ("DEFAULT_MODEL", "FALLBACK_MODEL", "JEV_DIR", "PRICES", "CONFIG_PATH", "ENV_FILE", "OPENROUTER_KEY", "MAX_DIFF_LINES", "DOC_RE", "DEP_DIRS", "EXPR_L36", "EXPR_L37", "CREW_MODELS", "LINEAR_KEY", "WORKSPACE", "CREW_EFFORT", "CREW_FALLBACK", "PLANNING_ROLES", "CREW_DEFAULTS", "PROBE_CACHE", "read_config", "write_config", "settings", "apply_config", "WORKSPACE_ACTIONS", "read_key", "cmd_workspace"),
    "fc_tasks": ("TASK_BLOCK", "SYNC_SHAPE", "task_from_issue", "sync_tasks", "linear_cache", "load_tasks", "linear_done", "code_tasks", "FINISHED", "task_finished", "parse_criteria", "criteria_from_tasks", "_hold_warned", "held", "held_behind", "yolo_state", "CANCELED", "run_marker", "pid_alive", "run_alive"),
    "fc_linear": ("LINEAR_TREE_FIELDS", "LINEAR_FEATURE", "LINEAR_CHILDREN", "linear_children", "linear_sync_payload", "LINEAR_URL", "LINEAR_ISSUE", "_linear_warned", "linear_gql", "linear_issue", "linear_move", "linear_comment", "linear_ready", "linear_note", "LINEAR_BLOCKERS", "linear_blocked_by", "linear_restore", "rollup_state", "linear_roll_up", "linear_event", "linear_merged", "linear_verified", "cmd_sync"),
    "fc_claude": ("is_claude", "claude_id", "headless_env", "NO_ATTRIBUTION", "crew_settings", "claude_once", "claude_trusted", "untrusted"),
    "fc_models": ("opencode", "RATE_LIMIT_MARK", "pi_error", "pi_turn", "fallback_for", "PaymentRequired", "PAY_RE", "TOP_UP", "payment_check", "http_json", "RateLimited", "parse_pi_session", "_PROBED", "pi_id", "pi_key_args", "probe_command", "probe_result", "model_available", "TRANSIENT", "probe_once", "probe_clear", "cmd_models", "TEST_TIMEOUT", "TURN_TIMEOUT", "turn_timeout", "payment_halt", "lenient_json", "fast_env", "fast_json", "EmptyReply", "ConfirmError", "confirm_call", "jev_ask", "reask_criterion"),
    "fc_herdr": ("HERDR_SPACES", "PI_HERDR_EXT", "herdr_env", "herdr", "herdr_error", "herdr_text", "herdr_ready", "herdr_await_start", "herdr_start_crew", "pane_processes", "pane_launching", "pane_kill", "agent_name", "herdr_main_repo", "herdr_find_space", "project_worktree", "live_agents", "herdr_space", "herdr_tabs", "herdr_status_tab", "herdr_label", "IMPLEMENTERS_TAB", "herdr_implementer_pane", "herdr_agent_start", "herdr_verify_panes", "herdr_stage", "herdr_space_is"),
    "fc_worktree": ("replace_branch", "replaced_tips", "task_branches", "stack_order", "TREEHOUSE_INSTALL", "use_treehouse", "treehouse", "slot_on", "pool_shortfall", "is_slot", "default_branch", "release_slot", "slots", "stack_worktree", "exclude_paths", "TOOL_DIRS", "ignore_tool_files", "dep_dirs", "stamp_graft_wiring", "ready_checkout", "names_lockfile", "adopt_installs", "mirror_stack_state", "STACK_LOCK", "GENERATED_RE", "LOCKFILE_RE", "LOCKFILES"),
    "fc_layers": ("CONFIG_FILE_RE", "layer_prefix", "commit_message", "chain_order", "STACK_STOP", "linearize", "_linearize", "REVIEW_LAYER_LINES", "commit_facts", "group_units", "review_units", "cherry_pick_same", "record_layers", "group_by_record", "build_layers", "layer_note", "layer_pr", "gh_pr_text", "write_pr_text", "register_stack", "cmd_stack"),
    "fc_change": ("REFLECT_THRESHOLD", "REFLECT_EVIDENCE_CAP", "REFLECT_LOCK", "REFLECT_CHOICES", "REFLECT_RULES", "map_section", "LIST_ITEM", "decision_lines", "changes_dir", "last_change_done", "evidence_cut", "evidence_since", "reflect", "cmd_hold", "CHANGE_SYNC_MAX", "CHANGE_CONTENT", "load_change", "write_change", "change_ids", "open_change", "change_line", "fresh_sync", "begin_change", "change_diff", "issue_label", "change_comment", "change_start", "change_done", "undo_edits", "change_undo", "cmd_change", "cmd_reflect", "reflect_counts", "REFLECT_ON"),
    "fc_frame0": ("FRAME0_APP", "FRAME0_PORTS", "FRAME0_CLIENT", "frame0_port", "frame0_pid", "frame0_register", "frame0_command", "frame0_empty_doc", "frame0_up", "frame0_save", "frame0_down", "cmd_frame0"),
    "fc_crew": ("CREW_STATES", "CLI_REPO", "TOOL_BUGS", "crew_dir", "crew_reports", "tab_closed", "scratch_dir", "listeners_under", "stop_listeners_under", "TRUST_PROMPT", "crew_preamble", "crew_pick", "crew_pick_full", "crew_fallback", "crew_model", "crew_effort", "crew_workdir", "cmd_crew", "GUARDED_TOOLS", "GUARDED_ROLES", "CLI_FILE", "guard_decision", "cmd_guard", "SKILL_DIR", "SKILL_SEEN", "SKILL_FILES", "skill_hashes", "skill_changed", "skill_notice", "cmd_skillcheck", "write_report", "crew_unstart", "crew_record", "crew_reporting_to", "crew_reregister", "crew_attention", "desktop_notify", "manager_attention", "cmd_report", "log_tool_bug", "close_after_turn", "crew_closed", "TASK_TAB", "VERIFY_TAB", "teardown", "cmd_teardown"),
    "fc_init": ("FRAMELINK_ENV", "FRAMELINK_ADD", "GRAFT_INIT", "existing_repo", "setup_graft", "cmd_graft", "HERDR_MIN", "TREEHOUSE_MIN", "GRAFT_INSTALL", "DEPS", "user_mcp_servers", "version_of", "check_deps", "herdr_toml", "herdr_toast_warning", "cmd_doctor", "cmd_init", "merge_evidence", "merged_into", "own_commits", "live_crew", "clean_project", "cmd_clean"),
    "fc_figma": ("FIGMA_CONNECTOR", "FRAMELINK_SETUP", "framelink_fetch", "DESIGNER_BRIEF", "cmd_designer", "DESIGN_CONCURRENCY", "design_brief", "cmd_designcrews", "TREE_CHUNK_CHARS", "hard_split", "split_node", "tree_chunks", "combine_choices", "figma_judge_chunks", "figma_reask", "store_figma", "figma_tree", "cmd_figma"),
    "fc_briefs": ("detect_stacks", "GROUNDWORK_BRIEF", "cmd_groundwork", "WAYFINDER_BRIEF", "PLANNER_BRIEF", "CHANGE_BRIEF", "EXPLORE_BRIEF", "cmd_explore", "cmd_wayfinder", "cmd_planner", "TEST_BUDGET", "test_brief", "cmd_testcrews", "test_branch", "test_worktree", "collect_tests"),
    "fc_implement": ("implementer", "herdr_pi", "graft_pack", "branch_budget", "task_base", "PRETTIER_EXT", "format_files", "condense_failure", "HANG_HINT", "timed", "run_test", "cmd_timed", "run_task", "CONTRADICTION_RE", "contradiction"),
    "fc_jev": ("JEV_TIMEOUT", "TOOL_ERROR_RE", "tool_error", "stop_group", "kill_listeners", "harness_daemons", "end_new_daemons", "e2e_ports", "expand_ports", "driver_e2e", "jev_e2e"),
    "fc_verify": ("SIMPLICITY_BAR", "PERSPECTIVES", "llm_review", "JEV_CODE_CAP", "jev_acceptance", "verify_failed", "review_inputs", "e2e_stage", "run_stages", "verify_root", "cmd_verify", "fix_strays", "fix_message", "verify_rounds"),
    "fc_run": ("TRIAGE_BAR", "triage", "cmd_triage", "cmd_run", "preflight", "run_tasks", "reflect_task", "cmd_resume"),
    "fc_status": ("project_head", "task_state", "render_status", "project_summary", "cmd_projects", "cmd_cost", "cmd_status", "cmd_done", "cmd_top"),
    "fc_spec": ("file_clashes", "cmd_tasks", "run_waves", "spec_check", "cmd_spec_check", "MAX_TASK_FILES", "MAX_TASK_BRIEF", "too_big"),
    "fc_watch": ("YOLO_HINT", "FINAL_STATES", "watch_snapshot", "STALL_SECONDS", "watch_mem", "watch_save", "watch_lock", "watch_stalls", "watch_events", "yolo_mark", "watch_filter", "WATCH_INTERVAL", "cmd_watch", "cmd_rewake", "cmd_reenter"),
    "fc_yolo": ("YOLO_NEVER", "yolo_digest", "cmd_yolo"),
    "fc_bench": ("pct", "cmd_bench"),
}
HELPERS = {"fc_cost", "fc_mcp", "fc_sessions"}
SETDEFAULTS = ["os.environ.setdefault('GRAFT_NO_GITIGNORE', '1')", "os.environ.setdefault('GRAFT_NO_IGNORE', '1')"]
CONFIG_ONLY = ("DEFAULT_MODEL", "FALLBACK_MODEL", "OPENROUTER_KEY", "LINEAR_KEY", "WORKSPACE", "CREW_MODELS", "CREW_EFFORT", "CREW_FALLBACK")
LAUNCHER_SHA = "d44b3c09f228a368816f9b2ea6e6cecc7fd944ec28924e2fc9afbf1215438049"
SUBCOMMANDS = "doctor, init, run, verify, bench, resume, done, sync, tasks, spec-check, projects, cost, status, watch, top, stack, clean, groundwork, explore, graft, wayfinder, planner, testcrews, designer, designcrews, triage, reflect, hold, yolo, change, crew, report, models, frame0, figma, teardown, guard, rewake, reenter, skillcheck, workspace".split(", ")


def parse(name):
    return ast.parse((BIN / name).read_text())


def defined(tree):
    out = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(n.name)
        elif isinstance(n, ast.Assign):
            out += [x.id for t in n.targets for x in ast.walk(t) if isinstance(x, ast.Name)]
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.append(n.target.id)
    return out


def fc_imports(tree):
    """Every fc_* module named by an import anywhere in the file (always `import fc_x`, never `from fc_x import`)."""
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names |= {a.name for a in n.names if a.name.startswith("fc_")}
        elif isinstance(n, ast.ImportFrom) and (n.module or "").startswith("fc_"):
            names.add(n.module)
    return names


def expressions(tree):
    return [ast.unparse(n) for n in tree.body if isinstance(n, ast.Expr) and not isinstance(n.value, ast.Constant)]


def names(m):
    return [n for n in MODULES[m] if not n.startswith("EXPR_")]


def bad_refs(tree):
    """`fc_x.attr` uses whose fc_x is one of the 24 but is not imported here or does not define attr."""
    imported = fc_imports(tree)
    return sorted(
        f"{n.value.id}.{n.attr}"
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in MODULES
        and (n.value.id not in imported or n.attr not in MODULES[n.value.id])
    )


class ModuleChecks:
    module = ""

    def tree(self):
        path = BIN / f"{self.module}.py"
        self.assertTrue(path.exists(), f"{path.name} does not exist")
        return parse(path.name)

    def test_defines_exactly_its_names_in_order(self):
        self.assertEqual(defined(self.tree()), names(self.module))

    def test_imports_only_lower_rank(self):
        tree = self.tree()
        allowed = set(RANK[: RANK.index(self.module)]) | HELPERS
        self.assertLessEqual(fc_imports(tree), allowed)
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                self.assertFalse((n.module or "").startswith("fc_"), f"from {n.module} import ...")
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module]
                self.assertNotIn("fast_coding", mods)

    def test_collaborators_resolve(self):
        self.assertEqual(bad_refs(self.tree()), [])

    def test_at_most_600_lines(self):
        self.tree()
        self.assertLessEqual(len((BIN / f"{self.module}.py").read_text().splitlines()), 600)

    def test_gone_from_fast_coding(self):
        self.tree()
        fast = parse("fast_coding.py")
        self.assertEqual(set(names(self.module)) & set(defined(fast)), set())
        self.assertEqual(bad_refs(fast), [])


class FcCore(ModuleChecks, unittest.TestCase): module = "fc_core"
class FcConfig(ModuleChecks, unittest.TestCase):
    module = "fc_config"

    def test_setdefaults_moved(self):
        self.assertEqual(expressions(self.tree()), SETDEFAULTS)
        self.assertEqual(set(expressions(parse("fast_coding.py"))) & set(SETDEFAULTS), set())


class FcTasks(ModuleChecks, unittest.TestCase): module = "fc_tasks"
class FcLinear(ModuleChecks, unittest.TestCase): module = "fc_linear"
class FcClaude(ModuleChecks, unittest.TestCase): module = "fc_claude"
class FcModels(ModuleChecks, unittest.TestCase): module = "fc_models"
class FcHerdr(ModuleChecks, unittest.TestCase): module = "fc_herdr"
class FcWorktree(ModuleChecks, unittest.TestCase): module = "fc_worktree"
class FcLayers(ModuleChecks, unittest.TestCase): module = "fc_layers"
class FcChange(ModuleChecks, unittest.TestCase): module = "fc_change"
class FcFrame0(ModuleChecks, unittest.TestCase): module = "fc_frame0"
class FcCrew(ModuleChecks, unittest.TestCase): module = "fc_crew"
class FcInit(ModuleChecks, unittest.TestCase): module = "fc_init"
class FcFigma(ModuleChecks, unittest.TestCase): module = "fc_figma"
class FcBriefs(ModuleChecks, unittest.TestCase): module = "fc_briefs"
class FcImplement(ModuleChecks, unittest.TestCase): module = "fc_implement"
class FcJev(ModuleChecks, unittest.TestCase): module = "fc_jev"
class FcVerify(ModuleChecks, unittest.TestCase): module = "fc_verify"
class FcRun(ModuleChecks, unittest.TestCase): module = "fc_run"
class FcStatus(ModuleChecks, unittest.TestCase): module = "fc_status"
class FcSpec(ModuleChecks, unittest.TestCase): module = "fc_spec"
class FcWatch(ModuleChecks, unittest.TestCase): module = "fc_watch"
class FcYolo(ModuleChecks, unittest.TestCase): module = "fc_yolo"
class FcBench(ModuleChecks, unittest.TestCase): module = "fc_bench"


class Residue(unittest.TestCase):
    def test_fast_coding_keeps_only_the_entry_point(self):
        tree = parse("fast_coding.py")
        self.assertEqual(set(defined(tree)), {"DETACHED", "detach", "follow", "main"})
        self.assertEqual(expressions(tree), ["sys.path.insert(0, str(Path(__file__).resolve().parent))"])
        rest = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign, ast.Expr, ast.If))]
        self.assertEqual(rest, [])
        guards = [ast.unparse(n.test) for n in tree.body if isinstance(n, ast.If)]
        self.assertEqual(guards, ["__name__ == '__main__'"])

    def test_import_graph_is_acyclic_in_rank_order(self):
        for i, m in enumerate(RANK):
            with self.subTest(m):
                self.assertLessEqual(fc_imports(parse(f"{m}.py")), set(RANK[:i]) | HELPERS)

    def test_settings_have_one_owner(self):
        owners = {m: set(defined(parse(f"{m}.py"))) for m in RANK}
        owners["fast_coding"] = set(defined(parse("fast_coding.py")))
        for name, owner in [(n, "fc_config") for n in CONFIG_ONLY] + [("STACK_STOP", "fc_layers")]:
            with self.subTest(name):
                self.assertEqual([m for m, d in owners.items() if name in d], [owner])

    def test_launcher_unchanged(self):
        self.assertEqual(hashlib.sha256((BIN / "fast-coding").read_bytes()).hexdigest(), LAUNCHER_SHA)

    def test_help_lists_the_same_subcommands(self):
        out = subprocess.run(["/usr/bin/python3", str(BIN / "fast-coding"), "--help"], capture_output=True, text=True, check=True).stdout
        group = out[out.index("{") + 1 : out.index("}")]
        self.assertEqual(group.split(","), SUBCOMMANDS)


MODULE_CLASSES = {"fc_core": FcCore, "fc_config": FcConfig, "fc_tasks": FcTasks, "fc_linear": FcLinear, "fc_claude": FcClaude, "fc_models": FcModels, "fc_herdr": FcHerdr, "fc_worktree": FcWorktree, "fc_layers": FcLayers, "fc_change": FcChange, "fc_frame0": FcFrame0, "fc_crew": FcCrew, "fc_init": FcInit, "fc_figma": FcFigma, "fc_briefs": FcBriefs, "fc_implement": FcImplement, "fc_jev": FcJev, "fc_verify": FcVerify, "fc_run": FcRun, "fc_status": FcStatus, "fc_spec": FcSpec, "fc_watch": FcWatch, "fc_yolo": FcYolo, "fc_bench": FcBench}


def load_tests(loader, tests, pattern):
    if pattern is None:
        return tests
    suite = unittest.TestSuite()
    present = [m for m in RANK if (BIN / f"{m}.py").exists()]
    for m in present:
        suite.addTests(loader.loadTestsFromTestCase(MODULE_CLASSES[m]))
    if len(present) == len(RANK):
        suite.addTests(loader.loadTestsFromTestCase(Residue))
    return suite
