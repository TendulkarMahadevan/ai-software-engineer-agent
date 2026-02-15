class PatchGenerator:

    def __init__(self, llm):
        self.llm = llm

    def generate_patch(self, issue_text,file_path, context):
        system_prompt = "You are a senior software engineer. Generate minimal, correct code patches."

        user_prompt = f"""
GitHub Issue:
{issue_text}

You are ONLY allowed to modify this file:
{file_path}

Here is the file content:
{context}

Generate a minimal unified diff patch.

The diff MUST modify:
{file_path}

Do NOT reference any other file.

Return ONLY the diff.
"""



        return self.llm.generate(system_prompt, user_prompt)
