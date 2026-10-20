import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException
from langchain_chroma import Chroma
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.knowledge_bases import get_owned_knowledge_base
from app.knowledge_index import document_snapshot
from app.models import KnowledgeBase, User
from app.rag import PROMPT, VECTOR_DIR, _embeddings


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/knowledge-bases",
    tags=["知识库问答"],
)


class KnowledgeQuestion(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    question: str = Field(min_length=1, max_length=500)


@router.post("/{knowledge_base_id}/chat")
def chat_with_knowledge_base(
    knowledge_base_id: int,
    payload: KnowledgeQuestion,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 必须先检查所有权，再读取索引或调用模型。
    knowledge_base = get_owned_knowledge_base(
        knowledge_base_id,
        db,
        current_user,
    )

    collection_name = knowledge_base.index_collection

    if not collection_name:
        raise HTTPException(
            status_code=409,
            detail="知识库尚未建立索引，或文档已变化，请重新建立索引",
        )

    if not re.fullmatch(
        rf"kb_{knowledge_base_id}_[0-9a-f]{{32}}",
        collection_name,
    ):
        raise HTTPException(
            status_code=500,
            detail="知识库索引配置异常",
        )

    user_id = current_user.id
    documents = document_snapshot(db, knowledge_base_id)
    allowed_document_ids = {item.id for item in documents}

    # 不在模型请求期间持有数据库事务。
    db.rollback()

    if not allowed_document_ids:
        raise HTTPException(
            status_code=409,
            detail="知识库没有可用文档，请重新建立索引",
        )

    try:
        store = Chroma(
            collection_name=collection_name,
            embedding_function=_embeddings(),
            persist_directory=str(VECTOR_DIR),
            create_collection_if_not_exists=False,
        )

        matched = store.similarity_search(
            payload.question,
            k=4,
            filter={"knowledge_base_id": knowledge_base_id},
        )
    except Exception as exc:
        logger.exception("知识库检索失败")
        raise HTTPException(
            status_code=500,
            detail="知识库检索失败，请检查索引和后端日志",
        ) from exc

    # 再检查片段归属，异常时拒绝送入大模型。
    for document in matched:
        metadata = document.metadata

        if (
            metadata.get("knowledge_base_id") != knowledge_base_id
            or metadata.get("document_id") not in allowed_document_ids
        ):
            raise HTTPException(
                status_code=409,
                detail="索引内容与文档清单不一致，请重新建立索引",
            )

    citations = [
        {
            "document_id": document.metadata["document_id"],
            "source": document.metadata.get("source", "未知"),
            "page": document.metadata.get("page"),
            "chunk_index": document.metadata.get("chunk_index"),
            "excerpt": document.page_content[:200],
        }
        for document in matched
    ]

    if not matched:
        answer = "知识库中没有找到相关信息。"
    else:
        context = "\n\n".join(
            (
                f"[来源：{document.metadata.get('source', '未知')}]\n"
                f"{document.page_content}"
            )
            for document in matched
        )

        try:
            model = ChatOpenAI(
                model=os.getenv("CHAT_MODEL", "deepseek-v4-flash"),
                temperature=0,
                base_url=os.getenv("OPENAI_BASE_URL") or None,
                timeout=60,
                max_retries=1,
            )

            response = (PROMPT | model).invoke({
                "context": context,
                "question": payload.question,
            })

            if not isinstance(response.content, str):
                raise RuntimeError("模型返回了非文本内容")

            answer = response.content
        except Exception as exc:
            logger.exception("知识库回答生成失败")
            raise HTTPException(
                status_code=502,
                detail="回答生成失败，请稍后重试",
            ) from exc

    # 生成期间若文档变化或索引被切换，不返回旧索引的回答。
    try:
        active_collection = db.scalar(
            select(KnowledgeBase.index_collection).where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.user_id == user_id,
            )
        )
    finally:
        db.rollback()

    if active_collection != collection_name:
        raise HTTPException(
            status_code=409,
            detail="回答期间知识库发生变化，请重新确认索引后提问",
        )

    return {
        "knowledge_base_id": knowledge_base_id,
        "answer": answer,
        "sources": list(dict.fromkeys(
            item["source"] for item in citations
        )),
        "citations": citations,
    }