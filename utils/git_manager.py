import git
import tempfile
import os
import subprocess


class GitManager:

    def clone_repo(self, owner, repo):
        repo_url = f"https://github.com/{owner}/{repo}.git"
        local_path = tempfile.mkdtemp(prefix="ai_agent_repo_")

        print(f"[AI-ENGINEER] Cloning repo to {local_path}")
        git.Repo.clone_from(repo_url, local_path)

        return local_path

    def create_branch(self, local_path, branch_name):
        repo = git.Repo(local_path)
        repo.git.checkout("-b", branch_name)
        print(f"[AI-ENGINEER] Created branch {branch_name}")

    def commit_changes(self, local_path, message):
        repo = git.Repo(local_path)
        repo.git.add(all=True)
        repo.index.commit(message)
        print("[AI-ENGINEER] Changes committed")

    def get_diff(self, local_path):
        repo = git.Repo(local_path)
        return repo.git.diff("HEAD~1")

    # FIXED PATCH CLEANER
    def clean_patch(self, text):
        text = text.replace("```diff", "")
        text = text.replace("```", "")
        text = text.strip()

        # Accept either format
        if text.startswith("diff --git"):
            return text
        elif text.startswith("--- "):
            return text
        else:
            raise ValueError("No valid diff header found")


    # FIXED PATCH APPLY
    def apply_patch(self, repo_path, patch_text):
        print("[AI-ENGINEER] Cleaning patch...")
        patch_text = self.clean_patch(patch_text)

        print("[AI-ENGINEER] Validating patch...")

        patch_file = os.path.join(repo_path, "temp_patch.diff")

        # Always enforce utf-8
        with open(patch_file, "w", encoding="utf-8") as f:
            f.write(patch_text)

        try:
            # Step 1: Validate only
            subprocess.run(
                ["git", "apply", "--check", patch_file],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )

            print("✔ Patch validation successful.")

            # Step 2: Apply
            subprocess.run(
                ["git", "apply", patch_file],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )

            print("✔ Patch applied successfully.")

        except subprocess.CalledProcessError as e:
            print("❌ Patch validation failed.")
            print("STDERR:")
            print(e.stderr)
            raise

        finally:
            if os.path.exists(patch_file):
                os.remove(patch_file)
                
    def overwrite_file(self, repo_path, file_path, new_content):
        full_path = os.path.join(repo_path, file_path)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        print(f"[AI-ENGINEER] Overwrote {file_path}")


