from pathlib import Path
import importlib.util
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "sync_agent_contracts.py"
SPEC = importlib.util.spec_from_file_location("sync_agent_contracts", SCRIPT_PATH)
sync_agent_contracts = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(sync_agent_contracts)


class AgentContractTests(unittest.TestCase):
    def test_entry_files_are_generated_from_agents(self):
        self.assertEqual(sync_agent_contracts.check(), [])

    def test_agents_contains_delivery_rules(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        required = [
            "prompts/docs/",
            "name_embedded.html",
            "--doc-series",
            "风险点",
            "建议下一任务",
        ]
        for text in required:
            self.assertIn(text, agents)

    def test_gemini_imports_shared_agents_without_copying_main_rules(self):
        gemini = (ROOT / "GEMINI.md").read_text(encoding="utf-8")
        self.assertIn("@./AGENTS.md", gemini)
        self.assertNotIn("每个正式 prompt 文档必须成对交付", gemini)

    def test_claude_imports_shared_agents_without_copying_main_rules(self):
        claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("@AGENTS.md", claude)
        self.assertNotIn("每个正式 prompt 文档必须成对交付", claude)


if __name__ == "__main__":
    unittest.main()
