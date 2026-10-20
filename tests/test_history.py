import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# 避免导入接口时初始化真实数据库。
with patch("sqlite3.connect"):
    from app import main


class HistoryTests(unittest.TestCase):
    def setUp(self):
        # 测试文件只放在项目的 D 盘 outputs 目录。
        output_dir = Path(__file__).resolve().parents[1] / "outputs"
        output_dir.mkdir(exist_ok=True)

        temporary = TemporaryDirectory(
            prefix="history_test_",
            dir=output_dir,
        )
        self.addCleanup(temporary.cleanup)

        self.database = Path(temporary.name) / "history.db"

        patcher = patch.object(main, "HISTORY_DB", self.database)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_upgrade_preserves_old_record(self):
        old_record = (
            "旧问题",
            "旧回答",
            '["旧文件.md"]',
            "2026-10-01 10:00:00",
        )

        with closing(sqlite3.connect(self.database)) as conn:
            conn.execute(
                """
                CREATE TABLE chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    sources TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO chat_history
                (question, answer, sources, created_at)
                VALUES (?, ?, ?, ?)
                """,
                old_record,
            )
            conn.commit()

        # 连续运行两次，验证不会重复添加字段。
        main.init_history_database()
        main.init_history_database()

        with closing(sqlite3.connect(self.database)) as conn:
            rows = conn.execute(
                """
                SELECT question, answer, sources, created_at
                FROM chat_history
                """
            ).fetchall()

        self.assertEqual(rows, [old_record])

        history = main.get_history()
        self.assertEqual(len(history), 1)
        self.assertIsNone(history[0]["search_source"])
        self.assertEqual(history[0]["citations"], [])

    def test_new_records_preserve_scope_and_citations(self):
        main.init_history_database()

        citations = [{
            "source": "测试.pdf",
            "page": 2,
            "chunk_index": 3,
            "excerpt": "测试片段",
        }]
        result = {
            "answer": "测试回答",
            "sources": ["测试.pdf"],
            "citations": citations,
        }

        main.save_chat_history(
            "指定文件问题",
            result,
            source="测试.pdf",
        )
        main.save_chat_history("全部文件问题", result)

        records = {
            item["question"]: item
            for item in main.get_history()
        }

        selected = records["指定文件问题"]
        self.assertEqual(selected["search_source"], "测试.pdf")
        self.assertEqual(selected["citations"], citations)
        self.assertEqual(selected["answer"], "测试回答")

        self.assertEqual(
            records["全部文件问题"]["search_source"],
            "",
        )