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


def _definition_pattern(name):
    """
    Matches a line that defines `name` (constant, variable, function, class, type),
    not one that merely uses it. Works across common languages.
    """
    modifiers = (r"(?:(?:export|public|private|protected|static|final|readonly|async|pub|"
                 r"const|let|var|val|def|class|function|func|fn|type|interface|struct|enum|"
                 r"object|trait)\s+)*")
    receiver = r"(?:\([^)]*\)\s*)?"  # Go method receiver: func (s *S) name()
    return re.compile(rf"^\s*{modifiers}{receiver}{re.escape(name)}\s*(?::[^=\n]*)?(?:=(?!=)|\(|\{{|<|$|:)")


ROOT_DEFINITION_SCORE = 10     # defines the name from scratch
PARENT_BONUS = 5               # the file whose class others extend or qualify with
DERIVED_DEFINITION_SCORE = 4   # redefines it from the parent's value (e.g. `X = Base.X | {...}`)


class RepoSearchTool:

    def _source_files(self, local_path):
        """Yields (full_path, relative_path) for every searchable source file."""
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

                yield full_path, os.path.relpath(full_path, local_path)

    def find_definitions(self, local_path, identifiers):
        """
        Returns {relative_path: score} for files that DEFINE any of the identifiers.

        - A definition built from the parent's value (the name appears again on the same
          line, like `X = Base.X | {...}`) scores lower than an original definition.
        - Several files can define the name from scratch (a base class and one-off
          overrides). The one whose class is used as a qualifier elsewhere (`Base.X`)
          is the parent, so it gets a bonus and wins the tie.
        """
        patterns = {name: _definition_pattern(name) for name in identifiers}
        qualifier_res = [re.compile(rf"\b(\w+)\.{re.escape(name)}\b") for name in identifiers]
        class_re = re.compile(r"^\s*(?:export\s+|public\s+|abstract\s+|final\s+)*"
                              r"(?:class|struct|trait|interface|object)\s+(\w+)")

        best_by_file = {}
        classes_by_file = {}
        qualifiers = set()

        for full_path, relative_path in self._source_files(local_path):
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.read().splitlines()
            except OSError:
                continue

            best = 0
            classes = set()
            for line in lines:
                if any(name in line for name in identifiers):
                    for qualifier_re in qualifier_res:
                        qualifiers.update(qualifier_re.findall(line))
                    for name, pattern in patterns.items():
                        if name in line and pattern.match(line):
                            derived = name in line.split(name, 1)[1]
                            best = max(best, DERIVED_DEFINITION_SCORE if derived
                                       else ROOT_DEFINITION_SCORE)
                match = class_re.match(line)
                if match:
                    classes.add(match.group(1))

            if best:
                best_by_file[relative_path] = best
                classes_by_file[relative_path] = classes

        scores = {}
        for path, best in best_by_file.items():
            is_parent = bool(classes_by_file[path] & qualifiers)
            scores[path] = best + (PARENT_BONUS if is_parent else 0)
        return scores

    def search_files_local(self, local_path, keywords):
        matched = []

        for full_path, relative_path in self._source_files(local_path):
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
