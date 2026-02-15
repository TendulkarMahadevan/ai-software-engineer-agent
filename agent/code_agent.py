from tools.github_tool import GitHubTool
from tools.repo_search_tool import RepoSearchTool
from tools.context_extractor import ContextExtractor
from patch.patch_generator import PatchGenerator
from patch.pr_writer import PRWriter
from llm.openai_client import LLMClient

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
        patch = self.patch_gen.generate_patch(issue_text, context)

        print("Generating PR description...")
        pr = self.pr_writer.generate_pr(issue_text, patch)

        print("\n===== PATCH =====\n")
        print(patch)

        print("\n===== PR DESCRIPTION =====\n")
        print(pr)
