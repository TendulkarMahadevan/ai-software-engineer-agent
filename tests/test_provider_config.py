import os
import stat
import tempfile
import unittest
from unittest import mock

from llm import provider_config as pc

ENV_KEYS = ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "OPENAI_API_KEY", "AI_AGENT_CONFIG_DIR")


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["AI_AGENT_CONFIG_DIR"] = self.tmp.name


class ResolveTests(ConfigTestCase):
    def test_nothing_configured_returns_none(self):
        self.assertIsNone(pc.resolve())

    def test_saved_config_is_used(self):
        pc.save_config(pc.LLMConfig("ollama", "http://localhost:11434/v1", "m1"))
        cfg = pc.resolve()
        self.assertEqual((cfg.provider, cfg.model), ("ollama", "m1"))

    def test_env_overrides_saved(self):
        pc.save_config(pc.LLMConfig("ollama", "http://localhost:11434/v1", "m1"))
        os.environ["LLM_MODEL"] = "other"
        cfg = pc.resolve()
        self.assertEqual(cfg.model, "other")
        self.assertEqual(cfg.base_url, "http://localhost:11434/v1")
        self.assertEqual(cfg.provider, "env")

    def test_legacy_openai_key_still_works(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        cfg = pc.resolve()
        self.assertEqual(cfg.provider, "openai")
        self.assertEqual(cfg.api_key, "sk-test")

    def test_saved_config_beats_legacy_key(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        pc.save_config(pc.LLMConfig("ollama", "http://localhost:11434/v1", "m1"))
        self.assertEqual(pc.resolve().provider, "ollama")

    def test_url_without_model_is_an_error(self):
        os.environ["LLM_BASE_URL"] = "https://example.com/v1"
        with self.assertRaises(pc.ConfigError):
            pc.resolve()

    def test_ensure_configured_non_interactive_fails_clearly(self):
        with mock.patch("sys.stdin.isatty", return_value=False):
            with self.assertRaises(pc.ConfigError) as ctx:
                pc.ensure_configured()
        self.assertIn("--setup", str(ctx.exception))


class SaveTests(ConfigTestCase):
    def test_file_is_owner_only(self):
        path = pc.save_config(pc.LLMConfig("openai", "https://x/v1", "m", "secret"))
        mode = stat.S_IMODE(os.stat(path).st_mode)
        self.assertEqual(mode, 0o600)

    def test_corrupt_file_is_ignored(self):
        os.makedirs(self.tmp.name, exist_ok=True)
        with open(pc.config_path(), "w") as f:
            f.write("{not json")
        self.assertIsNone(pc.load_saved())

    def test_overwrite_replaces_old_choice(self):
        pc.save_config(pc.LLMConfig("ollama", "http://localhost:11434/v1", "a"))
        pc.save_config(pc.LLMConfig("openai", "https://api.openai.com/v1", "b", "k"))
        cfg = pc.load_saved()
        self.assertEqual((cfg.provider, cfg.model, cfg.api_key), ("openai", "b", "k"))


def scripted(answers):
    it = iter(answers)
    return lambda prompt="": next(it)


class SetupMenuTests(ConfigTestCase):
    def run_menu(self, answers, key="", check_result=(True, "ok")):
        lines = []
        cfg = pc.run_setup(
            input_fn=scripted(answers),
            print_fn=lines.append,
            getpass_fn=lambda prompt="": key,
            check=lambda cfg: check_result,
        )
        return cfg, "\n".join(lines)

    def test_default_choice_is_local_ollama_without_key(self):
        cfg, _ = self.run_menu(["", ""])  # tier default, model default
        self.assertEqual(cfg.provider, "ollama")
        self.assertEqual(cfg.api_key, "")
        self.assertEqual(pc.load_saved().provider, "ollama")

    def test_paid_openai_choice_saves_key(self):
        cfg, _ = self.run_menu(["3", "1", ""], key="sk-abc")
        self.assertEqual((cfg.provider, cfg.model), ("openai", "gpt-4o-mini"))
        self.assertEqual(pc.load_saved().api_key, "sk-abc")

    def test_openrouter_requires_a_model_name(self):
        # tier 2, provider 3 (openrouter), empty model -> menu restarts; then valid answers
        cfg, out = self.run_menu(["2", "3", "", "1", "", "", ], key="gk")
        self.assertIn("model name is required", out)
        self.assertEqual(cfg.provider, "ollama")

    def test_key_never_printed(self):
        _, out = self.run_menu(["3", "1", ""], key="sk-very-secret")
        self.assertNotIn("sk-very-secret", out)

    def test_failed_check_can_be_declined_and_menu_restarts(self):
        results = iter([(False, "Ollama is not running."), (True, "ok")])
        answers = ["1", "", "n",      # local, default model, decline to save
                   "1", ""]           # local again, accepted
        lines = []
        cfg = pc.run_setup(
            input_fn=scripted(answers),
            print_fn=lines.append,
            getpass_fn=lambda prompt="": "",
            check=lambda cfg: next(results),
        )
        self.assertEqual(cfg.provider, "ollama")
        self.assertIn("Ollama is not running.", "\n".join(lines))

    def test_failed_check_can_be_saved_anyway(self):
        cfg, _ = self.run_menu(["1", "", "y"], check_result=(False, "not running"))
        self.assertEqual(pc.load_saved().provider, "ollama")

    def test_invalid_tier_reprompts(self):
        cfg, out = self.run_menu(["9", "1", ""])
        self.assertIn("Please type 1, 2 or 3", out)
        self.assertEqual(cfg.provider, "ollama")

    def test_missing_key_for_paid_provider_reprompts(self):
        calls = iter(["", "sk-real"])
        lines = []
        cfg = pc.run_setup(
            input_fn=scripted(["3", "1", "", "3", "1", ""]),
            print_fn=lines.append,
            getpass_fn=lambda prompt="": next(calls),
            check=lambda cfg: (True, "ok"),
        )
        self.assertIn("API key is required", "\n".join(lines))
        self.assertEqual(cfg.api_key, "sk-real")

    def test_custom_endpoint_rejects_bad_url(self):
        cfg, out = self.run_menu(["3", "3", "not-a-url", "1", ""], key="")
        self.assertIn("must start with http", out)

    def test_eof_becomes_config_error(self):
        def raise_eof(prompt=""):
            raise EOFError
        with self.assertRaises(pc.ConfigError):
            pc.run_setup(input_fn=raise_eof, print_fn=lambda *_: None)


class ClassifyErrorTests(unittest.TestCase):
    def test_kinds(self):
        def make(name):
            return type(name, (Exception,), {})()
        self.assertEqual(pc.classify_error(make("APIConnectionError")), "connection")
        self.assertEqual(pc.classify_error(make("AuthenticationError")), "auth")
        self.assertEqual(pc.classify_error(make("NotFoundError")), "model")
        self.assertEqual(pc.classify_error(make("RateLimitError")), "rate_limit")
        self.assertIsNone(pc.classify_error(ValueError("x")))

    def test_hint_mentions_ollama_pull_for_missing_local_model(self):
        cfg = pc.LLMConfig("ollama", "http://localhost:11434/v1", "qwen2.5-coder:7b")
        self.assertIn("ollama pull qwen2.5-coder:7b", pc.error_hint("model", cfg))


class ConnectionCheckTests(unittest.TestCase):
    def fake_response(self, status, payload=None):
        r = mock.Mock()
        r.status_code = status
        r.json.return_value = payload or {}
        return r

    def test_ollama_not_running(self):
        import requests
        cfg = pc.LLMConfig("ollama", "http://localhost:11434/v1", "m:1")
        with mock.patch("requests.get", side_effect=requests.ConnectionError):
            ok, msg = pc.check_connection(cfg)
        self.assertFalse(ok)
        self.assertIn("not running", msg)

    def test_ollama_model_missing(self):
        cfg = pc.LLMConfig("ollama", "http://localhost:11434/v1", "m:1")
        resp = self.fake_response(200, {"models": [{"name": "other:latest"}]})
        with mock.patch("requests.get", return_value=resp):
            ok, msg = pc.check_connection(cfg)
        self.assertFalse(ok)
        self.assertIn("ollama pull m:1", msg)

    def test_ollama_ok_and_bare_name_matches_latest(self):
        cfg = pc.LLMConfig("ollama", "http://localhost:11434/v1", "llama3")
        resp = self.fake_response(200, {"models": [{"name": "llama3:latest"}]})
        with mock.patch("requests.get", return_value=resp):
            ok, _ = pc.check_connection(cfg)
        self.assertTrue(ok)

    def test_hosted_bad_key(self):
        cfg = pc.LLMConfig("groq", "https://api.groq.com/openai/v1", "m", "bad")
        with mock.patch("requests.get", return_value=self.fake_response(401)):
            ok, msg = pc.check_connection(cfg)
        self.assertFalse(ok)
        self.assertIn("rejected", msg)

    def test_hosted_404_on_models_is_accepted(self):
        cfg = pc.LLMConfig("custom", "https://example.com/v1", "m", "k")
        with mock.patch("requests.get", return_value=self.fake_response(404)):
            ok, _ = pc.check_connection(cfg)
        self.assertTrue(ok)

    def test_network_error_never_raises(self):
        import requests
        cfg = pc.LLMConfig("custom", "https://example.com/v1", "m", "k")
        with mock.patch("requests.get", side_effect=requests.Timeout):
            ok, msg = pc.check_connection(cfg)
        self.assertFalse(ok)


class LegacyKeyPromptTests(ConfigTestCase):
    def setUp(self):
        super().setUp()
        os.environ["OPENAI_API_KEY"] = "sk-env"

    def ensure(self, answer, tty=True):
        with mock.patch("sys.stdin.isatty", return_value=tty):
            return pc.ensure_configured(input_fn=lambda prompt="": answer)

    def test_enter_keeps_openai_and_remembers_without_copying_key(self):
        cfg = self.ensure("")
        self.assertEqual((cfg.provider, cfg.api_key, cfg.source), ("openai", "sk-env", "saved"))
        self.assertEqual(pc.load_saved().api_key, "")  # key stays in the environment

    def test_choice_is_remembered_so_second_run_does_not_ask(self):
        self.ensure("")
        with mock.patch("sys.stdin.isatty", return_value=True):
            cfg = pc.ensure_configured(input_fn=lambda prompt="": self.fail("asked again"))
        self.assertEqual(cfg.provider, "openai")

    def test_s_opens_setup_menu(self):
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch.object(pc, "run_setup", return_value="MENU") as menu:
            result = pc.ensure_configured(input_fn=lambda prompt="": "s")
        self.assertEqual(result, "MENU")
        menu.assert_called_once()

    def test_non_interactive_uses_legacy_key_silently(self):
        cfg = self.ensure("", tty=False)
        self.assertEqual((cfg.provider, cfg.source), ("openai", "legacy"))
        self.assertIsNone(pc.load_saved())

    def test_source_is_never_written_to_disk(self):
        path = pc.save_config(pc.LLMConfig("openai", "https://x/v1", "m", "", source="legacy"))
        with open(path) as f:
            self.assertNotIn("source", f.read())

    def test_describe_names_provider_model_and_origin(self):
        self.assertIn("OPENAI_API_KEY", pc.describe(pc.resolve()))
        os.environ["LLM_MODEL"] = "m9"
        text = pc.describe(pc.resolve())
        self.assertIn("m9", text)
        self.assertIn("--setup", text)


if __name__ == "__main__":
    unittest.main()
