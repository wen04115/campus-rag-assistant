import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from langchain_core.documents import Document
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from app import knowledge_chat as api
from app.models import Base, KnowledgeBase, KnowledgeDocument, User


class KnowledgeChatTests(unittest.TestCase):
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
        self.collection_name = f"kb_{library.id}_{'a' * 32}"
        library.index_collection = self.collection_name

        document = KnowledgeDocument(
            original_name="test.txt",
            storage_name=f"{'b' * 32}.txt",
            size=5,
            knowledge_base_id=library.id,
        )
        self.db.add(document)
        self.db.flush()
        self.document_id = document.id
        self.db.commit()

        # 替换实际向量库、嵌入模型和聊天模型。
        self.chroma = self.mock_attribute("Chroma")
        self.embeddings = self.mock_attribute("_embeddings")
        self.model = self.mock_attribute("ChatOpenAI")
        self.prompt = self.mock_attribute("PROMPT")

        self.store = self.chroma.return_value
        self.chain = self.prompt.__or__.return_value
        self.chain.invoke.return_value = SimpleNamespace(
            content="这是测试回答",
        )

        self.store.similarity_search.return_value = [
            Document(
                page_content="只属于A的测试资料",
                metadata={
                    "knowledge_base_id": self.library_id,
                    "document_id": self.document_id,
                    "source": "test.txt",
                    "page": 1,
                    "chunk_index": 1,
                },
            )
        ]

    def mock_attribute(self, name):
        patcher = patch.object(api, name)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def ask(self, owner):
        return api.chat_with_knowledge_base(
            knowledge_base_id=self.library_id,
            payload=api.KnowledgeQuestion(question="资料说了什么？"),
            db=self.db,
            current_user=owner,
        )

    def assert_no_external_calls(self):
        self.chroma.assert_not_called()
        self.embeddings.assert_not_called()
        self.model.assert_not_called()

    def test_owner_uses_only_assigned_collection(self):
        result = self.ask(self.user_a)

        self.assertEqual(result["answer"], "这是测试回答")
        self.assertEqual(
            result["knowledge_base_id"],
            self.library_id,
        )
        self.assertEqual(result["sources"], ["test.txt"])
        self.assertEqual(
            result["citations"][0]["document_id"],
            self.document_id,
        )

        arguments = self.chroma.call_args.kwargs
        self.assertEqual(
            arguments["collection_name"],
            self.collection_name,
        )
        self.assertFalse(
            arguments["create_collection_if_not_exists"]
        )

        self.store.similarity_search.assert_called_once_with(
            "资料说了什么？",
            k=4,
            filter={"knowledge_base_id": self.library_id},
        )
        self.model.assert_called_once()
        self.chain.invoke.assert_called_once()

    def test_other_user_is_rejected_before_retrieval(self):
        with self.assertRaises(HTTPException) as caught:
            self.ask(self.user_b)

        self.assertEqual(caught.exception.status_code, 404)
        self.assert_no_external_calls()

    def test_invalidated_index_does_not_call_model(self):
        self.db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id == self.library_id)
            .values(index_collection=None)
        )
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            self.ask(self.user_a)

        self.assertEqual(caught.exception.status_code, 409)
        self.assert_no_external_calls()

    def test_shared_collection_is_not_allowed(self):
        self.db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id == self.library_id)
            .values(index_collection="intern_rag")
        )
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            self.ask(self.user_a)

        self.assertEqual(caught.exception.status_code, 500)
        self.assert_no_external_calls()

    def test_invalid_chunk_ownership_does_not_call_model(self):
        cases = [
            {
                "knowledge_base_id": self.library_id + 100,
                "document_id": self.document_id,
            },
            {
                "knowledge_base_id": self.library_id,
                "document_id": self.document_id + 100,
            },
        ]

        for metadata in cases:
            with self.subTest(metadata=metadata):
                self.store.similarity_search.return_value = [
                    Document(
                        page_content="不应发送给模型的资料",
                        metadata=metadata,
                    )
                ]

                with self.assertRaises(HTTPException) as caught:
                    self.ask(self.user_a)

                self.assertEqual(caught.exception.status_code, 409)
                self.model.assert_not_called()
                self.chain.invoke.assert_not_called()

    def test_empty_search_does_not_call_model(self):
        self.store.similarity_search.return_value = []

        result = self.ask(self.user_a)

        self.assertEqual(
            result["answer"],
            "知识库中没有找到相关信息。",
        )
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["citations"], [])
        self.model.assert_not_called()
        self.chain.invoke.assert_not_called()

    def test_index_change_during_generation_rejects_answer(self):
        def generate_and_invalidate(_inputs):
            self.db.execute(
                update(KnowledgeBase)
                .where(KnowledgeBase.id == self.library_id)
                .values(index_collection=None)
            )
            self.db.commit()
            return SimpleNamespace(content="不应返回的旧索引回答")

        self.chain.invoke.side_effect = generate_and_invalidate

        with self.assertRaises(HTTPException) as caught:
            self.ask(self.user_a)

        self.assertEqual(caught.exception.status_code, 409)
        self.chain.invoke.assert_called_once()