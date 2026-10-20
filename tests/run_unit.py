"""One explicit offline suite; old live-service upload tests are intentionally excluded."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PATTERNS = (
    "test_document_loader.py", "test_documents.py", "test_kb_index.py",
    "test_knowledge_*.py", "test_retrieval.py", "test_stream_response.py",
    "test_history.py", "test_legacy_disabled.py", "test_index_cleanup.py",
    "test_frontend_serving.py",
)


def main():
    suite = unittest.TestSuite()
    for pattern in PATTERNS:
        discovered = unittest.TestLoader().discover(str(ROOT / "tests"), pattern=pattern)
        if not discovered.countTestCases():
            raise RuntimeError(f"没有发现预期测试：{pattern}")
        suite.addTests(discovered)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
