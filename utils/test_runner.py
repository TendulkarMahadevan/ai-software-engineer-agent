import subprocess

class TestRunner:

    @staticmethod
    def run_tests(repo_path):
        try:
            print("[TEST-RUNNER] Running npm tests...")

            result = subprocess.run(
                ["npm", "test"],
                cwd=repo_path,
                capture_output=True,
                text=True
            )

            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }

        except Exception as e:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": str(e)
            }

