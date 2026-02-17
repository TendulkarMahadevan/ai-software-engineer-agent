class KeywordExtractor:

    def __init__(self, llm):
        self.llm = llm

    def extract(self, issue_text: str) -> list:
        system_prompt = "You are an expert software engineer."

        user_prompt = f"""
Analyze the following GitHub issue and extract 3 to 5 broad technical search terms
that are likely to appear directly in source code.

Guidelines:
- Prefer module names (e.g., gateway, auth, cli, tui)
- Prefer feature names (e.g., scope, validation, token)
- Avoid long compound error strings
- Avoid full error messages
- Avoid punctuation

Return ONLY a comma-separated list of simple search terms.
No explanations.

Issue:
{issue_text}
"""


        response = self.llm.generate(system_prompt, user_prompt)

        # Clean response into list
        keywords = [k.strip() for k in response.split(",") if k.strip()]
        return keywords[:5]
