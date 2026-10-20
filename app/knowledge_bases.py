from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import KnowledgeBase, User


router = APIRouter(
    prefix="/api/knowledge-bases",
    tags=["知识库管理"],
)


class KnowledgeBaseCreate(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    name: str = Field(min_length=1, max_length=100)


class KnowledgeBasePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class KnowledgeBasePage(BaseModel):
    items: list[KnowledgeBasePublic]
    total: int
    page: int
    size: int


@router.post("", status_code=201, response_model=KnowledgeBasePublic)
def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge_base = KnowledgeBase(
        name=payload.name,
        user_id=current_user.id,
    )

    try:
        db.add(knowledge_base)
        db.commit()
        db.refresh(knowledge_base)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="创建知识库失败",
        ) from exc

    return knowledge_base


@router.get("", response_model=KnowledgeBasePage)
def list_knowledge_bases(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    condition = KnowledgeBase.user_id == current_user.id

    total = db.scalar(
        select(func.count())
        .select_from(KnowledgeBase)
        .where(condition)
    ) or 0

    items = db.scalars(
        select(KnowledgeBase)
        .where(condition)
        .order_by(KnowledgeBase.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()

    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
    }

def get_owned_knowledge_base(
    knowledge_base_id: int,
    db: Session,
    current_user: User,
) -> KnowledgeBase:
    knowledge_base = db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.user_id == current_user.id,
        )
    )

    if knowledge_base is None:
        raise HTTPException(
            status_code=404,
            detail="知识库不存在",
        )

    return knowledge_base


@router.get(
    "/{knowledge_base_id}",
    response_model=KnowledgeBasePublic,
)
def read_knowledge_base(
    knowledge_base_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_owned_knowledge_base(
        knowledge_base_id,
        db,
        current_user,
    )


@router.patch(
    "/{knowledge_base_id}",
    response_model=KnowledgeBasePublic,
)
def rename_knowledge_base(
    knowledge_base_id: int,
    payload: KnowledgeBaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge_base = get_owned_knowledge_base(
        knowledge_base_id,
        db,
        current_user,
    )

    knowledge_base.name = payload.name

    try:
        db.commit()
        db.refresh(knowledge_base)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="修改知识库失败",
        ) from exc

    return knowledge_base

@router.delete("/{knowledge_base_id}")
def delete_knowledge_base(
    knowledge_base_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge_base = get_owned_knowledge_base(
        knowledge_base_id,
        db,
        current_user,
    )

    try:
        db.delete(knowledge_base)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="删除知识库失败",
        ) from exc

    return {"message": "知识库已删除"}