class PatchGenerator:

    def __init__(self, llm):
        self.llm = llm

    def generate_patch(self, issue_text, context):
        system_prompt = "You are a senior software engineer. Generate minimal, correct code patches."

        user_prompt = f"""
GitHub Issue:
{issue_text}

Relevant Code:
{context}

Generate a unified diff patch.
Return ONLY the diff.
Do not include explanations.
"""

        return self.llm.generate(system_prompt, user_prompt)
