import json
import os
import re
import shlex
import subprocess
import sys

INSTALL_TIMEOUT = 900
TEST_TIMEOUT = 600

# Status values returned in result["status"]
PASSED = "passed"
FAILED = "failed"
NO_TESTS = "no_tests_found"
TOOL_MISSING = "tool_missing"
TIMEOUT = "timeout"
ERROR = "error"

# Statuses that mean "the tests could not be run", as opposed to "the tests failed".
# Callers should not retry a fix or write a PR on these.
ENV_ERRORS = (TOOL_MISSING, TIMEOUT, ERROR)

# Kept out of the commits the agent makes (written to .git/info/exclude)
LOCAL_ONLY = (".ai_agent_venv/", ".ai_agent_installed")
INSTALL_MARKER = ".ai_agent_installed"

# Optional-dependency groups that usually hold test tooling, in order of preference
PREFERRED_EXTRAS = ("test", "tests", "testing", "dev")
DEV_REQUIREMENT_FILES = ("requirements-dev.txt", "requirements-test.txt", "dev-requirements.txt")

PYTEST_NAME = "python (pytest)"
# pytest exit codes: 3 = internal error, 4 = usage error (bad flag, missing plugin),
# 5 = no tests collected. 3 and 4 are setup problems, not failing tests.
PYTEST_NO_TESTS = 5
PYTEST_SETUP_ERRORS = (3, 4)

# addopts fragments that need a plugin, so the repo's own pytest config can load
PYTEST_PLUGIN_HINTS = (
    (re.compile(r"--cov\b"), "pytest-cov"),
    (re.compile(r"(^|\s)-n\s*(\d+|auto|logical)\b|--numprocesses\b"), "pytest-xdist"),
    (re.compile(r"--timeout\b"), "pytest-timeout"),
)


class TestRunner:
    """
    Detects the project type and runs its tests.

    Result dict keys:
      returncode : 0 only when status == "passed"
      stdout, stderr : combined output of the install and test steps
      status : passed | failed | no_tests_found | tool_missing | timeout | error
      runner : human readable name of the detected runner
    """

    # Stops pytest from trying to collect tests in these folders
    __test__ = False

    # ---------- public API ----------

    @staticmethod
    def run_tests(repo_path):
        config = TestRunner._load_config(repo_path)
        plan = TestRunner._build_plan(repo_path, config)

        if plan is None:
            return TestRunner._result(
                -2, "", "No supported test setup detected. "
                "Add a .ai-agent.yml with 'test_command: ...' to this repo.",
                NO_TESTS, "none",
            )

        runner_name, install_cmds, test_cmd, env = plan
        print(f"[TEST-RUNNER] Detected runner: {runner_name}")

        TestRunner._exclude_from_git(repo_path)

        out_log, err_log = "", ""

        # ---- install dependencies (once per clone) ----
        marker = os.path.join(repo_path, INSTALL_MARKER)
        fingerprint = json.dumps(install_cmds)

        if install_cmds and TestRunner._read(marker) == fingerprint:
            print("[TEST-RUNNER] Dependencies already installed, skipping install.")
        else:
            for cmd in install_cmds:
                print(f"[TEST-RUNNER] Installing: {' '.join(cmd)}")
                res = TestRunner._run(cmd, repo_path, env, INSTALL_TIMEOUT)
                out_log += res["stdout"]
                err_log += res["stderr"]
                if res["status"] != PASSED:
                    err_log += f"\n[TEST-RUNNER] Install step failed: {' '.join(cmd)}\n"
                    # A failed install is a setup problem even when the command exited nonzero
                    status = res["status"] if res["status"] != FAILED else ERROR
                    return TestRunner._result(
                        res["returncode"] or -1, out_log, err_log, status, runner_name,
                    )
            if install_cmds:
                TestRunner._write(marker, fingerprint)

        # ---- run tests ----
        print(f"[TEST-RUNNER] Running: {' '.join(test_cmd)}")
        res = TestRunner._run(test_cmd, repo_path, env, TEST_TIMEOUT)
        out_log += res["stdout"]
        err_log += res["stderr"]

        status = res["status"]

        if runner_name == PYTEST_NAME:
            if res["returncode"] == PYTEST_NO_TESTS:
                status = NO_TESTS
            elif res["returncode"] in PYTEST_SETUP_ERRORS:
                status = ERROR
                err_log += ("\n[TEST-RUNNER] pytest could not start (usage or internal error). "
                            "This is a setup problem, not a failing test.\n")

        returncode = 0 if status == PASSED else (res["returncode"] or -1)
        return TestRunner._result(returncode, out_log, err_log, status, runner_name)

    # ---------- planning ----------

    @staticmethod
    def _build_plan(repo_path, config):
        """Returns (runner_name, [install_cmds], test_cmd, env) or None."""
        env = os.environ.copy()
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

        # 1. explicit override from the target repo
        if config.get("test_command"):
            install_cmds = []
            if config.get("install_command"):
                install_cmds.append(shlex.split(config["install_command"]))
            return (
                "custom (.ai-agent.yml)",
                install_cmds,
                shlex.split(config["test_command"]),
                env,
            )

        has = lambda name: os.path.exists(os.path.join(repo_path, name))

        # 2. Node
        if has("package.json") and TestRunner._node_has_test_script(repo_path):
            if has("pnpm-lock.yaml"):
                return ("node (pnpm)", [["pnpm", "install"]], ["pnpm", "test"], env)
            if has("yarn.lock"):
                return ("node (yarn)", [["yarn", "install"]], ["yarn", "test"], env)
            install = ["npm", "ci"] if has("package-lock.json") else ["npm", "install"]
            return ("node (npm)", [install], ["npm", "test"], env)

        # 3. Python
        if any(has(f) for f in ("pyproject.toml", "pytest.ini", "setup.py",
                                "setup.cfg", "requirements.txt", "tox.ini")):
            return TestRunner._python_plan(repo_path, env, has)

        # 4. Go
        if has("go.mod"):
            return ("go", [["go", "mod", "download"]], ["go", "test", "./..."], env)

        # 5. Rust
        if has("Cargo.toml"):
            return ("rust (cargo)", [], ["cargo", "test"], env)

        # 6. Java
        if has("pom.xml"):
            return ("java (maven)", [], ["mvn", "-q", "test"], env)
        if has("gradlew"):
            return ("java (gradle)", [], ["./gradlew", "test"], env)
        if has("build.gradle") or has("build.gradle.kts"):
            return ("java (gradle)", [], ["gradle", "test"], env)

        # 7. Ruby
        if has("Gemfile"):
            return (
                "ruby",
                [["bundle", "install"]],
                ["bundle", "exec", "rake", "test"],
                env,
            )

        return None

    @staticmethod
    def _python_plan(repo_path, env, has):
        """Uses a private virtualenv inside the clone so the host Python stays clean."""
        venv_dir = os.path.join(repo_path, ".ai_agent_venv")
        bin_dir = "Scripts" if sys.platform == "win32" else "bin"
        venv_python = os.path.join(venv_dir, bin_dir, "python")
        pip = [venv_python, "-m", "pip", "install", "-q"]

        install_cmds = []
        if not os.path.exists(venv_python):
            install_cmds.append([sys.executable, "-m", "venv", venv_dir])

        # pytest itself, plus any plugin the repo's own pytest config requires
        install_cmds.append(pip + ["pytest"] + TestRunner._required_pytest_plugins(repo_path))

        for req_file in DEV_REQUIREMENT_FILES:
            if has(req_file):
                install_cmds.append(pip + ["-r", req_file])
        if has("requirements.txt"):
            install_cmds.append(pip + ["-r", "requirements.txt"])

        if has("pyproject.toml") or has("setup.py") or has("setup.cfg"):
            extra = TestRunner._test_extra(repo_path)
            target = f".[{extra}]" if extra else "."
            install_cmds.append(pip + ["-e", target])

        return (
            PYTEST_NAME,
            install_cmds,
            [venv_python, "-m", "pytest", "-x", "-q"],
            env,
        )

    # ---------- python config helpers ----------

    @staticmethod
    def _test_extra(repo_path):
        """Name of the optional-dependency group holding test tooling, or None."""
        extras = TestRunner._optional_dependency_groups(repo_path)
        for name in PREFERRED_EXTRAS:
            if name in extras:
                return name
        return None

    @staticmethod
    def _optional_dependency_groups(repo_path):
        path = os.path.join(repo_path, "pyproject.toml")
        text = TestRunner._read(path)
        if not text:
            return set()

        try:
            import tomllib  # Python 3.11+
            data = tomllib.loads(text)
            return set(data.get("project", {}).get("optional-dependencies", {}))
        except ImportError:
            pass
        except Exception:
            return set()

        # Fallback for Python < 3.11: read the keys of [project.optional-dependencies]
        names, inside = set(), False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                inside = stripped == "[project.optional-dependencies]"
                continue
            if inside:
                match = re.match(r'^"?([A-Za-z0-9_.-]+)"?\s*=', stripped)
                if match:
                    names.add(match.group(1))
        return names

    @staticmethod
    def _required_pytest_plugins(repo_path):
        """Plugins implied by addopts in the repo's pytest config (empty if none)."""
        addopts = []
        for name in ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"):
            for line in TestRunner._read(os.path.join(repo_path, name)).splitlines():
                if "addopts" in line:
                    addopts.append(line)
        joined = " ".join(addopts)

        plugins = []
        for pattern, plugin in PYTEST_PLUGIN_HINTS:
            if pattern.search(joined) and plugin not in plugins:
                plugins.append(plugin)
        return plugins

    # ---------- helpers ----------

    @staticmethod
    def _node_has_test_script(repo_path):
        """True only if package.json defines a real test script."""
        try:
            with open(os.path.join(repo_path, "package.json"), "r", encoding="utf-8") as f:
                scripts = json.load(f).get("scripts", {})
        except Exception:
            return False

        test_script = scripts.get("test", "")
        if not test_script:
            return False
        # npm's default placeholder
        if "no test specified" in test_script:
            return False
        return True

    @staticmethod
    def _load_config(repo_path):
        """
        Reads a minimal .ai-agent.yml (flat 'key: value' lines, no yaml dependency).

        Example:
            test_command: make check
            install_command: make deps
        """
        path = os.path.join(repo_path, ".ai-agent.yml")
        config = {}
        if not os.path.exists(path):
            return config

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    config[key.strip()] = value.strip().strip('"').strip("'")
        except Exception:
            pass
        return config

    @staticmethod
    def _read(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    @staticmethod
    def _write(path, text):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass

    @staticmethod
    def _exclude_from_git(repo_path):
        """Keeps the venv and install marker out of the agent's commits."""
        info_dir = os.path.join(repo_path, ".git", "info")
        if not os.path.isdir(info_dir):
            return
        exclude = os.path.join(info_dir, "exclude")
        existing = TestRunner._read(exclude)
        missing = [entry for entry in LOCAL_ONLY if entry not in existing.splitlines()]
        if missing:
            prefix = "" if not existing or existing.endswith("\n") else "\n"
            TestRunner._write(exclude, existing + prefix + "\n".join(missing) + "\n")

    @staticmethod
    def _run(cmd, cwd, env, timeout):
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            status = PASSED if result.returncode == 0 else FAILED
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "status": status,
            }
        except FileNotFoundError:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"Command not found: {cmd[0]}. Install it on this machine.",
                "status": TOOL_MISSING,
            }
        except subprocess.TimeoutExpired:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"Timed out after {timeout}s: {' '.join(cmd)}",
                "status": TIMEOUT,
            }
        except Exception as e:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
                "status": ERROR,
            }

    @staticmethod
    def _result(returncode, stdout, stderr, status, runner):
        return {
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "status": status,
            "runner": runner,
        }
