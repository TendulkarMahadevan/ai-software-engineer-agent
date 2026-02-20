import os

class RepoSearchTool:

    def search_files_local(self, local_path, keywords):
        matched = []

        for root, _, files in os.walk(local_path):
            for file in files:
                if not file.endswith((".ts", ".js", ".py")):
                    continue

                full_path = os.path.join(root, file)
                relative_path = os.path.relpath(full_path, local_path)
                lower_path = relative_path.lower()

                path_score = 0
                content_score = 0

                # ---- PATH-BASED SCORING (STRONG SIGNAL) ----
                for kw in keywords:
                    if kw.lower() in lower_path:
                        path_score += 3

                # ---- CONTENT-BASED SCORING ----
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read().lower()
                        for kw in keywords:
                            if kw.lower() in content:
                                content_score += 1
                except:
                    pass

                total_score = path_score + content_score

                if total_score > 0:
                    matched.append((relative_path, total_score))

        # Sort by score (descending)
        matched.sort(key=lambda x: x[1], reverse=True)

        return [m[0] for m in matched]