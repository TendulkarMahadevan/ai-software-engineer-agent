class FileRewriter:

    def __init__(self, llm):
        self.llm = llm

    def rewrite_file(self, issue_text, file_path, context):

        system_prompt = """
You are a senior software engineer.

You will receive:
- A GitHub issue
- A file path
- The full content of the file

You must return the FULL updated file content.

Rules:
- Return ONLY valid TypeScript code.
- Do NOT include explanations.
- Do NOT include markdown.
- Do NOT include triple backticks.
- Return the entire file from top to bottom.
"""

        user_prompt = f"""
GitHub Issue:
{issue_text}

File to modify:
{file_path}

Current file content:
{context}

Return the FULL updated file content.
"""

        return self.llm.generate(system_prompt, user_prompt)
