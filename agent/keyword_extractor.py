import re

_UPPER_SNAKE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_CAMEL = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")
_BACKTICKED = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`")

MAX_IDENTIFIERS = 10


class KeywordExtractor:

    def __init__(self, llm):
        self.llm = llm

    @staticmethod
    def extract_identifiers(issue_text: str) -> list:
        """
        Code identifiers named in the issue (CONSTANTS, snake_case, CamelCase, `backticked`).
        Plain regex, no LLM. These are looked up in the repo to find where they are defined.
        """
        found = []

        def add(name):
            if len(name) >= 4 and name not in found:
                found.append(name)

        for match in _BACKTICKED.finditer(issue_text):
            # `Rules.INLINE_ONLY_ABBRVS` -> INLINE_ONLY_ABBRVS
            last = match.group(1).split(".")[-1]
            if "_" in last or _CAMEL.fullmatch(last):
                add(last)

        for pattern in (_UPPER_SNAKE, _CAMEL, _SNAKE):
            for match in pattern.finditer(issue_text):
                add(match.group(0))

        return found[:MAX_IDENTIFIERS]

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
