import requests
import base64
from config.settings import GITHUB_TOKEN


class GitHubTool:
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }

    def get_issue(self, owner, repo, issue_number):
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 404:
            raise Exception(
                f"Issue not found.\n"
                f"Owner: {owner}\n"
                f"Repo: {repo}\n"
                f"Issue: {issue_number}"
            )

        response.raise_for_status()
        return response.json()

    def get_default_branch(self, owner, repo):
        url = f"https://api.github.com/repos/{owner}/{repo}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()["default_branch"]

    def get_repo_tree(self, owner, repo, branch):
        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()["tree"]

    def get_file_content(self, owner_or_url, repo=None, path=None):
            """
            Supports two modes:
            1. get_file_content(file_url)
            2. get_file_content(owner, repo, path)
            """

            # Mode 1: Direct file URL
            if repo is None and path is None:
                file_url = owner_or_url

            # Mode 2: owner, repo, path
            else:
                owner = owner_or_url
                file_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

            response = requests.get(file_url, headers=self.headers)
            response.raise_for_status()

            data = response.json()

            if "content" in data:
                content = data["content"]
                decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
                return decoded

            return ""


