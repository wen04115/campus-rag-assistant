import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import documents as api
from app.models import Base, KnowledgeBase, KnowledgeDocument, User


class DocumentTests(unittest.TestCase):
    def setUp(self):
        outputs = Path(__file__).resolve().parents[1] / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)

        temporary = TemporaryDirectory(
            prefix="documents_test_",
            dir=outputs,
        )
        self.addCleanup(temporary.cleanup)
        self.storage = Path(temporary.name) / "documents"

        storage_patch = patch.object(api, "DOCUMENT_DIR", self.storage)
        storage_patch.start()
        self.addCleanup(storage_patch.stop)

        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)

        self.db = Session(engine)
        self.addCleanup(self.db.close)

        self.user_a = User(username="test_a", hashed_password="unused")
        self.user_b = User(username="test_b", hashed_password="unused")
        self.db.add_all([self.user_a, self.user_b])
        self.db.flush()

        self.library_a = KnowledgeBase(
            name="A的知识库",
            user_id=self.user_a.id,
        )
        self.library_a2 = KnowledgeBase(
            name="A的另一个知识库",
            user_id=self.user_a.id,
        )
        self.library_b = KnowledgeBase(
            name="B的知识库",
            user_id=self.user_b.id,
        )
        self.db.add_all([
            self.library_a,
            self.library_a2,
            self.library_b,
        ])
        self.db.commit()

    def upload(self, library, owner, name="test.txt", content=b"hello"):
        with BytesIO(content) as stream:
            file = UploadFile(filename=name, file=stream)
            return api.upload_document(
                knowledge_base_id=library.id,
                file=file,
                db=self.db,
                current_user=owner,
            )

    def document_count(self):
        return self.db.scalar(
            select(func.count()).select_from(KnowledgeDocument)
        )

    def stored_files(self):
        return [
            item
            for item in self.storage.rglob("*")
            if item.is_file()
        ]

    def test_upload_same_name_does_not_overwrite(self):
        first = self.upload(
            self.library_a,
            self.user_a,
            content=b"first",
        )
        second = self.upload(
            self.library_a,
            self.user_a,
            content=b"second",
        )

        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["original_name"], "test.txt")
        self.assertEqual(first["size"], 5)
        self.assertEqual(
            first["knowledge_base_id"],
            self.library_a.id,
        )

        row1 = self.db.get(KnowledgeDocument, first["id"])
        row2 = self.db.get(KnowledgeDocument, second["id"])
        self.assertNotEqual(row1.storage_name, row2.storage_name)

        directory = self.storage / str(self.library_a.id)
        self.assertEqual(
            (directory / row1.storage_name).read_bytes(),
            b"first",
        )
        self.assertEqual(
            (directory / row2.storage_name).read_bytes(),
            b"second",
        )
        self.assertEqual(self.document_count(), 2)

    def test_other_user_cannot_upload(self):
        with BytesIO(b"hello") as stream:
            file = UploadFile(filename="test.txt", file=stream)

            with patch.object(stream, "read") as read:
                with self.assertRaises(HTTPException) as caught:
                    api.upload_document(
                        knowledge_base_id=self.library_a.id,
                        file=file,
                        db=self.db,
                        current_user=self.user_b,
                    )

                self.assertEqual(caught.exception.status_code, 404)
                read.assert_not_called()

        self.assertEqual(self.document_count(), 0)
        self.assertEqual(self.stored_files(), [])

    def test_invalid_files_are_not_saved(self):
        cases = [
            ("test.exe", b"hello"),
            ("test.txt", b"\xff\xfe"),
            ("empty.txt", b""),
            ("blank.txt", b"   \n"),
            ("broken.pdf", b"not a pdf"),
        ]

        for name, content in cases:
            with self.subTest(filename=name):
                with self.assertRaises(HTTPException) as caught:
                    self.upload(
                        self.library_a,
                        self.user_a,
                        name=name,
                        content=content,
                    )

                self.assertEqual(caught.exception.status_code, 400)
                self.assertEqual(self.document_count(), 0)
                self.assertEqual(self.stored_files(), [])

    def test_oversized_file_is_not_saved(self):
        # 缩小测试限制，不必真的生成 10 MiB 文件。
        with patch.object(api, "MAX_FILE_SIZE", 8):
            with self.assertRaises(HTTPException) as caught:
                self.upload(
                    self.library_a,
                    self.user_a,
                    content=b"123456789",
                )

        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(self.document_count(), 0)
        self.assertEqual(self.stored_files(), [])

    def test_list_is_paginated_and_scoped_to_library(self):
        first = self.upload(self.library_a, self.user_a, "first.txt")
        second = self.upload(self.library_a, self.user_a, "second.txt")

        self.upload(self.library_a2, self.user_a, "another.txt")
        self.upload(self.library_b, self.user_b, "private.txt")

        page1 = api.list_documents(
            knowledge_base_id=self.library_a.id,
            page=1,
            size=1,
            db=self.db,
            current_user=self.user_a,
        )
        page2 = api.list_documents(
            knowledge_base_id=self.library_a.id,
            page=2,
            size=1,
            db=self.db,
            current_user=self.user_a,
        )

        self.assertEqual(page1["total"], 2)
        self.assertEqual(page1["page"], 1)
        self.assertEqual(page1["size"], 1)
        self.assertEqual(
            [item.id for item in page1["items"]],
            [second["id"]],
        )
        self.assertEqual(
            [item.id for item in page2["items"]],
            [first["id"]],
        )

        # 验证响应结构可以正常序列化。
        result = api.DocumentPage.model_validate(page1).model_dump()
        self.assertNotIn("storage_name", result["items"][0])

    def test_other_user_and_missing_library_return_404(self):
        cases = [
            (self.library_a.id, self.user_b),
            (999999, self.user_a),
        ]

        for library_id, owner in cases:
            with self.subTest(library_id=library_id):
                with self.assertRaises(HTTPException) as caught:
                    api.list_documents(
                        knowledge_base_id=library_id,
                        page=1,
                        size=20,
                        db=self.db,
                        current_user=owner,
                    )

                self.assertEqual(caught.exception.status_code, 404)

    def test_database_failure_cleans_up_uploaded_file(self):
        with patch.object(
            self.db,
            "commit",
            side_effect=SQLAlchemyError("test failure"),
        ):
            with self.assertLogs(api.logger, level="ERROR"):
                with self.assertRaises(HTTPException) as caught:
                    self.upload(self.library_a, self.user_a)

        self.assertEqual(caught.exception.status_code, 500)
        self.assertEqual(self.document_count(), 0)
        self.assertEqual(self.stored_files(), [])

    def test_owner_can_delete_document_only_once(self):
        uploaded = self.upload(self.library_a, self.user_a)
        kept = self.upload(self.library_a, self.user_a, "keep.txt")
        document_id = uploaded["id"]

        result = api.delete_document(
            knowledge_base_id=self.library_a.id,
            document_id=document_id,
            db=self.db,
            current_user=self.user_a,
        )

        self.assertEqual(result["message"], "文档已删除")
        self.assertFalse(result["cleanup_pending"])
        self.assertIsNone(
            self.db.get(KnowledgeDocument, document_id)
        )

        # 其他文档及其文件不能被误删。
        kept_row = self.db.get(KnowledgeDocument, kept["id"])
        self.assertIsNotNone(kept_row)

        kept_path = (
            self.storage
            / str(self.library_a.id)
            / kept_row.storage_name
        )
        self.assertEqual(kept_path.read_bytes(), b"hello")
        self.assertEqual(self.stored_files(), [kept_path])

        with self.assertRaises(HTTPException) as caught:
            api.delete_document(
                knowledge_base_id=self.library_a.id,
                document_id=document_id,
                db=self.db,
                current_user=self.user_a,
            )

        self.assertEqual(caught.exception.status_code, 404)

    def test_other_user_cannot_delete_document(self):
        uploaded = self.upload(self.library_a, self.user_a)
        document_id = uploaded["id"]
        files_before = self.stored_files()

        with self.assertRaises(HTTPException) as caught:
            api.delete_document(
                knowledge_base_id=self.library_a.id,
                document_id=document_id,
                db=self.db,
                current_user=self.user_b,
            )

        self.assertEqual(caught.exception.status_code, 404)
        self.assertIsNotNone(
            self.db.get(KnowledgeDocument, document_id)
        )
        self.assertEqual(self.stored_files(), files_before)
        self.assertEqual(files_before[0].read_bytes(), b"hello")

    def test_cannot_delete_document_through_another_library(self):
        uploaded = self.upload(self.library_a, self.user_a)
        document_id = uploaded["id"]
        files_before = self.stored_files()

        # 即使两个知识库都属于 A，也不能混用知识库和文档 ID。
        with self.assertRaises(HTTPException) as caught:
            api.delete_document(
                knowledge_base_id=self.library_a2.id,
                document_id=document_id,
                db=self.db,
                current_user=self.user_a,
            )

        self.assertEqual(caught.exception.status_code, 404)
        self.assertIsNotNone(
            self.db.get(KnowledgeDocument, document_id)
        )
        self.assertEqual(self.stored_files(), files_before)
        self.assertEqual(files_before[0].read_bytes(), b"hello")

    def test_delete_commit_failure_restores_file(self):
        uploaded = self.upload(self.library_a, self.user_a)
        document_id = uploaded["id"]
        library_id = self.library_a.id

        row = self.db.get(KnowledgeDocument, document_id)
        original_path = (
            self.storage
            / str(library_id)
            / row.storage_name
        )

        # 模拟提交前报错，检查数据库回滚和文件恢复。
        with patch.object(
            self.db,
            "commit",
            side_effect=SQLAlchemyError("test commit failure"),
        ):
            with self.assertLogs(api.logger, level="ERROR"):
                with self.assertRaises(HTTPException) as caught:
                    api.delete_document(
                        knowledge_base_id=library_id,
                        document_id=document_id,
                        db=self.db,
                        current_user=self.user_a,
                    )

        self.assertEqual(caught.exception.status_code, 500)
        self.assertIsNotNone(
            self.db.get(KnowledgeDocument, document_id)
        )
        self.assertEqual(original_path.read_bytes(), b"hello")

        # 不应该遗留临时改名的 .deleting 文件。
        self.assertEqual(self.stored_files(), [original_path])