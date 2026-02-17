class RepoSearchTool:

    def __init__(self, github_tool):
        self.github = github_tool

    def search_files(self, repo_tree, keywords):

        file_scores = []

        # Stage 1: Path-level prefilter
        candidate_files = []

        for item in repo_tree:
            if item["type"] != "blob":
                continue

            path = item["path"]

            if not path.endswith((".py", ".ts", ".js", ".json", ".go", ".java", ".tsx")):
                continue

            for kw in keywords:
                if kw.lower() in path.lower():
                    candidate_files.append(item)
                    break
                # print(f"[SEARCH] Candidate files: {len(candidate_files)}")

        # Stage 2: Content scoring (only for filtered files)
        for item in candidate_files:

            try:
                file_content = self.github.get_file_content(item["url"])

                score = 0
                for kw in keywords:
                    if kw.lower() in file_content.lower():
                        score += 1

                if score > 0:
                    file_scores.append((item["path"], score))
                print(f"[SEARCH] Checking: {item['path']}")

            except Exception:
                continue

        file_scores.sort(key=lambda x: x[1], reverse=True)

        return [file[0] for file in file_scores[:5]]
