import unittest
from unittest.mock import patch
from types import SimpleNamespace
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

    def test_stream_sends_chunks_and_metadata(self):
        chain = self.prompt.__or__.return_value
        chain.stream.return_value = iter([
            SimpleNamespace(content="第一段。"),
            SimpleNamespace(content=""),
            SimpleNamespace(content="第二段。"),
        ])

        events = rag.ask_stream("测试问题", source="测试.pdf")

        # 先收到来源和页码，此时还没有开始调用模型流。
        metadata = next(events)
        self.assertEqual(metadata["type"], "metadata")
        self.assertEqual(metadata["sources"], ["测试.pdf"])
        self.assertEqual(metadata["citations"][0]["page"], 1)
        chain.stream.assert_not_called()

        # 两段文字分别返回，空内容跳过。
        self.assertEqual(
            next(events),
            {"type": "token", "content": "第一段。"},
        )
        self.assertEqual(
            next(events),
            {"type": "token", "content": "第二段。"},
        )

        finished = next(events)
        self.assertEqual(finished["type"], "done")
        self.assertEqual(finished["answer"], "第一段。第二段。")
        self.assertEqual(finished["citations"], metadata["citations"])

        with self.assertRaises(StopIteration):
            next(events)

        self.store.similarity_search.assert_called_once_with(
            "测试问题",
            k=4,
            filter={"source": "测试.pdf"},
        )

    def test_stream_failure_has_no_done_event(self):
        def broken_stream():
            yield SimpleNamespace(content="已生成的部分。")
            raise RuntimeError("模拟模型中断")

        chain = self.prompt.__or__.return_value
        chain.stream.return_value = broken_stream()

        received = []

        with self.assertRaisesRegex(RuntimeError, "模拟模型中断"):
            for event in rag.ask_stream("测试问题", source="测试.pdf"):
                received.append(event)

        self.assertEqual(
            [event["type"] for event in received],
            ["metadata", "token"],
        )
        self.assertNotIn(
            "done",
            [event["type"] for event in received],
        )


if __name__ == "__main__":
    unittest.main()