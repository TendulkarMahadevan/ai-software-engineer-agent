import os
import re
from tools.github_tool import GitHubTool
from tools.repo_search_tool import RepoSearchTool, is_test_file
from tools.context_extractor import ContextExtractor
from patch.pr_writer import PRWriter
from llm.openai_client import LLMClient
from utils.git_manager import GitManager
from agent.keyword_extractor import KeywordExtractor
from utils.test_runner import TestRunner

class CodeAgent:

    def __init__(self):
        self.github = GitHubTool()
        self.search = RepoSearchTool()
        self.extractor = ContextExtractor()
        self.llm = LLMClient()
        self.pr_writer = PRWriter(self.llm)
        self.keyword_extractor = KeywordExtractor(self.llm)
        self.git_manager = GitManager()

    def run(self, owner, repo, issue_number):
        print("Fetching issue...")
        issue = self.github.get_issue(owner, repo, issue_number)
        issue_text = issue["title"] + "\n" + (issue.get("body") or "")
        
        print("[AI-ENGINEER] Analyzing issue type...")

        analysis_prompt = f"""
        Analyze the following GitHub issue.

        Classify:
        1. What layer is affected? (api, routing, dispatch, database, ui, config, etc.)
        2. Is it inbound flow or outbound flow?
        3. What keywords should be prioritized for file search?
        4. What type of fix is likely needed?

        Issue:
        {issue_text}

        Return structured bullet points.
        """

        issue_analysis = self.llm.generate(
            "You are a senior engineer analyzing a bug report.",
            analysis_prompt
        )

        print(issue_analysis)


        # ---- CLONE REPO ----
        print("[AI-ENGINEER] Cloning repository locally...")
        local_path = self.git_manager.clone_repo(owner, repo)

        # ---- CREATE BRANCH EARLY ----
        branch_name = f"ai-fix-issue-{issue_number}"
        self.git_manager.create_branch(local_path, branch_name)
        
        # ---- RUN BASELINE TESTS BEFORE ANY MODIFICATION ----
        print("[AI-ENGINEER] Running baseline tests before modification...")
        baseline_test = TestRunner.run_tests(local_path)

        baseline_output = (
            baseline_test.get("stdout", "") +
            "\n\nSTDERR:\n" +
            baseline_test.get("stderr", "")
        )

        baseline_status = baseline_test.get("status", "failed")
        print(f"[AI-ENGINEER] Test runner: {baseline_test.get('runner', 'unknown')}")

        if baseline_status == "passed":
            print("[AI-ENGINEER] Baseline tests passed.")

        elif baseline_status == "no_tests_found":
            print("[AI-ENGINEER] No tests detected for this repo. "
                  "Continuing without test validation.")

        elif baseline_status in ("tool_missing", "timeout", "error"):
            print(f"[AI-ENGINEER] Could not run baseline tests ({baseline_status}).")
            print(baseline_output[:2000])

        else:
            print("[AI-ENGINEER] Baseline tests are already failing.")
            print("\n===== BASELINE TEST OUTPUT =====\n")
            print(baseline_output[:2000])
            print("\n===============================\n")


        # ---- KEYWORD EXTRACTION ----
        print("[AI-ENGINEER] Extracting keywords from issue...")
        keywords = self.keyword_extractor.extract(issue_text)
        print(f"[AI-ENGINEER] Keywords detected: {keywords}")

        # ---- LOCAL SEARCH ----
        print("[AI-ENGINEER] Searching locally...")
        files = self.search.search_files_local(local_path, keywords)

        if not files:
            print("No relevant files found.")
            return

        # ---- FILTER OUT TEST FILES ----
        non_test_files = [f for f in files if not is_test_file(f)]

        if not non_test_files:
            non_test_files = files  # fallback

        # ---- FILE SCORING ----
        # The search step already ranks by keyword relevance, and sorted() is
        # stable, so this only demotes files that are poor patch targets.
        # No repo-specific heuristics here: it must work on any codebase.
        def score_file(path):
            score = 0
            lower = path.lower()

            # Penalize generated / minified / config-like files
            if any(x in lower for x in [".min.", ".generated.", ".pb.", "_pb2", "migrations/"]):
                score -= 5

            # Penalize very large files
            try:
                full_path = os.path.join(local_path, path)
                size = os.path.getsize(full_path)
                if size > 50000:
                    score -= 5
            except OSError:
                pass

            return score

        ranked_files = sorted(non_test_files, key=score_file, reverse=True)

        if not ranked_files:
            print("No candidate files after ranking.")
            return

        target_file = ranked_files[0]

        print(f"Using file: {target_file}")
        
        # ---- SELECT RELATED FILES FOR CONTEXT (Mini-RAG) ----
        related_files = []

        for f in files:
            if f != target_file and not is_test_file(f):
                related_files.append(f)

        # Take top 2 related files max
        related_files = related_files[:2]

        related_context = ""

        for rel_file in related_files:
            rel_path = os.path.join(local_path, rel_file)
            try:
                with open(rel_path, "r", encoding="utf-8", errors="ignore") as rf:
                    rel_content = rf.read()
                    related_context += f"\n\n--- Related File: {rel_file} ---\n"
                    related_context += rel_content
            except Exception:
                continue

        print(f"[AI-ENGINEER] Injecting {len(related_files)} related files for context.")

        

        file_path = os.path.join(local_path, target_file)

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            file_content = f.read()

        # ---- FULL FILE REWRITE ----
        print("[AI-ENGINEER] Rewriting file using LLM...")

        system_prompt = """
        You are a senior software engineer.

        You will receive:
        - A GitHub issue
        - A file path
        - The full content of the file

        Your task:
        Modify the file ONLY as necessary to fix the issue.

        STRICT RULES:
        - Do NOT remove comments.
        - Do NOT refactor unrelated code.
        - Do NOT change formatting unnecessarily.
        - Do NOT simplify existing logic.
        - Make the MINIMAL changes required.
        - Preserve all existing code except what must change.
        - Return the FULL updated file content.
        - Do NOT include explanations.
        - Do NOT include markdown.
        - Return only valid code.
        """

        user_prompt = f"""
        GitHub Issue:
        {issue_text}

        Current failing test output (before modification):
        {baseline_output}

        Target file:
        {target_file}

        Target file content:
        {file_content}

        Identify the root cause of the issue.
        Fix it with minimal changes.
        Return the COMPLETE updated file, from the first line to the last,
        with every unchanged line kept exactly as it is.
        Do NOT return only a snippet, a diff, or a summary.
        Do NOT include explanations or markdown fences.
        """

        raw_content = self.llm.generate(system_prompt, user_prompt)
        new_content = self._clean_file_output(raw_content, file_content)

        if new_content is None:
            print("[AI-ENGINEER] LLM output rejected (empty, truncated or snippet-only). "
                  "File left untouched.")
            return

        # ---- OVERWRITE FILE ----
        self.git_manager.overwrite_file(local_path, target_file, new_content)

        # ---- COMMIT ----
        commit_message = f"Fix issue #{issue_number} via AI agent"
        self.git_manager.commit_changes(local_path, commit_message)
        
        # ---- SHOW DIFF ----
        diff_output = self.git_manager.get_diff(local_path)

        print("\n===== LOCAL GIT DIFF =====\n")
        print(diff_output)
        
        # ---- RUN TESTS ----
        print("[AI-ENGINEER] Running automated tests...")
        test_result = TestRunner.run_tests(local_path)

        if test_result["returncode"] == 0:
            print("[AI-ENGINEER] Tests passed ✅")
            test_status = "Tests passed successfully."
        else:
            print("[AI-ENGINEER] Tests failed ❌")
            test_status = "Tests failed. Attempting automatic retry..."

            # ---- RETRY LOOP (1 attempt) ----
            retry_prompt = f"""
            The previous code change caused test failures.

            GitHub Issue:
            {issue_text}

            Git Diff:
            {diff_output}

            Test Failure Logs:
            {test_result["stdout"]}
            {test_result["stderr"][-2000:]}

            Target file: {target_file}

            Current content of the target file (after the previous change):
            {new_content}

            Fix the test errors WITHOUT removing unrelated logic.
            Make minimal changes.
            Return the COMPLETE updated file, from the first line to the last,
            with every unchanged line kept exactly as it is.
            Do NOT return only a snippet, a diff, or a summary.
            Do NOT include explanations or markdown fences.
            """

            retry_raw = self.llm.generate(
                "You are a senior engineer fixing failing tests.",
                retry_prompt
            )
            retry_content = self._clean_file_output(retry_raw, new_content)

            if retry_content is None:
                print("[AI-ENGINEER] Retry output rejected (empty, truncated or snippet-only). "
                      "Keeping the first attempt.")
                test_status = "Tests failed; retry output was rejected."
            else:
                self.git_manager.overwrite_file(local_path, target_file, retry_content)
                self.git_manager.commit_changes(local_path, "Retry fix after test failure")

                print("[AI-ENGINEER] Re-running tests after retry...")
                test_result = TestRunner.run_tests(local_path)

                if test_result["returncode"] == 0:
                    print("[AI-ENGINEER] Tests passed after retry ✅")
                    test_status = "Tests passed after automatic retry."
                else:
                    print("[AI-ENGINEER] Tests still failing ❌")
                    test_status = "Tests failed even after retry."


        print(test_result["stdout"])

        
        if len(diff_output.splitlines()) < 5:
            print("[AI-ENGINEER] Change too small — likely trivial modification.")
            print("[AI-ENGINEER] Skipping PR generation.")
            return
        
        # ---- SMALL CHANGE DETECTION (REAL CHANGE COUNT) ----
        change_lines = [
            line for line in diff_output.splitlines()
            if (line.startswith("+") or line.startswith("-"))
            and not line.startswith("+++")
            and not line.startswith("---")
        ]

        if len(change_lines) <= 2:
            print("[AI-ENGINEER] Only trivial changes detected.")
            print("[AI-ENGINEER] Skipping PR generation.")
            return
        
        # ---- LARGE CHANGE SAFETY GUARD ----
        if len(change_lines) > 80:
            print("[AI-ENGINEER] Change too large — possible unintended refactor.")
            print("[AI-ENGINEER] Aborting to prevent unsafe rewrite.")
            return
        
        # ---- FUNCTION DELETION GUARD ----
        # Language-agnostic: a definition is "deleted" only if its name was
        # removed and never re-added (so editing a signature is allowed).
        definition_re = re.compile(
            r"^\s*(?:export\s+)?(?:public\s+|private\s+|protected\s+|static\s+|async\s+|pub\s+)*"
            r"(?:def|function|func|fn|class|sub)\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)"
        )

        def definition_names(prefix):
            names = set()
            for line in change_lines:
                if line.startswith(prefix):
                    match = definition_re.match(line[1:])
                    if match:
                        names.add(match.group(1))
            return names

        deleted_functions = definition_names("-") - definition_names("+")

        if deleted_functions:
            print(f"[AI-ENGINEER] Detected deletion of: {', '.join(sorted(deleted_functions))}. "
                  "Aborting unsafe modification.")
            return

        # ---- PR DESCRIPTION ----
        print("Generating PR description...")
        pr = self.pr_writer.generate_pr(issue_text, diff_output, test_status)

        print("\n===== PR DESCRIPTION =====\n")
        print(pr)

    def _clean_file_output(self, text, original):
        """
        Turns raw LLM output into file content, or returns None if it can't be trusted.

        Handles: markdown fences around the whole answer, empty output, and
        snippet-only / truncated answers (far shorter than the original file).
        """
        if not text or not text.strip():
            return None

        cleaned = text.strip()

        fenced = re.match(r"^```[\w+.-]*\n(.*?)\n?```\s*$", cleaned, re.DOTALL)
        if fenced:
            cleaned = fenced.group(1)

        # A stray fence line left inside means the model mixed prose and code
        if cleaned.startswith("```") or cleaned.endswith("```"):
            return None

        original_lines = len(original.splitlines())
        new_lines = len(cleaned.splitlines())

        # Only enforce the length check when there is enough original to compare
        if original_lines >= 20 and new_lines < original_lines * 0.5:
            return None

        # Keep the file's trailing newline convention
        if original.endswith("\n") and not cleaned.endswith("\n"):
            cleaned += "\n"

        return cleaned

    def log(self, step):
        print(f"[AI-ENGINEER] {step}")

    
