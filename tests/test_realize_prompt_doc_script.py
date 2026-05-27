from pathlib import Path
import importlib.util
import sys
import types
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "realize_prompt_doc.py"
SPEC = importlib.util.spec_from_file_location("realize_prompt_doc", SCRIPT_PATH)
realize_prompt_doc = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(realize_prompt_doc)


class RealizePromptDocScriptTests(unittest.TestCase):
    def test_parse_args_requires_explicit_html(self):
        old_argv = sys.argv
        try:
            sys.argv = ["realize_prompt_doc.py"]
            with self.assertRaises(SystemExit):
                realize_prompt_doc.parse_args()
        finally:
            sys.argv = old_argv

    def test_resolve_output_dir_uses_new_run_when_base_has_images(self):
        root = ROOT / ".tmp" / "test_runs" / uuid.uuid4().hex
        base = root / "outputs" / "prompt_docs" / "example"
        base.mkdir(parents=True)
        (base / "example_001.png").write_bytes(b"old")

        resolved = realize_prompt_doc.resolve_output_dir(base, "example", "png")

        self.assertEqual(resolved.name, "example_r2")

    def test_resolve_output_dir_uses_new_run_when_base_has_queued_tasks(self):
        from image_factory.task_queue import enqueue_tasks, init_db

        root = ROOT / ".tmp" / "test_runs" / uuid.uuid4().hex
        base = root / "outputs" / "prompt_docs" / "example"
        queue_db = root / "queue.db"
        init_db(queue_db)
        enqueue_tasks(
            db_path=queue_db,
            plan_entries=[
                {
                    "path": str(base / "example_001.png"),
                    "prompt_sha256_16": "abc",
                    "prompt_text": "prompt",
                    "prompt_title": "main",
                }
            ],
            prompt_doc_path="doc.html",
        )

        resolved = realize_prompt_doc.resolve_output_dir(base, "example", "png", queue_db=queue_db)

        self.assertEqual(resolved.name, "example_r2")

    def test_execute_path_enqueues_then_runs_workers(self):
        calls = {}
        args = types.SimpleNamespace(max_workers=2, base_url="https://example.test/v1", allow_api=True)
        html_path = ROOT / "prompts" / "docs" / "example_embedded.html"

        original_enqueue = realize_prompt_doc._run_enqueue
        original_worker_module = sys.modules.get("run_image_workers")
        from image_factory.providers import openai as openai_provider

        original_openai_assert = openai_provider.assert_api_enabled

        def fake_enqueue(received_args, received_html_path):
            calls["enqueue"] = (received_args, received_html_path)
            return {
                "count": 3,
                "db_path": ROOT / ".tmp" / "queue.db",
                "output_dir": ROOT / "outputs" / "prompt_docs" / "example",
            }

        def fake_run_workers(**kwargs):
            calls["workers"] = kwargs
            return {"done": 1, "failed": 0, "pending": 0}

        try:
            realize_prompt_doc._run_enqueue = fake_enqueue
            openai_provider.assert_api_enabled = lambda allow_api=False: calls.setdefault("allow_api", allow_api)
            sys.modules["run_image_workers"] = types.SimpleNamespace(run_workers=fake_run_workers)

            realize_prompt_doc._run_concurrent_execute(args, [html_path])
        finally:
            realize_prompt_doc._run_enqueue = original_enqueue
            openai_provider.assert_api_enabled = original_openai_assert
            if original_worker_module is None:
                sys.modules.pop("run_image_workers", None)
            else:
                sys.modules["run_image_workers"] = original_worker_module

        self.assertEqual(calls["enqueue"], (args, html_path))
        self.assertTrue(calls["allow_api"])
        self.assertEqual(calls["workers"]["queue_db"], ROOT / ".tmp" / "queue.db")
        self.assertEqual(calls["workers"]["max_workers"], 2)
        self.assertEqual(calls["workers"]["base_url"], "https://example.test/v1")


if __name__ == "__main__":
    unittest.main()
