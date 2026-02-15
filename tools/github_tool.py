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

    def get_file_content(self, owner, repo, path):
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()

        data = response.json()

        if data.get("encoding") != "base64":
            raise Exception("Unsupported file encoding")

        try:
            return base64.b64decode(data["content"]).decode("utf-8")
        except UnicodeDecodeError:
            raise Exception("File is not valid UTF-8 text")
