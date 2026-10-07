import os
import tempfile
import unittest
from unittest import mock

from agent.keyword_extractor import KeywordExtractor
from tools.repo_search_tool import RepoSearchTool, _definition_pattern, is_test_file
from utils import test_runner as tr
from utils.test_runner import TestRunner


def make_repo(files):
    root = tempfile.mkdtemp()
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return root


class PytestSetupTests(unittest.TestCase):
    def test_cov_in_addopts_requires_pytest_cov(self):
        repo = make_repo({"pyproject.toml": '[tool.pytest.ini_options]\naddopts = "--cov=pkg -q"\n'})
        self.assertEqual(TestRunner._required_pytest_plugins(repo), ["pytest-cov"])

    def test_xdist_and_timeout_detected(self):
        repo = make_repo({"pytest.ini": "[pytest]\naddopts = -n auto --timeout=60\n"})
        self.assertEqual(TestRunner._required_pytest_plugins(repo), ["pytest-xdist", "pytest-timeout"])

    def test_no_addopts_needs_no_plugins(self):
        repo = make_repo({"pyproject.toml": "[project]\nname='x'\n"})
        self.assertEqual(TestRunner._required_pytest_plugins(repo), [])

    def test_test_extra_prefers_test_over_dev(self):
        repo = make_repo({"pyproject.toml": (
            "[project]\nname='x'\n[project.optional-dependencies]\n"
            'dev = ["ruff"]\ntest = ["pytest"]\n')})
        self.assertEqual(TestRunner._test_extra(repo), "test")

    def test_dev_extra_used_when_only_option(self):
        repo = make_repo({"pyproject.toml": (
            "[project]\nname='x'\n[project.optional-dependencies]\ndev = [\"pytest\"]\ndocs = []\n")})
        self.assertEqual(TestRunner._test_extra(repo), "dev")

    def test_no_extras_returns_none(self):
        repo = make_repo({"pyproject.toml": "[project]\nname='x'\n"})
        self.assertIsNone(TestRunner._test_extra(repo))

    def test_plan_installs_extra_and_plugin(self):
        repo = make_repo({"pyproject.toml": (
            '[project]\nname="x"\n[project.optional-dependencies]\ndev=["pytest"]\n'
            '[tool.pytest.ini_options]\naddopts = "--cov=x"\n')})
        name, cmds, _test, _env = TestRunner._build_plan(repo, {})
        flat = [" ".join(c) for c in cmds]
        self.assertEqual(name, tr.PYTEST_NAME)
        self.assertTrue(any("pytest pytest-cov" in c for c in flat))
        self.assertTrue(any(c.endswith("-e .[dev]") for c in flat))

    def test_existing_venv_is_not_recreated(self):
        repo = make_repo({"pyproject.toml": "[project]\nname='x'\n"})
        bin_dir = "Scripts" if os.name == "nt" else "bin"
        py = os.path.join(repo, ".ai_agent_venv", bin_dir, "python")
        os.makedirs(os.path.dirname(py))
        open(py, "w").close()
        _name, cmds, _t, _e = TestRunner._build_plan(repo, {})
        self.assertFalse(any(cmd[1:3] == ["-m", "venv"] for cmd in cmds))


class StatusMappingTests(unittest.TestCase):
    def run_with(self, test_returncode):
        repo = make_repo({"pyproject.toml": "[project]\nname='x'\n"})
        calls = []

        def fake_run(cmd, cwd, env, timeout):
            calls.append(cmd)
            is_test = "pytest" in cmd and "-x" in cmd
            rc = test_returncode if is_test else 0
            return {"returncode": rc, "stdout": "", "stderr": "usage: pytest" if is_test else "",
                    "status": tr.PASSED if rc == 0 else tr.FAILED}

        with mock.patch.object(TestRunner, "_run", side_effect=fake_run):
            return TestRunner.run_tests(repo), calls, repo

    def test_usage_error_is_setup_error_not_failure(self):
        result, _, _ = self.run_with(4)
        self.assertEqual(result["status"], tr.ERROR)
        self.assertIn("setup problem", result["stderr"])

    def test_real_failure_stays_failed(self):
        result, _, _ = self.run_with(1)
        self.assertEqual(result["status"], tr.FAILED)

    def test_no_tests_collected(self):
        result, _, _ = self.run_with(5)
        self.assertEqual(result["status"], tr.NO_TESTS)

    def test_pass(self):
        result, _, _ = self.run_with(0)
        self.assertEqual(result["status"], tr.PASSED)
        self.assertEqual(result["returncode"], 0)

    def test_failed_install_is_setup_error(self):
        repo = make_repo({"pyproject.toml": "[project]\nname='x'\n"})
        bad = {"returncode": 1, "stdout": "", "stderr": "no matching distribution", "status": tr.FAILED}
        with mock.patch.object(TestRunner, "_run", return_value=bad):
            result = TestRunner.run_tests(repo)
        self.assertEqual(result["status"], tr.ERROR)
        self.assertIn("Install step failed", result["stderr"])

    def test_install_runs_once_per_clone(self):
        result, calls, repo = self.run_with(0)
        first = len(calls)
        with mock.patch.object(TestRunner, "_run", return_value={
                "returncode": 0, "stdout": "", "stderr": "", "status": tr.PASSED}) as run:
            TestRunner.run_tests(repo)
        self.assertGreater(first, 1)
        self.assertEqual(run.call_count, 1)  # only the test command, no reinstall

    def test_venv_and_marker_kept_out_of_git(self):
        repo = make_repo({"pyproject.toml": "[project]\nname='x'\n", ".git/info/exclude": "# existing"})
        TestRunner._exclude_from_git(repo)
        TestRunner._exclude_from_git(repo)  # idempotent
        with open(os.path.join(repo, ".git", "info", "exclude")) as f:
            text = f.read()
        self.assertEqual(text.count(".ai_agent_venv/"), 1)
        self.assertEqual(text.count(".ai_agent_installed"), 1)
        self.assertTrue(text.startswith("# existing"))


class IdentifierTests(unittest.TestCase):
    def test_finds_constants_classes_and_backticked(self):
        text = ("`v.s.` is split by the BoundaryDetector. INLINE_ONLY_ABBRVS has `vs.` "
                "but `Rules.INLINE_ONLY_ABBRVS` needs it; see build_pattern and API.")
        found = KeywordExtractor.extract_identifiers(text)
        self.assertIn("INLINE_ONLY_ABBRVS", found)
        self.assertIn("BoundaryDetector", found)
        self.assertIn("build_pattern", found)
        self.assertNotIn("API", found)
        self.assertEqual(len(found), len(set(found)))

    def test_plain_prose_yields_nothing(self):
        self.assertEqual(KeywordExtractor.extract_identifiers("The button is broken on Safari."), [])


class DefinitionTests(unittest.TestCase):
    def test_pattern_matches_definitions_not_uses(self):
        pat = _definition_pattern("MAX_SIZE")
        for line in ("MAX_SIZE = 10", "    MAX_SIZE: int = 10", "const MAX_SIZE = 10;",
                     "    MAX_SIZE = Base.MAX_SIZE | {1}"):
            self.assertTrue(pat.match(line), line)
        for line in ("x = MAX_SIZE", "foo(MAX_SIZE)", "if MAX_SIZE == 3:", "# MAX_SIZE = 1"):
            self.assertFalse(pat.match(line), line)

    def test_functions_classes_and_go_methods(self):
        self.assertTrue(_definition_pattern("run").match("def run(self):"))
        self.assertTrue(_definition_pattern("Foo").match("class Foo(Base):"))
        self.assertTrue(_definition_pattern("run").match("func (s *Server) run() {"))
        self.assertFalse(_definition_pattern("run").match("    self.run()"))

    def test_base_definition_beats_subclasses_and_users(self):
        repo = make_repo({
            "src/detector.py": "from rules import Rules\nuse = Rules.ABBRS\nprint(ABBRS)\n",
            "src/rules/base.py": "class Rules:\n    ABBRS = {\n        'vs.',\n    }\n",
            "src/rules/af.py": "class Af(Rules):\n    ABBRS = Rules.ABBRS | {'a.'}\n",
            "node_modules/pkg/x.js": "const ABBRS = 1;\n",
        })
        scores = RepoSearchTool().find_definitions(repo, ["ABBRS"])
        self.assertEqual(set(scores), {os.path.join("src", "rules", "base.py"),
                                       os.path.join("src", "rules", "af.py")})
        self.assertGreater(scores[os.path.join("src", "rules", "base.py")],
                           scores[os.path.join("src", "rules", "af.py")])

    def test_parent_wins_tie_with_unrelated_root_definition(self):
        repo = make_repo({
            "rules/base.py": "class Rules:\n    ABBRS = {'vs.'}\n",
            "rules/hy.py": "class HyRules(Rules):\n    ABBRS = set()\n",
            "rules/af.py": "class AfRules(Rules):\n    ABBRS = Rules.ABBRS | {'a.'}\n",
        })
        scores = RepoSearchTool().find_definitions(repo, ["ABBRS"])
        ranked = sorted(scores, key=scores.get, reverse=True)
        self.assertEqual(ranked[0], os.path.join("rules", "base.py"))

    def test_no_identifiers_no_definitions(self):
        repo = make_repo({"a.py": "x = 1\n"})
        self.assertEqual(RepoSearchTool().find_definitions(repo, ["MISSING_NAME"]), {})

    def test_is_test_file_still_works(self):
        self.assertTrue(is_test_file("tests/test_a.py"))
        self.assertFalse(is_test_file("src/contest.go"))


if __name__ == "__main__":
    unittest.main()
