import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import knowledge_history as history
from app.models import (
    Base,
    KnowledgeBase,
    KnowledgeChatRecord,
    User,
)


class KnowledgeHistoryTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(engine.dispose)

        # 仅在测试内存数据库建表，不修改业务 MySQL。
        Base.metadata.create_all(engine)

        self.db = Session(engine)
        self.addCleanup(self.db.close)

        user_a = User(username="history_a", hashed_password="unused")
        user_b = User(username="history_b", hashed_password="unused")
        self.db.add_all([user_a, user_b])
        self.db.flush()

        self.user_a_id = user_a.id
        self.user_b_id = user_b.id
        self.collection = f"kb_1_{'a' * 32}"

        library = KnowledgeBase(
            name="A的测试知识库",
            user_id=self.user_a_id,
            index_collection=self.collection,
        )
        self.db.add(library)
        self.db.flush()

        self.library_id = library.id
        self.db.commit()

        self.prepared = {
            "knowledge_base_id": self.library_id,
            "user_id": self.user_a_id,
            "collection_name": self.collection,
            "sources": ["test.pdf"],
            "citations": [
                {
                    "document_id": 1,
                    "source": "test.pdf",
                    "page": 1,
                    "chunk_index": 1,
                    "excerpt": "测试资料",
                },
            ],
        }

    def count_records(self):
        return self.db.scalar(
            select(func.count()).select_from(KnowledgeChatRecord)
        )

    def save(self, prepared=None, answer="完整测试回答"):
        return history.save_chat_record(
            self.db,
            self.prepared if prepared is None else prepared,
            "测试问题",
            answer,
        )

    def test_owner_can_save_complete_record(self):
        record_id = self.save()
        record = self.db.get(KnowledgeChatRecord, record_id)

        self.assertIsNotNone(record)
        self.assertEqual(record.knowledge_base_id, self.library_id)
        self.assertEqual(record.question, "测试问题")
        self.assertEqual(record.answer, "完整测试回答")
        self.assertEqual(record.sources, self.prepared["sources"])
        self.assertEqual(record.citations, self.prepared["citations"])
        self.assertIsNotNone(record.created_at)
        self.assertEqual(self.count_records(), 1)

    def test_other_user_cannot_save(self):
        prepared = {
            **self.prepared,
            "user_id": self.user_b_id,
        }

        with self.assertRaises(HTTPException) as caught:
            self.save(prepared=prepared)

        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.count_records(), 0)

    def test_changed_index_is_rejected(self):
        self.db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id == self.library_id)
            .values(index_collection=None)
        )
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            self.save()

        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.count_records(), 0)

    def test_blank_answer_is_rejected(self):
        with self.assertRaises(ValueError):
            self.save(answer="   ")

        self.assertEqual(self.count_records(), 0)

    def test_database_failure_rolls_back(self):
        with patch.object(
            self.db,
            "commit",
            side_effect=SQLAlchemyError("simulated failure"),
        ):
            with self.assertLogs(history.logger, level="ERROR"):
                with self.assertRaises(HTTPException) as caught:
                    self.save()

        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(self.count_records(), 0)


if __name__ == "__main__":
    unittest.main()