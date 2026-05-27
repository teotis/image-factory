import unittest
from unittest.mock import patch

from image_factory.config import DEFAULT_PROVIDER
from image_factory.providers.registry import get_provider, normalize_provider
from image_factory.providers import ProviderUnsupportedError
from image_factory.providers import openai as openai_provider


class ProviderRegistryTests(unittest.TestCase):
    def test_default_provider_is_packyapi(self):
        self.assertEqual(DEFAULT_PROVIDER, "packyapi")
        self.assertEqual(normalize_provider(""), "packyapi")
        self.assertEqual(get_provider("packyapi").__name__, "image_factory.providers.openai")

    def test_openai_provider_still_available(self):
        self.assertEqual(get_provider("openai").__name__, "image_factory.providers.openai")

    def test_gemini_cli_boundary_is_explicit_until_implemented(self):
        with self.assertRaises(ProviderUnsupportedError):
            get_provider("gemini-cli")

    def test_openai_client_uses_timeout(self):
        with patch.object(openai_provider, "assert_api_enabled"), patch.object(openai_provider, "load_env"):
            with patch("openai.OpenAI") as mock_openai:
                openai_provider.get_client(allow_api=True, base_url="https://example.test/v1", api_key="key", timeout=7)

        mock_openai.assert_called_once()
        self.assertEqual(mock_openai.call_args.kwargs["timeout"], 7)
        self.assertEqual(mock_openai.call_args.kwargs["base_url"], "https://example.test/v1")


if __name__ == "__main__":
    unittest.main()
