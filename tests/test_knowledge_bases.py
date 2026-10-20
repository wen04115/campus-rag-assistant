import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import knowledge_bases as api
from app.models import Base, User


class KnowledgeBaseTests(unittest.TestCase):
    def setUp(self):
        # 只使用内存数据库，不连接真实 MySQL。
        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)

        self.db = Session(engine)
        self.addCleanup(self.db.close)

        self.user_a = User(
            username="test_a",
            hashed_password="unused",
        )
        self.user_b = User(
            username="test_b",
            hashed_password="unused",
        )
        self.db.add_all([self.user_a, self.user_b])
        self.db.commit()

    def create_library(self, owner, name):
        return api.create_knowledge_base(
            payload=api.KnowledgeBaseCreate(name=name),
            db=self.db,
            current_user=owner,
        )

    def test_create_and_list_only_own_libraries(self):
        library_a = self.create_library(self.user_a, "A的知识库")
        self.create_library(self.user_b, "B的知识库")

        self.assertEqual(library_a.user_id, self.user_a.id)

        result = api.list_knowledge_bases(
            page=1,
            size=20,
            db=self.db,
            current_user=self.user_a,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(
            [item.id for item in result["items"]],
            [library_a.id],
        )

    def test_other_user_cannot_read_or_rename(self):
        library = self.create_library(self.user_a, "原名称")
        library_id = library.id

        with self.assertRaises(HTTPException) as caught:
            api.read_knowledge_base(
                knowledge_base_id=library_id,
                db=self.db,
                current_user=self.user_b,
            )
        self.assertEqual(caught.exception.status_code, 404)

        with self.assertRaises(HTTPException) as caught:
            api.rename_knowledge_base(
                knowledge_base_id=library_id,
                payload=api.KnowledgeBaseCreate(name="越权修改"),
                db=self.db,
                current_user=self.user_b,
            )
        self.assertEqual(caught.exception.status_code, 404)

        self.db.refresh(library)
        self.assertEqual(library.name, "原名称")

    def test_owner_can_read_and_rename(self):
        library = self.create_library(self.user_a, "旧名称")
        library_id = library.id

        result = api.read_knowledge_base(
            knowledge_base_id=library_id,
            db=self.db,
            current_user=self.user_a,
        )
        self.assertEqual(result.name, "旧名称")

        result = api.rename_knowledge_base(
            knowledge_base_id=library_id,
            payload=api.KnowledgeBaseCreate(name="新名称"),
            db=self.db,
            current_user=self.user_a,
        )

        self.assertEqual(result.id, library_id)
        self.db.refresh(library)
        self.assertEqual(library.name, "新名称")

    def test_other_user_cannot_delete(self):
        library = self.create_library(self.user_a, "不能被别人删除")
        library_id = library.id

        with self.assertRaises(HTTPException) as caught:
            api.delete_knowledge_base(
                knowledge_base_id=library_id,
                db=self.db,
                current_user=self.user_b,
            )

        self.assertEqual(caught.exception.status_code, 404)

        result = api.read_knowledge_base(
            knowledge_base_id=library_id,
            db=self.db,
            current_user=self.user_a,
        )
        self.assertEqual(result.name, "不能被别人删除")

    def test_owner_can_delete_only_once(self):
        library = self.create_library(self.user_a, "删除测试")
        library_id = library.id

        result = api.delete_knowledge_base(
            knowledge_base_id=library_id,
            db=self.db,
            current_user=self.user_a,
        )
        self.assertEqual(result["message"], "知识库已删除")

        with self.assertRaises(HTTPException) as caught:
            api.read_knowledge_base(
                knowledge_base_id=library_id,
                db=self.db,
                current_user=self.user_a,
            )
        self.assertEqual(caught.exception.status_code, 404)

        with self.assertRaises(HTTPException) as caught:
            api.delete_knowledge_base(
                knowledge_base_id=library_id,
                db=self.db,
                current_user=self.user_a,
            )
        self.assertEqual(caught.exception.status_code, 404)