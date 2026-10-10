from __future__ import annotations

import os
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter

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


def _load_documents() -> list[Document]:
    docs: list[Document] = []
    for path in KNOWLEDGE_DIR.glob("**/*"):
        if path.suffix.lower() not in {".md", ".txt"} or not path.is_file():
            continue
        docs.append(Document(page_content=path.read_text(encoding="utf-8"), metadata={"source": path.name}))
    return docs


def rebuild_index() -> dict:
    """Split local knowledge files and write their embeddings into Chroma."""
    source_docs = _load_documents()
    if not source_docs:
        return {"documents": 0, "chunks": 0}
    chunks = RecursiveCharacterTextSplitter(
        chunk_size=500, 
        chunk_overlap=80
    ).split_documents(source_docs)
    for index, chunk in enumerate(chunks[:3], start=1):
        print(f"\n--- 第 {index} 个文本片段 ---")
        print(f"来源文件：{chunk.metadata.get('source', '未知')}")
        print(f"文本长度：{len(chunk.page_content)} 个字符")
        print(chunk.page_content)
    # Do not delete the persistence directory. On Windows Chroma's HNSW index file
    # can be held open by this running FastAPI process. Clearing existing records
    # through Chroma avoids a WinError 32 file-lock conflict during a rebuild.
    store = _store()
    existing_ids = store.get(include=[]).get("ids", [])
    if existing_ids:
        store.delete(ids=existing_ids)
    store.add_documents(chunks)
    return {"documents": len(source_docs), "chunks": len(chunks)}


def ask(question: str) -> dict:
    if not VECTOR_DIR.exists():
        raise RuntimeError("尚未建立索引，请先调用 /api/index")
    matched = _store().similarity_search(question, k=4)
    context = "\n\n".join(f"[来源：{doc.metadata.get('source', '未知')}]\n{doc.page_content}" for doc in matched)
    model = ChatOpenAI(
        model=os.getenv("CHAT_MODEL", "deepseek-v4-flash"),
        temperature=0,
        base_url=os.getenv("OPENAI_BASE_URL") or None,
    )
    answer = (PROMPT | model).invoke({"context": context, "question": question}).content
    return {"answer": answer, "sources": list(dict.fromkeys(doc.metadata.get("source", "未知") for doc in matched))}
