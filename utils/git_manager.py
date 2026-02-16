import os
import shutil
import tempfile
import git


class GitManager:

    def __init__(self, repo_url: str):
        self.repo_url = repo_url
        self.local_path = os.path.join(
            tempfile.gettempdir(),
            "ai_agent_repo"
        )

    def clone_repo(self):
        if os.path.exists(self.local_path):
            shutil.rmtree(self.local_path)

        print(f"[AI-ENGINEER] Cloning repo to {self.local_path}")
        git.Repo.clone_from(self.repo_url, self.local_path)

        return self.local_path

    def create_branch(self, branch_name: str):
        repo = git.Repo(self.local_path)
        new_branch = repo.create_head(branch_name)
        repo.head.reference = new_branch
        repo.head.reset(index=True, working_tree=True)
        print(f"[AI-ENGINEER] Created branch {branch_name}")

    def apply_patch(self, diff_text: str):
        """
        Applies a simple unified diff manually.
        Assumes single-file modification.
        """

        import re

        repo = git.Repo(self.local_path)

        # Extract file path
        match = re.search(r"\+\+\+ (?:b/)?(.+)", diff_text)
        if not match:
            raise Exception("Could not extract file path from diff")

        file_path = match.group(1).strip()
        full_path = os.path.join(self.local_path, file_path)

        if not os.path.exists(full_path):
            raise Exception(f"File not found in repo: {file_path}")

        # Extract only added lines (simplified MVP)
        new_lines = []
        for line in diff_text.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                new_lines.append(line[1:])

        # For MVP, append new lines to file (simplified strategy)
        with open(full_path, "a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(new_lines))

        print("[AI-ENGINEER] Patch applied manually (MVP mode)")


    def commit_changes(self, message: str):
        repo = git.Repo(self.local_path)
        repo.git.add(A=True)
        repo.index.commit(message)
        print("[AI-ENGINEER] Changes committed")

    def get_diff(self):
        repo = git.Repo(self.local_path)
        return repo.git.diff("HEAD~1")
