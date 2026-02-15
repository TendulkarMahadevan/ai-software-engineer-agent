import re


class DiffValidator:

    @staticmethod
    def clean_diff(diff_text: str) -> str:
        """
        Removes markdown code fences if present.
        """
        diff_text = diff_text.strip()
        if diff_text.startswith("```"):
            diff_text = re.sub(r"^```diff\n?", "", diff_text)
            diff_text = re.sub(r"^```\n?", "", diff_text)
            diff_text = re.sub(r"\n```$", "", diff_text)
        return diff_text.strip()

    @staticmethod
    def extract_modified_files(diff_text: str):
        """
        Extract file paths from unified diff.
        Supports both:
        +++ b/file/path
        +++ file/path
        """
        pattern = r"\+\+\+ (?:b/)?(.+)"
        return re.findall(pattern, diff_text)

    @staticmethod
    def validate(diff_text: str, allowed_files: list):
        diff_text = DiffValidator.clean_diff(diff_text)

        modified_files = DiffValidator.extract_modified_files(diff_text)

        if not modified_files:
            return False, "No valid file paths found in diff."

        for file in modified_files:
            file = file.strip()

            if file not in allowed_files:
                return False, f"Unauthorized file modification detected: {file}"

        return True, "Diff validated successfully."
