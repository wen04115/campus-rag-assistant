"""Run only against the disposable GitHub Actions MySQL service, never local .env."""
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    if (
        os.getenv("GITHUB_ACTIONS") != "true"
        or os.getenv("MYSQL_USER") != "ci_runner"
        or os.getenv("MYSQL_DATABASE") != "rag_platform"
    ):
        raise RuntimeError("此检查仅允许在 GitHub Actions 的 ci_runner 临时数据库执行")

    from app.database import engine
    from app.models import KnowledgeBase, KnowledgeChatRecord, KnowledgeDocument, User

    with engine.connect() as db:
        transaction = db.begin()
        try:
            user_id = db.execute(insert(User).values(
                username="migration_fixture", hashed_password="not-a-login-password",
            )).inserted_primary_key[0]
            kb_id = db.execute(insert(KnowledgeBase).values(
                user_id=user_id, name="迁移检查",
            )).inserted_primary_key[0]
            record_id = db.execute(insert(KnowledgeChatRecord).values(
                knowledge_base_id=kb_id, question="测试", answer="回答",
                sources=["中文.pdf"], citations=[{"page": 1}],
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )).inserted_primary_key[0]
            sources = db.scalar(select(KnowledgeChatRecord.sources).where(KnowledgeChatRecord.id == record_id))
            assert sources == ["中文.pdf"], "JSON/UTF-8 round-trip failed"
            db.execute(delete(KnowledgeBase).where(KnowledgeBase.id == kb_id))
            assert db.scalar(select(KnowledgeChatRecord.id).where(KnowledgeChatRecord.id == record_id)) is None

            kb_id = db.execute(insert(KnowledgeBase).values(user_id=user_id, name="有文档")).inserted_primary_key[0]
            db.execute(insert(KnowledgeDocument).values(
                knowledge_base_id=kb_id, original_name="test.txt", storage_name="ci-only.txt", size=4,
            ))
            try:
                with db.begin_nested():
                    db.execute(delete(KnowledgeBase).where(KnowledgeBase.id == kb_id))
            except IntegrityError:
                pass
            else:
                raise AssertionError("文档外键应禁止直接删除非空知识库")
        finally:
            transaction.rollback()
    print("MySQL: JSON、历史级联删除、文档外键保护检查通过（测试数据已回滚）")


if __name__ == "__main__":
    main()
