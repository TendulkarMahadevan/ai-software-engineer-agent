from tools.github_tool import GitHubTool
from tools.repo_search_tool import RepoSearchTool
from tools.context_extractor import ContextExtractor
from patch.patch_generator import PatchGenerator
from patch.pr_writer import PRWriter
from llm.openai_client import LLMClient
from utils import git_manager
from utils.diff_validator import DiffValidator
from utils.git_manager import GitManager

class CodeAgent:

    def __init__(self):
        self.github = GitHubTool()
        self.search = RepoSearchTool()
        self.extractor = ContextExtractor()
        self.llm = LLMClient()
        self.patch_gen = PatchGenerator(self.llm)
        self.pr_writer = PRWriter(self.llm)

    def run(self, owner, repo, issue_number, keyword):
        print("\nFetching issue...")
        issue = self.github.get_issue(owner, repo, issue_number)

        issue_text = issue.get("title", "") + "\n\n" + issue.get("body", "")

        print("Getting repository info...")
        branch = self.github.get_default_branch(owner, repo)
        repo_tree = self.github.get_repo_tree(owner, repo, branch)

        print("Searching files...")
        files = self.search.search_files(repo_tree, keyword)

        if not files:
            print("No relevant files found.")
            return

        print(f"Using file: {files[0]}")

        file_content = self.github.get_file_content(owner, repo, files[0])
        context = self.extractor.extract_context(file_content, keyword)

        print("Generating patch...")
        patch = self.patch_gen.generate_patch(issue_text, files[0], context)

        is_valid, message = DiffValidator.validate(patch, files)

        if not is_valid:
            print("\n⚠ Patch validation failed:")
            print(message)
            return

        print("\n✔ Patch validation successful.")

        # Git automation phase
        repo_url = f"https://github.com/{owner}/{repo}.git"

        git_manager = GitManager(repo_url)
        local_path = git_manager.clone_repo()

        branch_name = f"ai-fix-issue-{issue_number}"
        git_manager.create_branch(branch_name)
        
        patch = DiffValidator.clean_diff(patch)

        git_manager.apply_patch(patch)

        commit_message = f"Fix issue #{issue_number} via AI agent"
        git_manager.commit_changes(commit_message)

        diff_output = git_manager.get_diff()

        print("\n===== LOCAL GIT DIFF =====\n")
        print(diff_output)



        print("Generating PR description...")
        pr = self.pr_writer.generate_pr(issue_text, patch)

        print("\n===== PATCH =====\n")
        print(patch)

        print("\n===== PR DESCRIPTION =====\n")
        print(pr)
        
    def log(self, step):
        print(f"[AI-ENGINEER] {step}")

