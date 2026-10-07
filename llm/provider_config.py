"""
LLM provider selection: which AI backend the agent uses, and how users switch.

Every option is an OpenAI-compatible endpoint, so a choice is just three values:
base_url, model and api_key.

Resolution order (first match wins):
  1. LLM_BASE_URL / LLM_MODEL / LLM_API_KEY environment variables (also read from .env)
  2. The saved choice in ~/.config/ai-engineer-agent/config.json
  3. Legacy OPENAI_API_KEY (keeps older setups working)
"""

import getpass
import json
import os
import sys
from dataclasses import asdict, dataclass

import requests
from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    """Raised when no usable LLM configuration exists or setup is cancelled."""


@dataclass
class LLMConfig:
    provider: str
    base_url: str
    model: str
    api_key: str = ""

    @property
    def is_ollama(self):
        return self.provider == "ollama" or ":11434" in self.base_url


# Default models change often. They are only starting points: setup lets the user
# type any model name their provider supports.
PROVIDERS = {
    "ollama": {
        "label": "Ollama (runs on your computer)",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5-coder:7b",
        "needs_key": False,
        "key_url": "",
    },
    "gemini": {
        "label": "Google Gemini (free tier)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.0-flash",
        "needs_key": True,
        "key_url": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "label": "Groq (free tier)",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "needs_key": True,
        "key_url": "https://console.groq.com/keys",
    },
    "openrouter": {
        "label": "OpenRouter (free and paid models)",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "",  # no safe default: the user picks one
        "needs_key": True,
        "key_url": "https://openrouter.ai/keys",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "needs_key": True,
        "key_url": "https://platform.openai.com/api-keys",
    },
    "custom": {
        "label": "Other OpenAI-compatible endpoint",
        "base_url": "",
        "model": "",
        "needs_key": True,
        "key_url": "",
    },
}

TIERS = {
    "1": ("Free, on my computer (Ollama: no key, no account)", ["ollama"]),
    "2": ("Free hosted tier (free key, rate limited)", ["gemini", "groq", "openrouter"]),
    "3": ("My own paid key (best quality)", ["openai", "openrouter", "custom"]),
}

DEFAULT_TIER = "1"


# ---------- saved config ----------

def config_dir():
    override = os.environ.get("AI_AGENT_CONFIG_DIR")
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".config", "ai-engineer-agent")


def config_path():
    return os.path.join(config_dir(), "config.json")


def load_saved():
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return LLMConfig(
            provider=data["provider"],
            base_url=data["base_url"],
            model=data["model"],
            api_key=data.get("api_key", ""),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_config(cfg):
    """Writes the config atomically with owner-only permissions (it can hold an API key)."""
    directory = config_dir()
    os.makedirs(directory, mode=0o700, exist_ok=True)

    final_path = config_path()
    tmp_path = final_path + ".tmp"

    # O_EXCL after removing a stale temp file, so the 0600 mode always applies
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)

    os.replace(tmp_path, final_path)
    return final_path


# ---------- resolution ----------

def resolve():
    """Returns the active LLMConfig, or None if nothing is configured."""
    env_url = os.getenv("LLM_BASE_URL", "").strip()
    env_model = os.getenv("LLM_MODEL", "").strip()
    env_key = os.getenv("LLM_API_KEY", "").strip()
    saved = load_saved()

    if env_url or env_model or env_key:
        if env_url:
            base_url = env_url
        elif saved:
            base_url = saved.base_url
        else:
            base_url = PROVIDERS["openai"]["base_url"]

        if env_model:
            model = env_model
        elif saved:
            model = saved.model
        elif not env_url:
            model = PROVIDERS["openai"]["model"]
        else:
            raise ConfigError("LLM_BASE_URL is set but LLM_MODEL is not. Set both.")

        api_key = env_key or (saved.api_key if saved else "")
        return LLMConfig("env", base_url, model, api_key)

    if saved:
        return saved

    legacy_key = os.getenv("OPENAI_API_KEY", "").strip()
    if legacy_key:
        return LLMConfig(
            "openai",
            PROVIDERS["openai"]["base_url"],
            PROVIDERS["openai"]["model"],
            legacy_key,
        )

    return None


def ensure_configured():
    """Returns a config, running the setup menu on first use when a human is present."""
    cfg = resolve()
    if cfg:
        return cfg

    if not sys.stdin.isatty():
        raise ConfigError(
            "No LLM configured. Run `python main.py --setup`, or set "
            "LLM_BASE_URL, LLM_MODEL and LLM_API_KEY in the environment."
        )

    print("First run: let's choose how the agent should think.\n")
    return run_setup()


# ---------- connection check ----------

def check_connection(cfg, timeout=5):
    """Returns (ok, message). Never raises."""
    try:
        if cfg.is_ollama:
            return _check_ollama(cfg, timeout)
        return _check_hosted(cfg, timeout)
    except requests.RequestException as e:
        return False, f"Could not reach {cfg.base_url}: {e.__class__.__name__}"


def _check_ollama(cfg, timeout):
    root = cfg.base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]

    try:
        response = requests.get(f"{root}/api/tags", timeout=timeout)
    except requests.ConnectionError:
        return False, ("Ollama is not running. Install it from ollama.com, then start "
                       "the app or run `ollama serve`.")

    if response.status_code != 200:
        return False, f"Ollama answered with HTTP {response.status_code}."

    names = [m.get("name", "") for m in response.json().get("models", [])]
    wanted = cfg.model
    if ":" not in wanted:
        wanted += ":latest"

    if wanted not in names:
        return False, f"Model not downloaded yet. Run: ollama pull {cfg.model}"

    return True, "Ollama is running and the model is available."


def _check_hosted(cfg, timeout):
    headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
    url = cfg.base_url.rstrip("/") + "/models"
    response = requests.get(url, headers=headers, timeout=timeout)

    if response.status_code in (401, 403):
        return False, "The provider rejected this key (HTTP %d)." % response.status_code
    if response.status_code >= 500:
        return False, f"The provider returned HTTP {response.status_code}. Try again later."

    # 404 on /models is common for compatible servers: reachable is good enough
    return True, "Provider reachable."


# ---------- error hints ----------

def classify_error(exc):
    """Maps an SDK or network exception to 'connection', 'auth', 'model', 'rate_limit' or None."""
    name = type(exc).__name__
    if name in ("APIConnectionError", "APITimeoutError", "ConnectError", "ConnectionError"):
        return "connection"
    if name in ("AuthenticationError", "PermissionDeniedError"):
        return "auth"
    if name == "NotFoundError":
        return "model"
    if name == "RateLimitError":
        return "rate_limit"
    return None


def error_hint(kind, cfg):
    if kind == "connection":
        if cfg.is_ollama:
            return "Cannot reach Ollama. Is the Ollama app running?"
        return f"Cannot reach {cfg.base_url}. Check your internet connection."
    if kind == "auth":
        return "The provider rejected your API key."
    if kind == "model":
        if cfg.is_ollama:
            return f"Model '{cfg.model}' is not available. Run: ollama pull {cfg.model}"
        return f"The provider does not know the model '{cfg.model}'."
    if kind == "rate_limit":
        return "Rate limit reached (common on free tiers)."
    return ""


# ---------- setup menu ----------

def run_setup(input_fn=input, print_fn=print, getpass_fn=getpass.getpass,
              check=check_connection, save=save_config):
    """Interactive menu. Returns the saved LLMConfig. Raises ConfigError if cancelled."""
    try:
        return _run_setup(input_fn, print_fn, getpass_fn, check, save)
    except (EOFError, KeyboardInterrupt):
        raise ConfigError("Setup cancelled.")


def _run_setup(input_fn, print_fn, getpass_fn, check, save):
    current = resolve_safely()
    if current:
        print_fn(f"Current setup: {current.provider} / {current.model}\n")

    for _ in range(10):
        print_fn("How do you want the agent to think?\n")
        for key, (label, _providers) in TIERS.items():
            print_fn(f"  {key}) {label}")
        print_fn("")

        tier = input_fn(f"Choice [{DEFAULT_TIER}]: ").strip() or DEFAULT_TIER
        if tier not in TIERS:
            print_fn("Please type 1, 2 or 3.\n")
            continue

        provider_name = _pick_provider(TIERS[tier][1], input_fn, print_fn)
        if provider_name is None:
            continue

        cfg = _collect_details(provider_name, input_fn, print_fn, getpass_fn)
        if cfg is None:
            continue

        print_fn("\nChecking connection...")
        ok, message = check(cfg)
        print_fn(("OK: " if ok else "Problem: ") + message)

        if not ok:
            answer = input_fn("Save this choice anyway? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                print_fn("")
                continue

        path = save(cfg)
        print_fn(f"\nSaved to {path}")
        print_fn("Run `python main.py --setup` any time to change this.\n")
        return cfg

    raise ConfigError("Too many invalid answers. Run `python main.py --setup` to try again.")


def resolve_safely():
    try:
        return resolve()
    except ConfigError:
        return None


def _pick_provider(names, input_fn, print_fn):
    if len(names) == 1:
        return names[0]

    print_fn("\nWhich provider?")
    for i, name in enumerate(names, start=1):
        print_fn(f"  {i}) {PROVIDERS[name]['label']}")

    answer = input_fn("Provider [1]: ").strip() or "1"
    if not answer.isdigit() or not (1 <= int(answer) <= len(names)):
        print_fn("Not a valid provider number.\n")
        return None
    return names[int(answer) - 1]


def _collect_details(provider_name, input_fn, print_fn, getpass_fn):
    preset = PROVIDERS[provider_name]
    base_url = preset["base_url"]

    if provider_name == "custom":
        base_url = input_fn("Base URL (for example https://host/v1): ").strip()
        if not base_url.startswith(("http://", "https://")):
            print_fn("The base URL must start with http:// or https://\n")
            return None

    default_model = preset["model"]
    if default_model:
        model = input_fn(f"Model [{default_model}]: ").strip() or default_model
    else:
        model = input_fn("Model name (required): ").strip()
        if not model:
            print_fn("A model name is required for this provider.\n")
            return None

    api_key = ""
    if preset["needs_key"]:
        if preset["key_url"]:
            print_fn(f"Get a key at {preset['key_url']}")
        api_key = getpass_fn("API key (hidden as you type): ").strip()
        if not api_key:
            print_fn("An API key is required for this provider.\n")
            return None

    return LLMConfig(provider_name, base_url, model, api_key)
