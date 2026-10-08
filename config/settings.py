import os
from dotenv import load_dotenv

load_dotenv()

# The LLM provider and key are handled in llm/provider_config.py
# (run `python main.py --setup`). Only GitHub access is required here.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN not found in .env")
