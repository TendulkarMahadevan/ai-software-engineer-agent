class PRWriter:

    def __init__(self, llm):
        self.llm = llm

    def generate_pr(self, issue_text, patch):
        system_prompt = "You are a professional open-source contributor."

        user_prompt = f"""
Issue:
{issue_text}

Patch:
{patch}

Write a professional pull request description including:
- Problem
- Root Cause
- Fix
- Testing Notes
"""

        return self.llm.generate(system_prompt, user_prompt)
