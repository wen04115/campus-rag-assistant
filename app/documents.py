import logging
import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.document_loader import load_document_bytes
from app.knowledge_bases import get_owned_knowledge_base
from app.models import KnowledgeDocument, User


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/knowledge-bases",
    tags=["知识库文档"],
)

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_DIR = ROOT / "data" / "documents"
MAX_FILE_SIZE = 10 * 1024 * 1024


class DocumentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_name: str
    size: int
    knowledge_base_id: int


class DocumentPage(BaseModel):
    items: list[DocumentPublic]
    total: int
    page: int
    size: int


@router.post(
    "/{knowledge_base_id}/documents",
    status_code=201,
    response_model=DocumentPublic,
)
def upload_document(
    knowledge_base_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 先确认知识库属于当前用户。
    knowledge_base = get_owned_knowledge_base(
        knowledge_base_id,
        db,
        current_user,
    )

    filename = (
        (file.filename or "")
        .replace("\\", "/")
        .rsplit("/", 1)[-1]
        .strip()
    )

    if not filename or "\x00" in filename or len(filename) > 255:
        raise HTTPException(
            status_code=400,
            detail="文件名不能为空，且不能超过 255 个字符",
        )

    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".md", ".pdf"}:
        raise HTTPException(
            status_code=400,
            detail="只支持 .txt、.md 和文字版 PDF 文件",
        )

    # 普通 def 接口中使用同步文件读取。
    content = file.file.read(MAX_FILE_SIZE + 1)

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="文件不能超过 10 MiB",
        )

    if not content:
        raise HTTPException(
            status_code=400,
            detail="不能上传空文件",
        )

    # 编码错误、损坏 PDF、扫描版 PDF 等不会保存。
    try:
        parsed_documents = load_document_bytes(content, filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if not any(item.page_content.strip() for item in parsed_documents):
        raise HTTPException(
            status_code=400,
            detail="文件中没有可用文字",
        )

    # 保存路径只使用后端生成的名称，不使用用户提供的路径。
    storage_name = f"{uuid4().hex}{suffix}"
    directory = DOCUMENT_DIR / str(knowledge_base.id)
    target = directory / storage_name
    created = False

    try:
        directory.mkdir(parents=True, exist_ok=True)

        with target.open("xb") as output:
            created = True
            output.write(content)

        document = KnowledgeDocument(
            original_name=filename,
            storage_name=storage_name,
            size=len(content),
            knowledge_base_id=knowledge_base.id,
        )
        db.add(document)
        db.flush()

        # 提交前取出响应字段，避免提交后刷新失败误删文件。
        result = {
            "id": document.id,
            "original_name": document.original_name,
            "size": document.size,
            "knowledge_base_id": document.knowledge_base_id,
        }

        db.commit()
    except (OSError, SQLAlchemyError) as exc:
        db.rollback()

        if created:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                logger.exception("上传失败后的文件清理失败")

        logger.exception("文档上传失败")
        raise HTTPException(
            status_code=500,
            detail="文档上传失败，请稍后重试",
        ) from exc

    return result

@router.get(
    "/{knowledge_base_id}/documents",
    response_model=DocumentPage,
)
def list_documents(
    knowledge_base_id: int,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge_base = get_owned_knowledge_base(
        knowledge_base_id,
        db,
        current_user,
    )

    condition = (
        KnowledgeDocument.knowledge_base_id == knowledge_base.id
    )

    total = db.scalar(
        select(func.count())
        .select_from(KnowledgeDocument)
        .where(condition)
    ) or 0

    items = db.scalars(
        select(KnowledgeDocument)
        .where(condition)
        .order_by(KnowledgeDocument.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()

    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
    }

@router.delete(
    "/{knowledge_base_id}/documents/{document_id}",
)
def delete_document(
    knowledge_base_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge_base = get_owned_knowledge_base(
        knowledge_base_id,
        db,
        current_user,
    )

    # 同时限制知识库和文档 ID，不能跨知识库删除。
    # MySQL 中锁定记录，避免同一文档被并发删除。
    document = db.scalar(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.knowledge_base_id == knowledge_base.id,
        )
        .with_for_update()
    )

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="文档不存在",
        )

    # 只允许后端生成的存储文件名。
    if not re.fullmatch(
        r"[0-9a-f]{32}\.(txt|md|pdf)",
        document.storage_name,
    ):
        raise HTTPException(
            status_code=500,
            detail="文档存储信息异常",
        )

    root = DOCUMENT_DIR.resolve()
    directory = (root / str(knowledge_base.id)).resolve()
    target = directory / document.storage_name

    # 防止目录或文件被替换成指向其他位置的链接。
    if directory.parent != root or target.is_symlink():
        raise HTTPException(
            status_code=500,
            detail="文档存储路径异常",
        )

    staged = directory / f".deleting-{uuid4().hex}"
    moved = False

    try:
        # 先临时改名，数据库操作失败时可以尝试恢复。
        # 原文件已经丢失时，仍允许清理数据库中的记录。
        if target.exists():
            target.rename(staged)
            moved = True

        db.delete(document)
        db.commit()
    except (OSError, SQLAlchemyError) as exc:
        db.rollback()

        if moved:
            try:
                staged.rename(target)
            except OSError:
                logger.exception("文档删除失败后的文件恢复失败")

        logger.exception("文档删除失败")
        raise HTTPException(
            status_code=500,
            detail="文档删除失败，请稍后重试",
        ) from exc

    cleanup_pending = False

    if moved:
        try:
            staged.unlink()
        except OSError:
            # 数据库删除已提交，不能假装回滚成功。
            cleanup_pending = True
            logger.exception("文档记录已删除，但磁盘文件清理失败")

    return {
        "message": "文档已删除",
        "cleanup_pending": cleanup_pending,
    }