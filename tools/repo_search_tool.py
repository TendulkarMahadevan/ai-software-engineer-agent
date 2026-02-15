class RepoSearchTool:

    def search_files(self, repo_tree, keyword):
        matches = []

        allowed_extensions = (
            ".py", ".js", ".ts", ".tsx", ".jsx",
            ".java", ".go", ".cpp", ".c", ".rs",
            ".json", ".yaml", ".yml"
        )

        for item in repo_tree:
            if item["type"] == "blob":
                path = item["path"]

                if not path.endswith(allowed_extensions):
                    continue

                if keyword.lower() in path.lower():
                    matches.append(path)

        return matches[:5]
