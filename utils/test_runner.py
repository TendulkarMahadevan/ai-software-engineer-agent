import json
import os
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

        out_log, err_log = "", ""

        # ---- install dependencies ----
        for cmd in install_cmds:
            print(f"[TEST-RUNNER] Installing: {' '.join(cmd)}")
            res = TestRunner._run(cmd, repo_path, env, INSTALL_TIMEOUT)
            out_log += res["stdout"]
            err_log += res["stderr"]
            if res["status"] != PASSED:
                err_log += f"\n[TEST-RUNNER] Install step failed: {' '.join(cmd)}\n"
                return TestRunner._result(
                    res["returncode"] or -1, out_log, err_log,
                    res["status"], runner_name,
                )

        # ---- run tests ----
        print(f"[TEST-RUNNER] Running: {' '.join(test_cmd)}")
        res = TestRunner._run(test_cmd, repo_path, env, TEST_TIMEOUT)
        out_log += res["stdout"]
        err_log += res["stderr"]

        status = res["status"]

        # pytest exits with code 5 when it collects zero tests
        if runner_name == "python (pytest)" and res["returncode"] == 5:
            status = NO_TESTS

        returncode = 0 if status == PASSED else (res["returncode"] or -1)
        return TestRunner._result(returncode, out_log, err_log, status, runner_name)

    # ---------- planning ----------

    @staticmethod
    def _build_plan(repo_path, config):
        """Returns (runner_name, [install_cmds], test_cmd, env) or None."""
        env = os.environ.copy()

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

        install_cmds = [[sys.executable, "-m", "venv", venv_dir]]
        install_cmds.append([venv_python, "-m", "pip", "install", "-q", "pytest"])

        if has("requirements.txt"):
            install_cmds.append(
                [venv_python, "-m", "pip", "install", "-q", "-r", "requirements.txt"]
            )
        if has("pyproject.toml") or has("setup.py") or has("setup.cfg"):
            install_cmds.append(
                [venv_python, "-m", "pip", "install", "-q", "-e", "."]
            )

        return (
            "python (pytest)",
            install_cmds,
            [venv_python, "-m", "pytest", "-x", "-q"],
            env,
        )

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