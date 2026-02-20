class PRWriter:

    def __init__(self, llm):
        self.llm = llm

    def generate_pr(self, issue_text, diff_output, test_status):
        prompt = f"""
        GitHub Issue:
        {issue_text}

        Code Diff:
        {diff_output}

        Test Execution Result:
        {test_status}

        STRICT INSTRUCTIONS:
        - Only describe changes that are explicitly visible in the diff.
        - If the diff contains only formatting or whitespace changes, state that clearly.
        - Do NOT assume logic changes unless shown in the diff.
        - Do NOT hallucinate modifications.
        - Base your summary entirely on the diff content.

        Write a professional pull request description including:
        - Summary of change
        - Why change was needed
        - What was modified
        - Test status
        """

        system_prompt = "You are a senior software engineer writing clean, professional GitHub pull request descriptions."

        return self.llm.generate(system_prompt, prompt)

