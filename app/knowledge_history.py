import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.knowledge_bases import get_owned_knowledge_base
from app.models import KnowledgeBase, KnowledgeChatRecord, User


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge-bases", tags=["知识库历史"])


class HistoryRecordPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    knowledge_base_id: int
    question: str
    answer: str
    sources: list[str]
    citations: list[dict]
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


class HistoryPage(BaseModel):
    items: list[HistoryRecordPublic]
    total: int
    page: int
    size: int


@router.get("/{knowledge_base_id}/history", response_model=HistoryPage)
def list_chat_history(
    knowledge_base_id: int,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    get_owned_knowledge_base(knowledge_base_id, db, current_user)
    # 查询本身也约束所有者，不能仅依赖前端传入的知识库 ID。
    condition = (
        KnowledgeChatRecord.knowledge_base_id == knowledge_base_id,
        KnowledgeBase.user_id == current_user.id,
    )
    total = db.scalar(
        select(func.count())
        .select_from(KnowledgeChatRecord)
        .join(KnowledgeBase)
        .where(*condition)
    ) or 0
    items = db.scalars(
        select(KnowledgeChatRecord)
        .join(KnowledgeBase)
        .where(*condition)
        .order_by(KnowledgeChatRecord.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return {"items": items, "total": total, "page": page, "size": size}


def save_chat_record(
    db: Session,
    prepared: dict,
    question: str,
    answer: str,
) -> int:
    """使用无其他待提交修改的短会话，保存一条完整回答。"""
    if (
        not isinstance(question, str)
        or not question.strip()
        or len(question) > 500
    ):
        raise ValueError("问题需要为1～500个字符")

    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("不能保存空回答")

    try:
        # 检查归属并锁住知识库行，直到本次历史写入提交。
        # 只查询列，避免复用会话中缓存的旧模型属性。
        library = db.execute(
            select(
                KnowledgeBase.id,
                KnowledgeBase.index_collection,
            )
            .where(
                KnowledgeBase.id == prepared["knowledge_base_id"],
                KnowledgeBase.user_id == prepared["user_id"],
            )
            .with_for_update()
        ).one_or_none()

        if library is None:
            raise HTTPException(
                status_code=404,
                detail="知识库不存在",
            )

        if (
            not library.index_collection
            or library.index_collection != prepared["collection_name"]
        ):
            raise HTTPException(
                status_code=409,
                detail="回答期间知识库发生变化，未保存本次历史",
            )

        record = KnowledgeChatRecord(
            knowledge_base_id=library.id,
            question=question,
            answer=answer,
            sources=prepared["sources"],
            citations=prepared["citations"],
        )

        db.add(record)
        db.flush()

        record_id = record.id
        db.commit()
        return record_id

    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("保存知识库问答历史失败")
        raise HTTPException(
            status_code=503,
            detail="回答已生成，但历史保存失败，请刷新历史列表确认",
        ) from exc
