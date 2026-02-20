import os
from tools.github_tool import GitHubTool
from tools.repo_search_tool import RepoSearchTool
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
        non_test_files = [f for f in files if ".test." not in f]

        if not non_test_files:
            non_test_files = files  # fallback

        # ---- FILE SCORING ----
        def score_file(path):
            score = 0
            lower = path.lower()

            # Boost inbound-related signals
            if any(x in lower for x in ["gateway", "raw", "update", "poll", "dispatch", "handler", "listener"]):
                score += 6

            # Penalize outbound-focused signals
            if any(x in lower for x in ["send", "outbound", "publisher", "notify"]):
                score -= 3
                
             # Dynamic Boost Based on Issue Analysis
            if "inbound" in issue_analysis.lower():
                if any(x in lower for x in ["handler", "listener", "dispatch", "poll"]):
                    score += 5

            if "database" in issue_analysis.lower():
                if any(x in lower for x in ["repository", "model", "db"]):
                    score += 5

            # Penalize very large files
            try:
                full_path = os.path.join(local_path, path)
                size = os.path.getsize(full_path)
                if size > 50000:
                    score -= 5
            except:
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
            if f != target_file and ".test." not in f:
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

        File to modify:
        {target_file}

        Current file content:
        {file_content}

        Additional related context (read-only, do NOT modify these directly):
        {related_context}

        Return the FULL updated file content of ONLY:
        {target_file}
        """

        new_content = self.llm.generate(system_prompt, user_prompt)

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

            Fix the test errors WITHOUT removing unrelated logic.
            Make minimal changes.
            Return only valid code.
            """

            retry_content = self.llm.generate(
                "You are a senior engineer fixing failing tests.",
                retry_prompt
            )

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
        deleted_functions = [
            line for line in change_lines
            if line.startswith("-function") or line.startswith("-async function")
        ]

        if deleted_functions:
            print("[AI-ENGINEER] Detected function deletion. Aborting unsafe modification.")
            return

        # ---- PR DESCRIPTION ----
        print("Generating PR description...")
        pr = self.pr_writer.generate_pr(issue_text, diff_output, test_status)

        print("\n===== PR DESCRIPTION =====\n")
        print(pr)

    def log(self, step):
        print(f"[AI-ENGINEER] {step}")

    
