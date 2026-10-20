import unittest
from unittest.mock import patch

from langchain_core.documents import Document

from app import rag


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        # 所有替换都会在每个测试结束后自动恢复。
        self.vector_dir = self.start_patch("VECTOR_DIR")
        self.vector_dir.exists.return_value = True

        self.store = self.start_patch("_store").return_value
        self.model_class = self.start_patch("ChatOpenAI")
        self.prompt = self.start_patch("PROMPT")

        chain = self.prompt.__or__.return_value
        chain.invoke.return_value.content = "模拟回答"

        self.store.similarity_search.return_value = [
            Document(
                page_content="OCR 用于从图片中提取文字。",
                metadata={
                    "source": "测试.pdf",
                    "page": 1,
                    "chunk_index": 1,
                },
            )
        ]

    def start_patch(self, name):
        patcher = patch.object(rag, name)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def test_selected_source_passes_filter(self):
        result = rag.ask("OCR是什么？", source="测试.pdf")

        self.store.similarity_search.assert_called_once_with(
            "OCR是什么？",
            k=4,
            filter={"source": "测试.pdf"},
        )
        self.assertEqual(result["sources"], ["测试.pdf"])
        self.assertEqual(result["citations"][0]["page"], 1)

    def test_default_search_has_no_filter(self):
        rag.ask("OCR是什么？")

        self.store.similarity_search.assert_called_once_with(
            "OCR是什么？",
            k=4,
            filter=None,
        )

    def test_empty_results_do_not_call_model(self):
        self.store.similarity_search.return_value = []

        with self.assertRaisesRegex(RuntimeError, "没有可检索的片段"):
            rag.ask("OCR是什么？", source="未索引.pdf")

        self.model_class.assert_not_called()
        self.prompt.__or__.assert_not_called()


if __name__ == "__main__":
    unittest.main()