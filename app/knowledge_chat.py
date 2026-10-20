import json
import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_chroma import Chroma
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import engine, get_db
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


def prepare_chat(
    knowledge_base_id: int,
    question: str,
    db: Session,
    current_user: User,
) -> dict:
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
            question,
            k=4,
            filter={"knowledge_base_id": knowledge_base_id},
        )
    except Exception as exc:
        logger.exception("知识库检索失败")
        raise HTTPException(
            status_code=500,
            detail="知识库检索失败，请检查索引和后端日志",
        ) from exc

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

    context = "\n\n".join(
        (
            f"[来源：{document.metadata.get('source', '未知')}]\n"
            f"{document.page_content}"
        )
        for document in matched
    )

    return {
        "knowledge_base_id": knowledge_base_id,
        "user_id": user_id,
        "collection_name": collection_name,
        "context": context,
        "sources": list(dict.fromkeys(
            item["source"] for item in citations
        )),
        "citations": citations,
    }


def ensure_index_current(db: Session, prepared: dict):
    try:
        active_collection = db.scalar(
            select(KnowledgeBase.index_collection).where(
                KnowledgeBase.id == prepared["knowledge_base_id"],
                KnowledgeBase.user_id == prepared["user_id"],
            )
        )
    finally:
        db.rollback()

    if active_collection != prepared["collection_name"]:
        raise HTTPException(
            status_code=409,
            detail="回答期间知识库发生变化，请重新确认索引后提问",
        )


def create_chat_model():
    return ChatOpenAI(
        model=os.getenv("CHAT_MODEL", "deepseek-v4-flash"),
        temperature=0,
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        timeout=60,
        max_retries=1,
    )


def chat_result(prepared: dict, answer: str) -> dict:
    return {
        "knowledge_base_id": prepared["knowledge_base_id"],
        "answer": answer,
        "sources": prepared["sources"],
        "citations": prepared["citations"],
    }


@router.post("/{knowledge_base_id}/chat")
def chat_with_knowledge_base(
    knowledge_base_id: int,
    payload: KnowledgeQuestion,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prepared = prepare_chat(
        knowledge_base_id,
        payload.question,
        db,
        current_user,
    )

    if not prepared["context"]:
        answer = "知识库中没有找到相关信息。"
    else:
        try:
            model = create_chat_model()
            response = (PROMPT | model).invoke({
                "context": prepared["context"],
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

    ensure_index_current(db, prepared)
    return chat_result(prepared, answer)


def encode_event(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"


@router.post("/{knowledge_base_id}/chat/stream")
def stream_with_knowledge_base(
    knowledge_base_id: int,
    payload: KnowledgeQuestion,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 在响应开始前完成权限、索引和检索检查。
    prepared = prepare_chat(
        knowledge_base_id,
        payload.question,
        db,
        current_user,
    )

    try:
        model = create_chat_model() if prepared["context"] else None
    except Exception as exc:
        logger.exception("聊天模型初始化失败")
        raise HTTPException(
            status_code=502,
            detail="聊天模型初始化失败",
        ) from exc

    def generate():
        model_stream = None

        try:
            # 流式阶段使用独立短会话，不复用请求中的数据库会话。
            with Session(engine) as check_db:
                ensure_index_current(check_db, prepared)

            yield encode_event({
                "type": "metadata",
                "knowledge_base_id": prepared["knowledge_base_id"],
                "sources": prepared["sources"],
                "citations": prepared["citations"],
            })

            parts = []

            if prepared["context"]:
                model_stream = (PROMPT | model).stream({
                    "context": prepared["context"],
                    "question": payload.question,
                })

                for chunk in model_stream:
                    content = chunk.content

                    if not isinstance(content, str):
                        raise RuntimeError("模型返回了非文本片段")

                    if content:
                        parts.append(content)
                        yield encode_event({
                            "type": "token",
                            "content": content,
                        })
            else:
                content = "知识库中没有找到相关信息。"
                parts.append(content)
                yield encode_event({
                    "type": "token",
                    "content": content,
                })

            answer = "".join(parts)

            if not answer.strip():
                raise RuntimeError("模型没有返回有效回答")

            with Session(engine) as check_db:
                ensure_index_current(check_db, prepared)

            yield encode_event({
                "type": "done",
                **chat_result(prepared, answer),
            })

        except HTTPException as exc:
            yield encode_event({
                "type": "error",
                "message": exc.detail,
            })
        except Exception:
            logger.exception("知识库流式回答失败")
            yield encode_event({
                "type": "error",
                "message": "回答未完成，请稍后重试",
            })
        finally:
            if model_stream is not None:
                close = getattr(model_stream, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        logger.exception("关闭模型数据流失败")

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache"},
    )