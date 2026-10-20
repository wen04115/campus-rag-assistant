from __future__ import annotations

import os
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.document_loader import load_document_bytes

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"
VECTOR_DIR = ROOT / "data" / "vector_store"

PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是企业知识库助手。仅依据给定的上下文回答。若上下文没有答案，请明确说‘知识库中没有找到相关信息’，不要编造。回答使用中文，并尽量简洁。\n\n上下文：\n{context}"),
    ("human", "{question}"),
])


def _embeddings() -> HuggingFaceEmbeddings:
    """Use a local Chinese embedding model; DeepSeek's API is only used for chat."""
    return HuggingFaceEmbeddings(
        model_name=os.getenv("LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def _store() -> Chroma:
    return Chroma(collection_name="intern_rag", embedding_function=_embeddings(), persist_directory=str(VECTOR_DIR))


def delete_source_from_index(filename: str) -> bool:
    """Delete one source file's chunks without rebuilding every document."""
    if not VECTOR_DIR.exists():
        return False

    store = Chroma(
        collection_name="intern_rag",
        persist_directory=str(VECTOR_DIR),
    )
    store.delete(where={"source": filename})
    return True


def _load_documents() -> list[Document]:
    docs: list[Document] = []

    for path in KNOWLEDGE_DIR.glob("**/*"):
        if not path.is_file():
            continue

        if path.suffix.lower() not in {".md", ".txt", ".pdf"}:
            continue

        # 统一读取；PDF 每个有文字的页面生成一个 Document
        documents = load_document_bytes(
            path.read_bytes(),
            path.name,
        )
        docs.extend(documents)

    return docs


def rebuild_index() -> dict:
    """Split local knowledge files and write their embeddings into Chroma."""
    source_docs = _load_documents()
    # Do not delete the persistence directory. On Windows Chroma's HNSW index file
    # can be held open by this running FastAPI process. Clearing existing records
    # through Chroma avoids a WinError 32 file-lock conflict during a rebuild.
    store = _store()
    existing_ids = store.get(include=[]).get("ids", [])
    if existing_ids:
        store.delete(ids=existing_ids)

    if not source_docs:
        return {"documents": 0, "chunks": 0}

    chunks = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=80,
    ).split_documents(source_docs)

    chunk_counts: dict[str, int] = {}

    for chunk in chunks:
        source = chunk.metadata.get("source", "未知")
        chunk_counts[source] = chunk_counts.get(source, 0) + 1
        chunk.metadata["chunk_index"] = chunk_counts[source]

    store.add_documents(chunks)
    document_count = len({
        doc.metadata["source"] for doc in source_docs
    })

    return {
        "documents": document_count,
        "chunks": len(chunks),
    }


def ask(question: str, source: str | None = None) -> dict:
    if not VECTOR_DIR.exists():
        raise RuntimeError("尚未建立索引，请先调用 /api/index")

    search_filter = {"source": source} if source is not None else None

    matched = _store().similarity_search(
        question,
        k=4,
        filter=search_filter,
    )

    if not matched:
        raise RuntimeError("所选范围内没有可检索的片段，请确认文件已建立索引")
    context = "\n\n".join(f"[来源：{doc.metadata.get('source', '未知')}]\n{doc.page_content}" for doc in matched)
    model = ChatOpenAI(
        model=os.getenv("CHAT_MODEL", "deepseek-v4-flash"),
        temperature=0,
        base_url=os.getenv("OPENAI_BASE_URL") or None,
    )
    answer = (PROMPT | model).invoke({"context": context, "question": question}).content
    citations = [
        {
            "source": doc.metadata.get("source", "未知"),
            "page": doc.metadata.get("page"),
            "chunk_index": doc.metadata.get("chunk_index", "未知"),
            "excerpt": doc.page_content[:100],
        }
        for doc in matched
    ]

    sources = list(
        dict.fromkeys(
            citation["source"] for citation in citations
        )
    )

    return {
        "answer": answer,
        "sources": sources,
        "citations": citations,
    }

def ask_stream(question: str, source: str | None = None):
    if not VECTOR_DIR.exists():
        raise RuntimeError("尚未建立索引，请先调用 /api/index")

    search_filter = {"source": source} if source is not None else None

    matched = _store().similarity_search(
        question,
        k=4,
        filter=search_filter,
    )

    if not matched:
        raise RuntimeError("所选范围内没有可检索的片段，请确认文件已建立索引")

    context = "\n\n".join(
        f"[来源：{doc.metadata.get('source', '未知')}]\n{doc.page_content}"
        for doc in matched
    )

    model = ChatOpenAI(
        model=os.getenv("CHAT_MODEL", "deepseek-v4-flash"),
        temperature=0,
        base_url=os.getenv("OPENAI_BASE_URL") or None,
    )

    sources = list(
        dict.fromkeys(
            doc.metadata.get("source", "未知")
            for doc in matched
        )
    )

    def generate():
        for chunk in (PROMPT | model).stream(
            {"context": context, "question": question}
        ):
            if chunk.content:
                yield chunk.content

        yield "\n\n来源：" + "、".join(sources)

    return generate()
