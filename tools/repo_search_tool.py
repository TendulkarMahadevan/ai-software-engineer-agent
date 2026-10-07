import os
import re

# Folders that never contain code worth patching (and can be huge)
IGNORED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "venv", ".venv", ".ai_agent_venv",
    "env", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache",
    "dist", "build", "target", "out", "vendor", ".next", ".gradle", ".idea",
    ".vscode", "coverage",
}

# Source file extensions the agent is allowed to search and patch
SOURCE_EXTENSIONS = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".scala",
    ".rb", ".php", ".cs", ".c", ".h", ".cc", ".cpp", ".hpp",
    ".swift", ".m", ".sh",
)

# Skip files larger than this (generated bundles, data dumps)
MAX_FILE_BYTES = 500_000

_TEST_FILE_PATTERNS = [
    re.compile(r"\.(test|spec)\.[a-z]+$"),           # foo.test.js, foo.spec.ts
    re.compile(r"(^|/)test_[^/]+\.py$"),             # test_foo.py
    re.compile(r"_test\.(py|go|rb|rs|c|cc|cpp)$"),   # foo_test.go, foo_test.py
    re.compile(r"(^|/)[^/]+(Test|Tests|Spec)\.(java|kt|scala|cs|php|swift)$"),
    re.compile(r"(^|/)(tests?|__tests__|spec|specs)/"),
]


def is_test_file(path):
    """True if the (relative) path looks like a test file in any common ecosystem."""
    normalized = path.replace("\\", "/")
    lower = normalized.lower()
    for pattern in _TEST_FILE_PATTERNS:
        # CamelCase patterns (FooTest.java) need the original casing
        target = normalized if "Test" in pattern.pattern else lower
        if pattern.search(target):
            return True
    return False


class RepoSearchTool:

    def search_files_local(self, local_path, keywords):
        matched = []

        for root, dirs, files in os.walk(local_path):
            # Prune in place so os.walk never descends into ignored folders
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

            for file in files:
                if not file.endswith(SOURCE_EXTENSIONS):
                    continue

                full_path = os.path.join(root, file)

                try:
                    if os.path.getsize(full_path) > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue

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
                except OSError:
                    pass

                total_score = path_score + content_score

                if total_score > 0:
                    matched.append((relative_path, total_score))

        # Sort by score (descending)
        matched.sort(key=lambda x: x[1], reverse=True)

        return [m[0] for m in matched]
