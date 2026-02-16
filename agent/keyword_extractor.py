class KeywordExtractor:

    def __init__(self, llm):
        self.llm = llm

    def extract(self, issue_text: str) -> list:
        system_prompt = "You are an expert software engineer."

        user_prompt = f"""
Analyze the following GitHub issue and extract 3 to 5 highly relevant technical keywords.

Focus on:
- Component names
- Function names
- Error messages
- Feature names
- Module names

Return ONLY a comma-separated list of keywords.
No explanations.

Issue:
{issue_text}
"""

        response = self.llm.generate(system_prompt, user_prompt)

        # Clean response into list
        keywords = [k.strip() for k in response.split(",") if k.strip()]
        return keywords[:5]
