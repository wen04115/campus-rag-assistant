import logging
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.document_loader import load_document_bytes
from app.rag import VECTOR_DIR, _embeddings


logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_DIR = ROOT / "data" / "documents"
MAX_FILE_SIZE = 10 * 1024 * 1024


@dataclass(frozen=True)
class IndexDocument:
    id: int
    knowledge_base_id: int
    original_name: str
    storage_name: str
    size: int


def build_knowledge_base_index(
    knowledge_base_id: int,
    documents: list[IndexDocument],
) -> dict:
    # 此函数只构建索引，调用方必须先检查知识库所有权。
    if knowledge_base_id <= 0:
        raise ValueError("知识库 ID 无效")

    if not documents:
        raise ValueError("知识库中没有文档，请先上传")

    root = DOCUMENT_DIR.resolve()
    directory = (root / str(knowledge_base_id)).resolve()

    if directory.parent != root:
        raise ValueError("知识库文档目录异常")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=80,
    )
    chunks = []
    chunk_ids = []

    # 只读取传入的数据库文档清单，不扫描共享目录。
    for document in documents:
        if document.knowledge_base_id != knowledge_base_id:
            raise ValueError("文档不属于当前知识库")

        if not re.fullmatch(
            r"[0-9a-f]{32}\.(txt|md|pdf)",
            document.storage_name,
        ):
            raise ValueError("文档存储名称异常")

        path = directory / document.storage_name

        if path.is_symlink():
            raise ValueError("文档存储路径异常")

        with path.open("rb") as source:
            content = source.read(MAX_FILE_SIZE + 1)

        if len(content) > MAX_FILE_SIZE:
            raise ValueError("文件不能超过 10 MiB")

        if len(content) != document.size:
            raise ValueError("文档大小发生变化，请检查存储文件")

        pages = load_document_bytes(
            content,
            document.original_name,
        )
        document_chunks = splitter.split_documents(pages)
        document_chunks = [
            chunk
            for chunk in document_chunks
            if chunk.page_content.strip()
        ]

        if not document_chunks:
            raise ValueError("文档没有可建立索引的文字")

        for number, chunk in enumerate(document_chunks, start=1):
            # 保留 PDF 页码，并增加稳定的文档标识。
            chunk.metadata.update({
                "source": document.original_name,
                "knowledge_base_id": knowledge_base_id,
                "document_id": document.id,
                "chunk_index": number,
            })
            chunks.append(chunk)
            chunk_ids.append(f"{document.id}_{number}")

    # 每次构建都使用新名称，不清空旧集合。
    collection_name = (
        f"kb_{knowledge_base_id}_{uuid4().hex}"
    )

    store = Chroma(
        collection_name=collection_name,
        embedding_function=_embeddings(),
        persist_directory=str(VECTOR_DIR),
    )

    try:
        # 分批写入，避免一次提交过多片段。
        for start in range(0, len(chunks), 64):
            store.add_documents(
                documents=chunks[start:start + 64],
                ids=chunk_ids[start:start + 64],
            )
    except Exception:
        # 只尝试清理本次失败的新集合，不碰旧索引。
        try:
            store.delete_collection()
        except Exception:
            logger.exception("构建失败后的新索引清理失败")
        raise

    return {
        "collection_name": collection_name,
        "documents": len(documents),
        "chunks": len(chunks),
    }