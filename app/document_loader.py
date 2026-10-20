from io import BytesIO
from pathlib import Path

from langchain_core.documents import Document
from pypdf import PdfReader
from pypdf.errors import PyPdfError


def load_document_bytes(content: bytes, filename: str) -> list[Document]:
    suffix = Path(filename).suffix.lower()

    # 文本文件仍然要求 UTF-8 编码
    if suffix in {".txt", ".md"}:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("文件必须是 UTF-8 编码") from exc

        return [
            Document(
                page_content=text,
                metadata={"source": filename},
            )
        ]

    if suffix != ".pdf":
        raise ValueError("只支持 .txt、.md 和文字版 PDF 文件")

    # PDF 按页提取文字，保留从 1 开始的物理页码
    documents = []

    try:
        reader = PdfReader(BytesIO(content))

        if reader.is_encrypted:
            raise ValueError("暂不支持加密 PDF，请先解密后上传")

        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()

            if text:
                documents.append(
                    Document(
                        page_content=text,
                        metadata={
                            "source": filename,
                            "page": page_number,
                        },
                    )
                )
    except PyPdfError as exc:
        raise ValueError("PDF 解析失败，请检查文件是否损坏") from exc

    if not documents:
        raise ValueError(
            "PDF 中没有可提取的文字，暂不支持纯扫描件"
        )

    return documents