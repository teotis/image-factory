import importlib.util
from pathlib import Path
import unittest
import uuid


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_prompt_docs.py"
SPEC = importlib.util.spec_from_file_location("check_prompt_docs", SCRIPT_PATH)
check_prompt_docs = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(check_prompt_docs)


def temp_root() -> Path:
    base = Path.cwd() / ".tmp" / "test_runs"
    base.mkdir(parents=True, exist_ok=True)
    root = base / uuid.uuid4().hex
    root.mkdir()
    return root


class PromptDocsDeliveryTests(unittest.TestCase):
    def test_requires_embedded_html_pair(self):
        root = temp_root()
        docs = root / "prompts" / "docs"
        docs.mkdir(parents=True)
        (docs / "example.md").write_text("# Example\n", encoding="utf-8")

        issues = check_prompt_docs.find_delivery_issues(docs)

        self.assertEqual(issues, [f"missing embedded HTML for {docs / 'example.md'}"])

    def test_markdown_images_require_html_data_uri(self):
        root = temp_root()
        docs = root / "prompts" / "docs"
        docs.mkdir(parents=True)
        (docs / "example.md").write_text("![ref](../../assets/ref.jpg)\n", encoding="utf-8")
        (docs / "example_embedded.html").write_text('<img src="../../assets/ref.jpg">', encoding="utf-8")

        issues = check_prompt_docs.find_delivery_issues(docs)

        self.assertEqual(issues, [f"HTML does not embed image data for {docs / 'example.md'}"])

    def test_valid_pair_passes(self):
        root = temp_root()
        docs = root / "prompts" / "docs"
        docs.mkdir(parents=True)
        (docs / "example.md").write_text("![ref](../../assets/ref.jpg)\n", encoding="utf-8")
        (docs / "example_embedded.html").write_text('<img src="data:image/jpeg;base64,abc">', encoding="utf-8")

        self.assertEqual(check_prompt_docs.find_delivery_issues(docs), [])


if __name__ == "__main__":
    unittest.main()
