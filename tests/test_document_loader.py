import unittest
from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from app.document_loader import load_document_bytes


# 在内存中生成测试 PDF，不保存文件
def make_pdf(with_text=True, encrypted=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)

    if with_text:
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({
                NameObject("/F1"): writer._add_object(font),
            }),
        })

        stream = DecodedStreamObject()
        stream.set_data(
            b"BT /F1 12 Tf 20 100 Td (PDF test content) Tj ET"
        )
        page[NameObject("/Contents")] = writer._add_object(stream)

    if encrypted:
        writer.encrypt("test-password")

    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class DocumentLoaderTests(unittest.TestCase):
    # 合法 PDF 能提取文字，并保留来源和页码
    def test_read_text_pdf(self):
        documents = load_document_bytes(make_pdf(), "sample.pdf")

        self.assertEqual(len(documents), 1)
        self.assertIn("PDF test content", documents[0].page_content)
        self.assertEqual(documents[0].metadata["source"], "sample.pdf")
        self.assertEqual(documents[0].metadata["page"], 1)

    # 损坏的 PDF 应被拒绝
    def test_reject_broken_pdf(self):
        with self.assertRaisesRegex(ValueError, "PDF 解析失败"):
            load_document_bytes(b"not a real pdf", "broken.pdf")

    # 没有可提取文字的 PDF 应被拒绝
    def test_reject_empty_pdf(self):
        with self.assertRaisesRegex(ValueError, "没有可提取的文字"):
            load_document_bytes(
                make_pdf(with_text=False),
                "empty.pdf",
            )

    # 加密 PDF 应被拒绝
    def test_reject_encrypted_pdf(self):
        with self.assertRaisesRegex(ValueError, "暂不支持加密 PDF"):
            load_document_bytes(
                make_pdf(encrypted=True),
                "encrypted.pdf",
            )