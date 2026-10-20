import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.kb_index import IndexDocument, build_knowledge_base_index
from app.knowledge_bases import get_owned_knowledge_base
from app.models import KnowledgeBase, KnowledgeDocument, User


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/knowledge-bases",
    tags=["知识库索引"],
)


def document_snapshot(
    db: Session,
    knowledge_base_id: int,
) -> list[IndexDocument]:
    rows = db.execute(
        select(
            KnowledgeDocument.id,
            KnowledgeDocument.knowledge_base_id,
            KnowledgeDocument.original_name,
            KnowledgeDocument.storage_name,
            KnowledgeDocument.size,
        )
        .where(
            KnowledgeDocument.knowledge_base_id == knowledge_base_id
        )
        .order_by(KnowledgeDocument.id)
    ).all()

    return [
        IndexDocument(
            id=row.id,
            knowledge_base_id=row.knowledge_base_id,
            original_name=row.original_name,
            storage_name=row.storage_name,
            size=row.size,
        )
        for row in rows
    ]


@router.post("/{knowledge_base_id}/index")
def create_knowledge_base_index(
    knowledge_base_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    get_owned_knowledge_base(
        knowledge_base_id,
        db,
        current_user,
    )

    user_id = current_user.id
    documents = document_snapshot(db, knowledge_base_id)

    # 结束只读事务，不在整个向量计算期间持有事务。
    db.rollback()

    if not documents:
        raise HTTPException(
            status_code=400,
            detail="知识库中没有文档，请先上传",
        )

    try:
        result = build_knowledge_base_index(
            knowledge_base_id,
            documents,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except OSError as exc:
        logger.exception("建立索引时读取文档失败")
        raise HTTPException(
            status_code=409,
            detail="文档读取失败，请检查文件是否存在后重试",
        ) from exc
    except Exception as exc:
        logger.exception("知识库索引构建失败")
        raise HTTPException(
            status_code=500,
            detail="索引构建失败，请查看后端日志",
        ) from exc

    try:
        # 新事务中再次检查所有权，并锁定索引指向所在记录。
        knowledge_base = db.scalar(
            select(KnowledgeBase)
            .where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.user_id == user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        if knowledge_base is None:
            raise HTTPException(
                status_code=404,
                detail="知识库不存在",
            )

        current_documents = document_snapshot(
            db,
            knowledge_base_id,
        )

        if current_documents != documents:
            raise HTTPException(
                status_code=409,
                detail="构建期间文档发生变化，请重新建立索引",
            )

        knowledge_base.index_collection = result["collection_name"]
        db.commit()
    except HTTPException:
        db.rollback()
        logger.warning(
            "新集合未启用，待后续清理：%s",
            result["collection_name"],
        )
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception(
            "索引切换失败，集合待核查：%s",
            result["collection_name"],
        )
        raise HTTPException(
            status_code=500,
            detail="索引切换失败，请查看后端日志",
        ) from exc

    return {
        "message": "知识库索引建立成功",
        "knowledge_base_id": knowledge_base_id,
        "documents": result["documents"],
        "chunks": result["chunks"],
    }