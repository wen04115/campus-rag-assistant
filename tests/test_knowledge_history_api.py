"""HTTP integration tests against an isolated SQLite database and fake models."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import auth, knowledge_bases, knowledge_chat, knowledge_history
from app.database import get_db
from app.models import Base, KnowledgeBase, KnowledgeChatRecord, KnowledgeDocument, User
from app.security import create_access_token, hash_password


class KnowledgeHistoryAPITests(unittest.TestCase):
    def setUp(self):
        secret = patch.dict("os.environ", {"JWT_SECRET_KEY": "ci-test-key-only-" * 4})
        secret.start()
        self.addCleanup(secret.stop)
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            password = hash_password("TestPassword123!")
            a = User(username="api_a", hashed_password=password)
            b = User(username="api_b", hashed_password=password)
            db.add_all([a, b])
            db.flush()
            self.a_id, self.b_id = a.id, b.id
            one = KnowledgeBase(name="A", user_id=a.id)
            two = KnowledgeBase(name="A2", user_id=a.id)
            three = KnowledgeBase(name="B", user_id=b.id)
            db.add_all([one, two, three])
            db.flush()
            self.kb, self.other, self.b_kb = one.id, two.id, three.id
            one.index_collection = f"kb_{one.id}_{'a' * 32}"
            db.add(KnowledgeDocument(
                knowledge_base_id=one.id, original_name="test.txt",
                storage_name=f"{'a' * 32}.txt", size=4,
            ))
            db.flush()
            self.document_id = db.scalar(select(KnowledgeDocument.id))
            db.commit()

        app = FastAPI()
        for router in (auth.router, knowledge_bases.router, knowledge_chat.router, knowledge_history.router):
            app.include_router(router)

        def isolated_db():
            with Session(self.engine) as db:
                yield db

        app.dependency_overrides[get_db] = isolated_db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.a_headers = {"Authorization": f"Bearer {create_access_token(self.a_id)}"}
        self.b_headers = {"Authorization": f"Bearer {create_access_token(self.b_id)}"}
        self.path = f"/api/knowledge-bases/{self.kb}"
        self.patch_attr(knowledge_chat, "engine", self.engine)
        self.patch_attr(knowledge_chat, "_embeddings")
        store = self.patch_attr(knowledge_chat, "Chroma").return_value
        store.similarity_search.return_value = [Document(
            page_content="测试资料", metadata={
                "knowledge_base_id": self.kb, "document_id": self.document_id,
                "source": "test.txt", "chunk_index": 1,
            },
        )]
        self.patch_attr(knowledge_chat, "create_chat_model")
        self.chain = self.patch_attr(knowledge_chat, "PROMPT").__or__.return_value
        self.chain.invoke.return_value = SimpleNamespace(content="完整回答")
        self.chain.stream.return_value = iter([
            SimpleNamespace(content="完整"), SimpleNamespace(content="回答"),
        ])

    def patch_attr(self, module, name, *args):
        patcher = patch.object(module, name, *args)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def seed_record(self, kb, question):
        with Session(self.engine) as db:
            db.add(KnowledgeChatRecord(
                knowledge_base_id=kb, question=question, answer="已保存",
                sources=[], citations=[],
            ))
            db.commit()

    def history(self):
        response = self.client.get(f"{self.path}/history", headers=self.a_headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_history_requires_login(self):
        response = self.client.get(f"{self.path}/history")
        self.assertEqual(response.status_code, 401)

    def test_other_user_and_missing_library_return_404(self):
        for path, headers in (
            (f"{self.path}/history", self.b_headers),
            ("/api/knowledge-bases/999999/history", self.a_headers),
        ):
            self.assertEqual(self.client.get(path, headers=headers).status_code, 404)

    def test_history_is_scoped_sorted_paginated_and_utc(self):
        self.seed_record(self.kb, "第一条")
        self.seed_record(self.kb, "第二条")
        self.seed_record(self.other, "同用户其他库")
        self.seed_record(self.b_kb, "其他用户")
        first = self.client.get(f"{self.path}/history?size=1&page=1", headers=self.a_headers).json()
        second = self.client.get(f"{self.path}/history?size=1&page=2", headers=self.a_headers).json()
        self.assertEqual(first["total"], 2)
        self.assertEqual(first["items"][0]["question"], "第二条")
        self.assertEqual(second["items"][0]["question"], "第一条")
        self.assertTrue(first["items"][0]["created_at"].endswith("Z"))

    def test_pagination_validation(self):
        for query in ("page=0", "size=0", "size=101"):
            with self.subTest(query=query):
                response = self.client.get(f"{self.path}/history?{query}", headers=self.a_headers)
                self.assertEqual(response.status_code, 422)

    def test_deleting_empty_library_cascades_only_its_history(self):
        self.seed_record(self.other, "删除这条")
        self.seed_record(self.kb, "保留这条")
        response = self.client.delete(f"/api/knowledge-bases/{self.other}", headers=self.a_headers)
        self.assertEqual(response.status_code, 200, response.text)
        with Session(self.engine) as db:
            records = db.scalars(select(KnowledgeChatRecord)).all()
            self.assertEqual([record.question for record in records], ["保留这条"])

    def test_normal_answer_is_saved(self):
        response = self.client.post(f"{self.path}/chat", headers=self.a_headers, json={"question": "问题"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.history()["items"][0]["answer"], "完整回答")

    def test_stream_completion_is_saved(self):
        response = self.client.post(f"{self.path}/chat/stream", headers=self.a_headers, json={"question": "问题"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('"type": "done"', response.text)
        self.assertEqual(self.history()["total"], 1)

    def test_broken_stream_does_not_save_partial_answer(self):
        def broken(_inputs):
            yield SimpleNamespace(content="部分文字")
            raise RuntimeError("fake upstream failure")

        self.chain.stream.side_effect = broken
        with self.assertLogs(knowledge_chat.logger, level="ERROR"):
            response = self.client.post(f"{self.path}/chat/stream", headers=self.a_headers, json={"question": "问题"})
        self.assertIn('"type": "error"', response.text)
        self.assertNotIn('"type": "done"', response.text)
        self.assertEqual(self.history()["total"], 0)

    def test_save_failure_does_not_emit_done(self):
        save = self.patch_attr(knowledge_chat, "save_chat_record")
        save.side_effect = HTTPException(status_code=503, detail="历史保存失败")
        response = self.client.post(f"{self.path}/chat/stream", headers=self.a_headers, json={"question": "问题"})
        self.assertIn("历史保存失败", response.text)
        self.assertNotIn('"type": "done"', response.text)
        self.assertEqual(self.history()["total"], 0)

    def test_login_and_invalid_password(self):
        good = self.client.post("/api/auth/login", json={"username": "api_a", "password": "TestPassword123!"})
        bad = self.client.post("/api/auth/login", json={"username": "api_a", "password": "wrong"})
        self.assertEqual(good.status_code, 200, good.text)
        self.assertIn("access_token", good.json())
        self.assertEqual(bad.status_code, 401)


if __name__ == "__main__":
    unittest.main()
