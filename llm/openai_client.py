import sys
import time

from openai import OpenAI, RateLimitError

from llm import provider_config

MAX_RECONFIGURES = 2


class LLMClient:
    """Talks to any OpenAI-compatible endpoint chosen via llm/provider_config.py."""

    def __init__(self, config=None):
        self.config = config or provider_config.ensure_configured()
        self.client = self._build_client()
        self._reconfigures = 0

    def _build_client(self):
        # Local servers ignore the key, but the SDK requires a non-empty value
        return OpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key or "not-needed",
        )

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        retries = 3
        attempt = 0

        while True:
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    temperature=0,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]
                )

                return (response.choices[0].message.content or "").strip()

            except Exception as exc:
                if isinstance(exc, RateLimitError) and attempt < retries - 1:
                    attempt += 1
                    print("Rate limit hit. Retrying...")
                    time.sleep(2)
                    continue

                if not self._offer_reconfigure(exc):
                    raise

                attempt = 0

    def _offer_reconfigure(self, exc):
        """On a fixable provider problem, lets a human switch provider and retry."""
        kind = provider_config.classify_error(exc)
        if kind is None:
            return False

        print(f"\n[AI-ENGINEER] {provider_config.error_hint(kind, self.config)}")

        if self.config.provider == "env":
            print("[AI-ENGINEER] Settings come from LLM_* environment variables. "
                  "Change or unset them, then run again.")
            return False

        if self._reconfigures >= MAX_RECONFIGURES or not sys.stdin.isatty():
            return False

        answer = input("Open the setup menu to switch provider? [Y/n]: ").strip().lower()
        if answer in ("n", "no"):
            return False

        try:
            self.config = provider_config.run_setup()
        except provider_config.ConfigError as e:
            print(e)
            return False

        self.client = self._build_client()
        self._reconfigures += 1
        return True
