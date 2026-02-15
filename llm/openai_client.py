import time
from openai import OpenAI, RateLimitError
from config.settings import OPENAI_API_KEY


class LLMClient:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        retries = 3

        for attempt in range(retries):
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    temperature=0,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]
                )

                return response.choices[0].message.content.strip()

            except RateLimitError:
                if attempt < retries - 1:
                    print("Rate limit hit. Retrying...")
                    time.sleep(2)
                else:
                    raise
