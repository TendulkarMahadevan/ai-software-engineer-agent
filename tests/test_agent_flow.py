import contextlib
import importlib
import io
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from agent.keyword_extractor import KeywordExtractor
from tools.repo_search_tool import RepoSearchTool
from utils.git_manager import GitManager

ORIGINAL = '''ABBRS = {
    "a",
    "b",
    "c",
    "d",
    "e",
}


class Rules:
    pass
'''

TRIVIAL_CHANGE = ORIGINAL.replace('"a",', '"aa",')            # 1 line changed
BIGGER_CHANGE = (ORIGINAL.replace('"a",', '"aa",').replace('"b",', '"bb",')
                 .replace('"c",', '"cc",').replace('"d",', '"dd",'))   # 4 lines changed


def git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True)


def make_git_repo(files):
    repo = tempfile.mkdtemp()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "tester")
    for rel, text in files.items():
        with open(os.path.join(repo, rel), "w", encoding="utf-8") as f:
            f.write(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def result(status, kind="", reason=""):
    return {"returncode": 0 if status == "passed" else 1, "stdout": "", "stderr": "",
            "status": status, "runner": "python (pytest)", "kind": kind, "reason": reason}


class GitManagerDiffTests(unittest.TestCase):
    def test_diff_against_base_covers_every_commit_since(self):
        repo = make_git_repo({"a.py": "x = 1\n"})
        manager = GitManager()
        base = manager.head_sha(repo)
        for value in (2, 3):
            with open(os.path.join(repo, "a.py"), "w") as f:
                f.write(f"x = {value}\n")
            manager.commit_changes(repo, f"set {value}")
        self.assertIn("-x = 1", manager.get_diff(repo, base))
        self.assertIn("+x = 3", manager.get_diff(repo, base))
        # the old default only sees the last commit
        self.assertNotIn("-x = 1", manager.get_diff(repo))


class AgentFlowTests(unittest.TestCase):
    """Runs CodeAgent.run with fakes for the network, the LLM and the test runner."""

    @classmethod
    def setUpClass(cls):
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "x"}):
            cls.module = importlib.import_module("agent.code_agent")

    def build(self, llm_replies):
        repo = make_git_repo({"rules.py": ORIGINAL})
        agent = self.module.CodeAgent.__new__(self.module.CodeAgent)
        agent.trust_repo_config = False
        agent.github = mock.Mock()
        agent.github.get_issue.return_value = {"title": "Handle abbreviation",
                                               "body": "Add it to `ABBRS` in the rules."}
        agent.llm = mock.Mock()
        agent.llm.generate.side_effect = list(llm_replies)
        agent.search = RepoSearchTool()
        agent.extractor = mock.Mock()
        agent.pr_writer = mock.Mock()
        agent.pr_writer.generate_pr.return_value = "PR TEXT"
        agent.keyword_extractor = mock.Mock()
        agent.keyword_extractor.extract.return_value = ["rules"]
        agent.keyword_extractor.extract_identifiers = KeywordExtractor.extract_identifiers
        agent.git_manager = GitManager()
        agent.git_manager.clone_repo = lambda owner, name: repo
        return agent

    def run_agent(self, agent, runner_results):
        with mock.patch.object(self.module.TestRunner, "run_tests",
                               side_effect=list(runner_results)) as runner, \
             contextlib.redirect_stdout(io.StringIO()) as out:
            agent.run("owner", "repo", 1)
        return runner, out.getvalue()

    def test_guards_judge_the_final_diff_after_a_retry(self):
        # First attempt is a 1-line change (would be 'trivial'); the retry makes a real change.
        agent = self.build(["analysis", TRIVIAL_CHANGE, BIGGER_CHANGE])
        _, out = self.run_agent(agent, [result("passed"), result("failed"), result("passed")])

        self.assertNotIn("Only trivial changes detected", out)
        self.assertIn("FINAL LOCAL GIT DIFF", out)
        agent.pr_writer.generate_pr.assert_called_once()
        diff_sent_to_pr = agent.pr_writer.generate_pr.call_args.args[1]
        self.assertIn('+    "dd",', diff_sent_to_pr)

    def test_a_retry_that_undoes_the_change_is_not_written_up_as_a_fix(self):
        agent = self.build(["analysis", BIGGER_CHANGE, ORIGINAL])
        _, out = self.run_agent(agent, [result("passed"), result("failed"), result("passed")])
        agent.pr_writer.generate_pr.assert_not_called()

    def test_import_error_after_the_patch_counts_as_failure_and_is_retried(self):
        agent = self.build(["analysis", BIGGER_CHANGE, BIGGER_CHANGE.replace('"aa"', '"a1"')])
        broken = result("error", "collection_import", "pytest could not import a module (boom)")
        _, out = self.run_agent(agent, [result("passed"), broken, result("passed")])
        self.assertEqual(agent.llm.generate.call_count, 3)   # analysis, rewrite, retry
        self.assertIn("The change broke an import", out)

    def test_baseline_setup_error_skips_tests_retry_and_pr(self):
        agent = self.build(["analysis", BIGGER_CHANGE])
        setup = result("error", "collection_import", "pytest could not import a module (langcodes)")
        runner, out = self.run_agent(agent, [setup])
        self.assertEqual(runner.call_count, 1)                # only the baseline ran
        self.assertEqual(agent.llm.generate.call_count, 2)    # analysis and rewrite, no retry
        agent.pr_writer.generate_pr.assert_not_called()
        self.assertIn("Reason: pytest could not import a module (langcodes)", out)
        self.assertIn("Not generating PR text", out)


if __name__ == "__main__":
    unittest.main()
