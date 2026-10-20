import hermetic  # first: no test sees the real home
import ast
import hashlib
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"

RANK = ("fc_core", "fc_prompt", "fc_proc", "fc_auth", "fc_config", "fc_tasks", "fc_plan", "fc_linear", "fc_linear_cmd", "fc_readguard", "fc_claude", "fc_models", "fc_herdr", "fc_worktree", "fc_checks", "fc_pi", "fc_keys", "fc_steps", "fc_layers", "fc_stack", "fc_change", "fc_frame0", "fc_crew", "fc_toolbug", "fc_init", "fc_herdrconf", "fc_links", "fc_defaults", "fc_steprun", "fc_finish", "fc_setup", "fc_update", "fc_figma", "fc_briefs", "fc_libapi", "fc_implement", "fc_jev", "fc_verify", "fc_run", "fc_status", "fc_spec", "fc_watch", "fc_yolo", "fc_bench")
MODULES = {
    "fc_core": ("now", "fmt", "say", "Ledger", "LEDGER", "sh", "worktrees", "repo_link", "project_config", "project_branch", "commit_convention", "COMMIT_TYPES", "typed", "commit_rule", "all_projects", "project_dir", "atomic_write", "SECRET_VARS", "SECRET_VALUES", "REDACTED", "clean_env", "SCRATCH_CONFIGS", "HOME_WRITES", "HOME_WRITES_MAX", "HOME_WRITES_SLACK", "HOME_HASH_MAX", "CLI_OWN", "CLI_CHECKOUT", "SCRATCH_PREFIX", "scratch_config", "is_scratch", "remove_scratch", "checkout_entries", "entry_state", "home_state", "note_home_write", "home_writes_outside", "flag_home", "scrub", "Scrubbed", "digests", "figma_key", "current_branch", "load_env", "free_port", "port_listening", "report_time", "session_id", "project_after", "tilde"),
    "fc_prompt": ("FRAMES", "paint", "intro", "bars", "note", "step", "outro", "select", "confirm", "password", "spin"),
    "fc_proc": ("STOP", "Stopped", "HOOKS", "RUNNING", "run", "kill_group", "stop", "on_termination", "SLOTS", "SLOT_SAY_AFTER", "slot"),
    "fc_auth": ("read_auth", "write_auth", "workspace_key", "set_key", "old_keys", "move_keys"),
    "fc_config": ("DEFAULT_MODEL", "FALLBACK_MODEL", "FALLBACK_AFTER", "TEST_READER", "JEV_DIR", "PRICES", "CONFIG_PATH", "ENV_FILE", "AUTH_PATH", "OPENROUTER_KEY", "MAX_DIFF_LINES", "DOC_RE", "DEP_DIRS", "EXPR_L36", "EXPR_L37", "CREW_MODELS", "PARALLEL", "LINEAR_KEY", "WORKSPACE", "CREW_EFFORT", "CREW_FALLBACK", "PLANNING_ROLES", "CREW_DEFAULTS", "PROBE_CACHE", "read_config", "write_config", "settings", "apply_config", "needs_linear_key", "typesafe_key", "openrouter_key", "key_file", "WORKSPACE_ACTIONS", "read_key", "cmd_workspace"),
    "fc_tasks": ("TASK_BLOCK", "SYNC_SHAPE", "task_from_issue", "hand_task", "sync_tasks", "linear_cache", "load_tasks", "blocker_finished", "waiting", "linear_done", "code_tasks", "FINISHED", "task_finished", "parse_criteria", "criteria_from_tasks", "_hold_warned", "held", "held_behind", "yolo_state", "yolo_by", "CANCELED", "run_marker", "pid_alive", "run_alive"),
    "fc_plan": ("heading_level", "headings", "section_span", "section_hash", "section_hashes", "replace_section", "PLAN_SECTIONS", "PLAN_NEXT", "plan_skeleton", "with_plan_link", "start_today", "lanes_text", "waves_text", "critical_path_text", "plan_sections"),
    "fc_linear": ("LINEAR_TREE_FIELDS", "LINEAR_FEATURE", "LINEAR_CHILDREN", "linear_children", "linear_sync_payload", "LINEAR_URL", "LINEAR_ISSUE", "_linear_warned", "linear_gql", "linear_issue", "linear_move", "linear_comment", "linear_ready", "linear_note", "LINEAR_BLOCKERS", "linear_blocked_by", "linear_restore", "rollup_state", "linear_roll_up", "linear_event", "linear_merged", "linear_reconcile", "ready_ids", "LINEAR_READY_TREE", "linear_mark_ready", "LINEAR_PLAN_TREE", "linear_plan", "ready_line", "cmd_ready", "refresh_ready", "linear_feature_after", "cmd_sync"),
    "fc_linear_cmd": ("issue_line", "read_body", "linear_project", "in_scope", "state_and_labels", "print_body", "writes_body", "new_body", "verb_project", "verb_get", "verb_list", "verb_create", "verb_update", "verb_comment", "verb_labels", "verb_doc", "cmd_linear"),
    "fc_readguard": ("PI_EXT", "OC_PLUGIN", "guard_file", "pack_paths", "write_guard", "command", "refusal", "refused", "cli"),
    "fc_claude": ("is_claude", "claude_id", "headless_env", "NO_ATTRIBUTION", "crew_settings", "REPO_INSTRUCTIONS", "repo_instructions", "claude_once", "claude_trusted", "untrusted"),
    "fc_models": ("opencode", "RATE_LIMIT_MARK", "pi_error", "pi_turn", "fallback_for", "PaymentRequired", "PAY_RE", "TOP_UP", "payment_check", "http_json", "RateLimited", "provider_busy", "parse_pi_session", "pi_turn_state", "_PROBED", "pi_id", "probe_command", "probe_result", "model_available", "TRANSIENT", "probe_once", "probe_clear", "cmd_models", "TEST_TIMEOUT", "TURN_TIMEOUT", "payment_halt", "lenient_json", "fast_env", "fast_json", "CUT_RETRY", "fast_json_whole", "EmptyReply", "CutOff", "BadReply", "fast_object", "ConfirmError", "confirm_call", "jev_ask", "reask_criterion"),
    "fc_herdr": ("HERDR_SPACES", "PI_HERDR_EXT", "herdr_env", "PANE_MAKERS", "herdr_argv", "herdr", "herdr_error", "herdr_text", "herdr_ready", "herdr_dialog", "herdr_await_start", "herdr_start_crew", "pane_processes", "pane_launching", "pane_kill", "agent_name", "agent_id", "agent_ref", "herdr_main_repo", "herdr_find_space", "project_worktree", "live_agents", "space_record", "tab_label", "MANAGER", "manager_projects", "herdr_name_manager", "herdr_unname_manager", "herdr_tab", "herdr_project_space", "herdr_project_tabs", "herdr_repo_space", "herdr_space", "herdr_tabs", "herdr_status_tab", "herdr_label", "IMPLEMENTERS_TAB", "herdr_implementer_pane", "herdr_agent_start", "PROMPT_START_WAIT", "herdr_stalled", "herdr_verify_panes", "herdr_stage", "herdr_space_is", "herdr_attach"),
    "fc_checks": ("owned_links", "link_state", "local_bin_on_path", "gh_authed", "rerere_set", "jev_synced", "chromium_installed"),
    "fc_pi": ("PI_MODELS", "PROVIDER", "TEXT_MODEL_DEFAULTS", "PI_AUTH", "has_glm", "provider_lacks", "provider_declared", "text_model_set", "pi_auth_overrides", "_read_provider", "declare_provider", "preview_provider", "write_text_model"),
    "fc_keys": ("key_status", "save_key", "skipped_line", "KEYS", "ask_keys"),
    "fc_steps": ("FRAMELINK_ENV", "FRAMELINK_ADD", "HERDR_MIN", "TREEHOUSE_MIN", "FLOORS", "user_mcp_servers", "version_of", "owned_link", "key_ok", "herdr_integration", "check", "STEPS"),
    "fc_worktree": ("task_prefix", "rename_legacy_branches", "task_branch", "own_branches", "replace_branch", "replaced_tips", "task_branches", "layer_order", "stack_order", "TREEHOUSE_INSTALL", "use_treehouse", "treehouse", "slot_on", "pool_shortfall", "is_slot", "default_branch", "review_base", "release_slot", "common_dir", "repo_worktree", "slots", "stack_worktree", "exclude_paths", "TOOL_DIRS", "WIRING", "dirty_paths", "graph_dir", "ignore_tool_files", "dep_dirs", "stamp_trail_wiring", "ready_checkout", "names_lockfile", "adopt_installs", "STACK_LOCK", "GENERATED_RE", "LOCKFILE_RE", "LOCKFILES"),
    "fc_layers": ("CONFIG_FILE_RE", "layer_prefix", "commit_message", "chain_order", "STACK_STOP", "linearize", "_linearize", "REVIEW_LAYER_LINES", "commit_facts", "group_units", "test_writers", "applies_without", "review_units", "cherry_pick_same", "record_layers", "group_by_record", "build_layers", "layer_note"),
    "fc_stack": ("TITLE_CHARS", "clip", "title_prefix", "layer_title", "WHY_CHARS", "GITHUB_ISSUE_RE", "plain", "title_text", "sentence", "first_sentence", "issue_refs", "linear_url", "story_of", "issue_lines", "layer_why", "layer_body", "pr_names", "ISSUE_LINE_RE", "pr_text", "layer_pr", "stale_pr_files", "gh_pr_text", "write_pr_text", "register_stack", "cmd_stack"),
    "fc_change": ("REFLECT_THRESHOLD", "REFLECT_EVIDENCE_CAP", "REFLECT_LOCK", "REFLECT_CHOICES", "REFLECT_RULES", "map_section", "LIST_ITEM", "decision_lines", "changes_dir", "last_change_done", "evidence_cut", "evidence_since", "reflect", "cmd_hold", "CHANGE_SYNC_MAX", "CHANGE_CONTENT", "load_change", "write_change", "change_ids", "open_change", "change_line", "fresh_sync", "begin_change", "change_diff", "issue_label", "change_comment", "change_start", "change_done", "undo_edits", "change_undo", "cmd_change", "cmd_reflect", "reflect_counts", "REFLECT_ON"),
    "fc_frame0": ("FRAME0_APP", "FRAME0_PORTS", "FRAME0_CLIENT", "FRAME0_WAIT", "frame0_port", "frame0_pid", "frame0_register", "frame0_post", "frame0_command", "frame0_proxy", "frame0_mcp", "frame0_empty_doc", "frame0_up", "frame0_save", "frame0_down", "cmd_frame0"),
    "fc_crew": ("CREW_STATES", "CLI_REPO", "TOOL_BUGS", "crew_dir", "crew_reports", "tab_closed", "scratch_dir", "listeners_under", "stop_listeners_under", "TRUST_PROMPT", "crew_preamble", "crew_pick", "crew_pick_full", "crew_fallback", "crew_model", "crew_effort", "crew_workdir", "cmd_crew", "GUARDED_TOOLS", "GUARDED_ROLES", "CLI_FILE", "guard_decision", "cmd_guard", "SKILL_DIR", "SKILL_SEEN", "SKILL_FILES", "skill_hashes", "skill_changed", "skill_notice", "cmd_skillcheck", "write_report", "crew_unstart", "crew_record", "crew_up", "crew_reporting_to", "crew_reregister", "crew_attention", "desktop_notify", "manager_attention", "cmd_report", "log_tool_bug", "close_after_turn", "finish_clean_after_turn", "crew_closed", "TASK_TAB", "VERIFY_TAB", "teardown", "cmd_teardown"),
    "fc_toolbug": ("REPO", "SECTIONS", "TOKEN_RE", "scrub", "environment", "issue_text", "gh_status", "open_matches", "post", "record_issue", "cmd_tool_bug"),
    "fc_init": ("TRAIL_INIT", "existing_repo", "setup_trail", "cmd_trail", "TRAIL_INSTALL", "check_deps", "herdr_toml", "herdr_loud", "herdr_toast_warning", "cmd_doctor", "created_from", "move_onto", "cmd_init", "merge_evidence", "merged_into", "first_unmatched", "own_commits", "live_crew", "standing_in", "remove_project", "close_space", "clean_project", "cmd_clean"),
    "fc_herdrconf": ("QUIET", "apply_herdr_config", "_edited"),
    "fc_links": ("ensure_link", "relink_owned", "path_line"),
    "fc_defaults": ("DEFAULT_MODELS", "PRESET_STEPS", "merge_models", "probe_implementer"),
    "fc_steprun": ("link_writer", "WRITERS", "PREVIEWS", "run_step", "_run_step"),
    "fc_finish": ("CLAUDE_MISSING", "finish", "_finish"),
    "fc_setup": ("MODES", "walk_steps", "run_setup", "cmd_setup"),
    "fc_update": ("diverged", "cmd_update"),
    "fc_figma": ("FIGMA_CONNECTOR", "FRAMELINK_SETUP", "framelink_fetch", "DESIGNER_BRIEF", "cmd_designer", "DESIGN_CONCURRENCY", "design_brief", "cmd_designcrews", "TREE_CHUNK_CHARS", "hard_split", "split_node", "tree_chunks", "CONFIRM_TREE_CHARS", "TREE_READING", "TREE_CHOICES", "PART_CHOICES", "TREE_RULES", "PART_RULES", "CONFIRM", "CONFIRM_PART", "combine_choices", "confirm_asks", "figma_judge_chunks", "figma_reask", "store_figma", "STYLE_KEYS", "GENERATED_STYLE", "walk", "put", "inline_styles", "sub_id", "renamed", "restore_hidden", "self_contained", "figma_tree", "cmd_figma"),
    "fc_briefs": ("detect_stacks", "GROUNDWORK_BRIEF", "cmd_groundwork", "WAYFINDER_BRIEF", "PLANNER_BRIEF", "TOOLSMITH_BRIEF", "CHANGE_BRIEF", "EXPLORE_BRIEF", "cmd_explore", "cmd_wayfinder", "cmd_planner", "cmd_toolsmith", "TEST_BUDGET", "test_brief", "cmd_testcrews", "test_branch", "test_open", "waiting_writers", "test_written", "test_blockers", "test_ready", "test_worktree", "collect_tests"),
    "fc_libapi": ("INSPECT", "python_api", "js_api", "section"),
    "fc_implement": ("implementer", "herdr_pi", "LEARNING_RE", "BANNERS", "trail_pack", "branch_budget", "task_base", "PRETTIER_EXT", "prettier_opted_in", "format_files", "READER_TIMEOUT", "read_failure", "HANG_HINT", "timed", "run_test", "cmd_timed", "run_task", "CONTRADICTION_RE", "contradiction"),
    "fc_jev": ("JEV_TIMEOUT", "TOOL_ERROR_RE", "tool_error", "stop_group", "kill_listeners", "harness_daemons", "end_new_daemons", "e2e_ports", "expand_ports", "alive", "reap_orphans", "SETUP_DEADLINE", "await_setup", "case_setup", "driver_e2e", "jev_e2e", "say_case"),
    "fc_verify": ("SIMPLICITY_BAR", "PERSPECTIVES", "well_formed", "llm_review", "JEV_CODE_CAP", "jev_acceptance", "verify_failed", "review_inputs", "e2e_stage", "fix_tests", "run_stages", "verify_root", "at_root", "cmd_verify", "fix_strays", "fix_message", "changed_files", "verify_rounds"),
    "fc_run": ("TRIAGE_BAR", "triage", "cmd_triage", "RUN_PARALLEL", "require_committed", "cmd_run", "preflight", "run_tasks", "reflect_task", "cmd_resume"),
    "fc_status": ("project_head", "branch_facts", "task_state", "_git_dirs", "git_dirs", "board_stamp", "_board", "board", "render_status", "project_summary", "cmd_projects", "cmd_cost", "cmd_status", "cmd_done", "cmd_top"),
    "fc_spec": ("file_clashes", "cmd_tasks", "run_waves", "spec_check", "cmd_spec_check", "MAX_TASK_FILES", "MAX_TASK_BRIEF", "too_big"),
    "fc_watch": ("YOLO_HINT", "FINAL_STATES", "AGENTS_INTERVAL", "Agents", "watch_snapshot", "crew_owners", "STALL_SECONDS", "watch_mem", "watch_save", "watch_lock", "watch_stalls", "watch_events", "yolo_mark", "watch_filter", "WATCH_INTERVAL", "watch_key", "watch_scope", "cmd_watch", "cmd_rewake", "crew_in_pane", "cmd_reenter"),
    "fc_yolo": ("YOLO_NEVER", "yolo_digest", "cmd_yolo"),
    "fc_bench": ("pct", "cmd_bench"),
}
HELPERS = {"fc_cost", "fc_mcp", "fc_sessions"}
SETDEFAULTS = ["os.environ.setdefault('GRAFT_NO_GITIGNORE', '1')", "os.environ.setdefault('GRAFT_NO_IGNORE', '1')"]
CONFIG_ONLY = ("DEFAULT_MODEL", "FALLBACK_MODEL", "FALLBACK_AFTER", "TEST_READER", "OPENROUTER_KEY", "LINEAR_KEY", "WORKSPACE", "CREW_MODELS", "CREW_EFFORT", "CREW_FALLBACK")
LAUNCHER_SHA = "6da43b058089b473dce7bba234756d8af893868a06c45fa7cc8a0280ae40f676"
SUBCOMMANDS = "doctor, setup, update, init, run, verify, bench, resume, done, sync, linear, tasks, spec-check, ready, projects, cost, status, watch, top, stack, clean, groundwork, explore, trail, wayfinder, planner, testcrews, designer, designcrews, triage, reflect, hold, yolo, change, crew, report, tool-bug, toolsmith, models, frame0, figma, teardown, guard, rewake, reenter, skillcheck, workspace".split(", ")


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
    """`fc_x.attr` uses whose fc_x is a ranked module but is not imported here or does not define attr."""
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
                self.assertNotIn("compose", mods)

    def test_collaborators_resolve(self):
        self.assertEqual(bad_refs(self.tree()), [])

    def test_at_most_600_lines(self):
        self.tree()
        self.assertLessEqual(len((BIN / f"{self.module}.py").read_text().splitlines()), 600)

    def test_gone_from_compose(self):
        self.tree()
        entry = parse("compose.py")
        self.assertEqual(set(names(self.module)) & set(defined(entry)), set())
        self.assertEqual(bad_refs(entry), [])


class FcCore(ModuleChecks, unittest.TestCase): module = "fc_core"
class FcPrompt(ModuleChecks, unittest.TestCase): module = "fc_prompt"
class FcProc(ModuleChecks, unittest.TestCase): module = "fc_proc"
class FcAuth(ModuleChecks, unittest.TestCase): module = "fc_auth"
class FcConfig(ModuleChecks, unittest.TestCase):
    module = "fc_config"

    def test_setdefaults_moved(self):
        self.assertEqual(expressions(self.tree()), SETDEFAULTS)
        self.assertEqual(set(expressions(parse("compose.py"))) & set(SETDEFAULTS), set())


class FcTasks(ModuleChecks, unittest.TestCase): module = "fc_tasks"
class FcPlan(ModuleChecks, unittest.TestCase): module = "fc_plan"
class FcLinear(ModuleChecks, unittest.TestCase): module = "fc_linear"
class FcLinearCmd(ModuleChecks, unittest.TestCase): module = "fc_linear_cmd"
class FcReadguard(ModuleChecks, unittest.TestCase): module = "fc_readguard"
class FcClaude(ModuleChecks, unittest.TestCase): module = "fc_claude"
class FcModels(ModuleChecks, unittest.TestCase): module = "fc_models"
class FcHerdr(ModuleChecks, unittest.TestCase): module = "fc_herdr"
class FcWorktree(ModuleChecks, unittest.TestCase): module = "fc_worktree"
class FcChecks(ModuleChecks, unittest.TestCase): module = "fc_checks"
class FcPi(ModuleChecks, unittest.TestCase): module = "fc_pi"
class FcKeys(ModuleChecks, unittest.TestCase): module = "fc_keys"
class FcSteps(ModuleChecks, unittest.TestCase): module = "fc_steps"
class FcLayers(ModuleChecks, unittest.TestCase): module = "fc_layers"
class FcStack(ModuleChecks, unittest.TestCase): module = "fc_stack"
class FcChange(ModuleChecks, unittest.TestCase): module = "fc_change"
class FcFrame0(ModuleChecks, unittest.TestCase): module = "fc_frame0"
class FcCrew(ModuleChecks, unittest.TestCase): module = "fc_crew"
class FcToolbug(ModuleChecks, unittest.TestCase): module = "fc_toolbug"
class FcInit(ModuleChecks, unittest.TestCase):
    module = "fc_init"

    def test_cmd_trail_sets_trail_up_in_the_project_worktree(self):
        sys.path.insert(0, str(BIN))
        import fc_core, fc_herdr, fc_init

        a = object()
        with mock.patch.object(fc_core, "project_dir", return_value=Path("/p")) as pd, \
             mock.patch.object(fc_herdr, "project_worktree", return_value=Path("/wt")) as pw, \
             mock.patch.object(fc_init, "setup_trail") as st:
            fc_init.cmd_trail(a)
        pd.assert_called_once_with(a)
        pw.assert_called_once_with(Path("/p"))
        st.assert_called_once_with(Path("/wt"))
class FcHerdrconf(ModuleChecks, unittest.TestCase): module = "fc_herdrconf"
class FcLinks(ModuleChecks, unittest.TestCase): module = "fc_links"
class FcDefaults(ModuleChecks, unittest.TestCase): module = "fc_defaults"
class FcSteprun(ModuleChecks, unittest.TestCase): module = "fc_steprun"
class FcFinish(ModuleChecks, unittest.TestCase): module = "fc_finish"
class FcSetup(ModuleChecks, unittest.TestCase): module = "fc_setup"
class FcUpdate(ModuleChecks, unittest.TestCase): module = "fc_update"
class FcFigma(ModuleChecks, unittest.TestCase): module = "fc_figma"
class FcBriefs(ModuleChecks, unittest.TestCase): module = "fc_briefs"
class FcLibapi(ModuleChecks, unittest.TestCase): module = "fc_libapi"
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
    def test_compose_keeps_only_the_entry_point(self):
        tree = parse("compose.py")
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
        owners["compose"] = set(defined(parse("compose.py")))
        for name, owner in [(n, "fc_config") for n in CONFIG_ONLY] + [("STACK_STOP", "fc_layers")]:
            with self.subTest(name):
                self.assertEqual([m for m, d in owners.items() if name in d], [owner])

    def test_launcher_unchanged(self):
        self.assertEqual(hashlib.sha256((BIN / "compose").read_bytes()).hexdigest(), LAUNCHER_SHA)

    def test_help_lists_the_same_subcommands(self):
        out = subprocess.run(["/usr/bin/python3", str(BIN / "compose"), "--help"], capture_output=True, text=True, check=True).stdout
        self.assertEqual(re.findall(r"^    ([a-z][\w-]*)(?: |$)", out.split("positional arguments:")[1], re.M), SUBCOMMANDS)

    def test_help_names_trail_not_graft(self):
        env = {**os.environ, "COLUMNS": "400"}
        out = subprocess.run(["/usr/bin/python3", str(BIN / "compose"), "--help"], capture_output=True, text=True, check=True, env=env).stdout
        lines = [" ".join(line.split()) for line in out.splitlines()]
        self.assertIn("trail set trail up in the project's worktree again: wire it for Claude Code and build the graph", lines)
        self.assertIn("explore print the explore teammate's brief (a fast trail-only map of an existing repo); --extra adds notes", lines)
        self.assertEqual(re.findall(r"(?<![\w/.@-])graft(?![\w/-])", out), [])
        self.assertIn("graft/", out)

    def test_old_graft_subcommand_is_rejected(self):
        env = {**os.environ, "COMPOSE_NO_GRAFT": "1", "COMPOSE_NO_TRAIL": "1"}
        p = subprocess.run(["/usr/bin/python3", str(BIN / "compose"), "graft", "--project", "no-such-project"], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 2)
        self.assertIn("invalid choice: 'graft'", p.stderr)


class TestModules(unittest.TestCase):
    def test_every_test_module_clears_herdr_env(self):
        """Run from a herdr pane, a test that reaches herdr_space would open a real space; discover never imports tests/__init__.py."""
        for f in sorted((ROOT / "tests").glob("test_*.py")):
            with self.subTest(f.name):
                self.assertRegex(f.read_text(), r'(?m)^os\.environ\["HERDR_ENV"\] = ""$')


MODULE_CLASSES = {"fc_core": FcCore, "fc_prompt": FcPrompt, "fc_proc": FcProc, "fc_auth": FcAuth, "fc_config": FcConfig, "fc_tasks": FcTasks, "fc_plan": FcPlan, "fc_linear": FcLinear, "fc_linear_cmd": FcLinearCmd, "fc_readguard": FcReadguard, "fc_claude": FcClaude, "fc_models": FcModels, "fc_herdr": FcHerdr, "fc_worktree": FcWorktree, "fc_checks": FcChecks, "fc_pi": FcPi, "fc_keys": FcKeys, "fc_steps": FcSteps, "fc_layers": FcLayers, "fc_stack": FcStack, "fc_change": FcChange, "fc_frame0": FcFrame0, "fc_crew": FcCrew, "fc_toolbug": FcToolbug, "fc_init": FcInit, "fc_herdrconf": FcHerdrconf, "fc_links": FcLinks, "fc_defaults": FcDefaults, "fc_steprun": FcSteprun, "fc_finish": FcFinish, "fc_setup": FcSetup, "fc_update": FcUpdate, "fc_figma": FcFigma, "fc_briefs": FcBriefs, "fc_libapi": FcLibapi, "fc_implement": FcImplement, "fc_jev": FcJev, "fc_verify": FcVerify, "fc_run": FcRun, "fc_status": FcStatus, "fc_spec": FcSpec, "fc_watch": FcWatch, "fc_yolo": FcYolo, "fc_bench": FcBench}


def load_tests(loader, tests, pattern):
    if pattern is None:
        return tests
    suite = unittest.TestSuite()
    present = [m for m in RANK if (BIN / f"{m}.py").exists()]
    for m in present:
        suite.addTests(loader.loadTestsFromTestCase(MODULE_CLASSES[m]))
    if len(present) == len(RANK):
        suite.addTests(loader.loadTestsFromTestCase(Residue))
    suite.addTests(loader.loadTestsFromTestCase(TestModules))
    return suite
