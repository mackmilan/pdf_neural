import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectMemoryStructureTest(unittest.TestCase):
    def test_versioned_memory_files_exist(self):
        expected = (
            "AGENTS.md",
            "CLAUDE.md",
            "docs/ai/README.md",
            "docs/ai/project-context.md",
            "docs/ai/decisions.md",
            "docs/ai/memory-log.md",
            "docs/ai/adapter-prompt.md",
        )

        for relative_path in expected:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((ROOT / relative_path).is_file())

    def test_providers_share_the_same_bootstrap(self):
        self.assertIn("@AGENTS.md", (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("docs/ai/README.md", agents)
        self.assertIn("OpenAI Codex", agents)
        self.assertIn("Claude Code", agents)

    def test_memory_log_entries_have_required_metadata(self):
        log = (ROOT / "docs/ai/memory-log.md").read_text(encoding="utf-8")

        for field in ("type", "evidence", "confidence", "review_when"):
            with self.subTest(field=field):
                self.assertIn(f"- **{field}:**", log)

        self.assertIn("append-only", log)
        self.assertIn("[VALOR_SENSIVEL_REDACTED]", log)


if __name__ == "__main__":
    unittest.main()
