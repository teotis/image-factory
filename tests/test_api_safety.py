import os
import unittest

from image_factory.providers import openai as openai_provider
from image_factory.openai_batch import ApiDisabledError, assert_api_enabled


class ApiSafetyTests(unittest.TestCase):
    def setUp(self):
        self.original_load_env = openai_provider.load_env
        openai_provider.load_env = lambda: None

    def tearDown(self):
        openai_provider.load_env = self.original_load_env

    def test_api_disabled_by_default(self):
        old_value = os.environ.pop("IMAGE_FACTORY_API_ENABLED", None)
        try:
            with self.assertRaises(ApiDisabledError):
                assert_api_enabled(allow_api=True)
        finally:
            if old_value is not None:
                os.environ["IMAGE_FACTORY_API_ENABLED"] = old_value

    def test_api_requires_cli_confirmation_even_when_env_enabled(self):
        old_value = os.environ.get("IMAGE_FACTORY_API_ENABLED")
        os.environ["IMAGE_FACTORY_API_ENABLED"] = "1"
        try:
            with self.assertRaises(ApiDisabledError):
                assert_api_enabled(allow_api=False)
        finally:
            if old_value is None:
                os.environ.pop("IMAGE_FACTORY_API_ENABLED", None)
            else:
                os.environ["IMAGE_FACTORY_API_ENABLED"] = old_value


if __name__ == "__main__":
    unittest.main()
