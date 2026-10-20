import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, delete, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import knowledge_index as api
from app.models import Base, KnowledgeBase, KnowledgeDocument, User


class KnowledgeIndexTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)

        self.db = Session(engine)
        self.addCleanup(self.db.close)

        self.user_a = User(username="test_a", hashed_password="unused")
        self.user_b = User(username="test_b", hashed_password="unused")
        self.db.add_all([self.user_a, self.user_b])
        self.db.flush()

        library = KnowledgeBase(
            name="A的知识库",
            user_id=self.user_a.id,
        )
        self.db.add(library)
        self.db.flush()

        self.library_id = library.id
        self.old_collection = f"kb_{library.id}_{'a' * 32}"
        self.new_collection = f"kb_{library.id}_{'b' * 32}"
        library.index_collection = self.old_collection

        document = KnowledgeDocument(
            original_name="test.txt",
            storage_name=f"{'c' * 32}.txt",
            size=5,
            knowledge_base_id=library.id,
        )
        self.db.add(document)
        self.db.flush()
        self.document_id = document.id
        self.db.commit()

        patcher = patch.object(api, "build_knowledge_base_index")
        self.builder = patcher.start()
        self.addCleanup(patcher.stop)

        self.build_result = {
            "collection_name": self.new_collection,
            "documents": 1,
            "chunks": 2,
        }
        self.builder.return_value = self.build_result

    def build(self, owner):
        return api.create_knowledge_base_index(
            knowledge_base_id=self.library_id,
            db=self.db,
            current_user=owner,
        )

    def current_collection(self):
        return self.db.get(
            KnowledgeBase,
            self.library_id,
        ).index_collection

    def test_owner_can_switch_to_new_index(self):
        result = self.build(self.user_a)

        self.assertEqual(
            self.current_collection(),
            self.new_collection,
        )
        self.assertEqual(result["knowledge_base_id"], self.library_id)
        self.assertEqual(result["documents"], 1)
        self.assertEqual(result["chunks"], 2)

        self.builder.assert_called_once()
        library_id, documents = self.builder.call_args.args

        self.assertEqual(library_id, self.library_id)
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].id, self.document_id)
        self.assertEqual(
            documents[0].knowledge_base_id,
            self.library_id,
        )
        self.assertEqual(documents[0].original_name, "test.txt")

    def test_other_user_cannot_build_index(self):
        with self.assertRaises(HTTPException) as caught:
            self.build(self.user_b)

        self.assertEqual(caught.exception.status_code, 404)
        self.builder.assert_not_called()
        self.assertEqual(
            self.current_collection(),
            self.old_collection,
        )

    def test_empty_library_does_not_start_build(self):
        # 只清理内存数据库中的测试记录。
        self.db.execute(
            delete(KnowledgeDocument).where(
                KnowledgeDocument.knowledge_base_id == self.library_id
            )
        )
        self.db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id == self.library_id)
            .values(index_collection=None)
        )
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            self.build(self.user_a)

        self.assertEqual(caught.exception.status_code, 400)
        self.builder.assert_not_called()
        self.assertIsNone(self.current_collection())

    def test_build_failure_preserves_old_index(self):
        self.builder.side_effect = RuntimeError("test build failure")

        with self.assertLogs(api.logger, level="ERROR"):
            with self.assertRaises(HTTPException) as caught:
                self.build(self.user_a)

        self.assertEqual(caught.exception.status_code, 500)
        self.assertEqual(
            self.current_collection(),
            self.old_collection,
        )

    def test_document_change_prevents_index_switch(self):
        def build_and_change_documents(_library_id, _documents):
            self.db.add(
                KnowledgeDocument(
                    original_name="new.txt",
                    storage_name=f"{'d' * 32}.txt",
                    size=3,
                    knowledge_base_id=self.library_id,
                )
            )

            # 模拟上传操作：文档变化，同时让旧索引失效。
            self.db.execute(
                update(KnowledgeBase)
                .where(KnowledgeBase.id == self.library_id)
                .values(index_collection=None)
            )
            self.db.commit()
            return self.build_result

        self.builder.side_effect = build_and_change_documents

        with self.assertLogs(api.logger, level="WARNING"):
            with self.assertRaises(HTTPException) as caught:
                self.build(self.user_a)

        self.assertEqual(caught.exception.status_code, 409)
        self.assertIsNone(self.current_collection())
        self.assertNotEqual(
            self.current_collection(),
            self.new_collection,
        )

    def test_commit_failure_preserves_old_index(self):
        # 模拟提交前异常，不代表真实连接中断后的提交状态。
        with patch.object(
            self.db,
            "commit",
            side_effect=SQLAlchemyError("test commit failure"),
        ):
            with self.assertLogs(api.logger, level="ERROR"):
                with self.assertRaises(HTTPException) as caught:
                    self.build(self.user_a)

        self.assertEqual(caught.exception.status_code, 500)
        self.assertEqual(
            self.current_collection(),
            self.old_collection,
        )