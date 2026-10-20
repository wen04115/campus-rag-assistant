import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app import knowledge_chat as api


def decode_event(chunk):
    if isinstance(chunk, bytes):
        chunk = chunk.decode("utf-8")
    return json.loads(chunk)


async def read_events(response):
    text = ""

    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")
        text += chunk

    return [
        json.loads(line)
        for line in text.splitlines()
        if line.strip()
    ]


class KnowledgeStreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.prepared = {
            "knowledge_base_id": 1,
            "user_id": 10,
            "collection_name": f"kb_1_{'a' * 32}",
            "context": "测试资料",
            "sources": ["test.txt"],
            "citations": [
                {
                    "document_id": 20,
                    "source": "test.txt",
                    "page": 1,
                    "chunk_index": 1,
                    "excerpt": "测试资料",
                }
            ],
        }

        self.prepare = self.mock_attribute("prepare_chat")
        self.prepare.return_value = self.prepared

        self.check_index = self.mock_attribute("ensure_index_current")
        self.save_record = self.mock_attribute("save_chat_record")
        self.save_record.return_value = 100
        self.model_factory = self.mock_attribute("create_chat_model")
        self.prompt = self.mock_attribute("PROMPT")

        # 阻止流式阶段创建真实 MySQL 会话。
        self.session_factory = self.mock_attribute("Session")
        self.chain = self.prompt.__or__.return_value

        self.chain.stream.return_value = iter([
            SimpleNamespace(content="第一段"),
            SimpleNamespace(content=""),
            SimpleNamespace(content="第二段"),
        ])

    def mock_attribute(self, name):
        patcher = patch.object(api, name)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def make_response(self):
        return api.stream_with_knowledge_base(
            knowledge_base_id=1,
            payload=api.KnowledgeQuestion(question="测试问题"),
            db=object(),
            current_user=object(),
        )

    async def test_success_streams_metadata_tokens_and_done(self):
        response = self.make_response()

        self.assertEqual(
            response.media_type,
            "application/x-ndjson",
        )
        self.chain.stream.assert_not_called()

        # 先读取第一条事件，确认没有先等完整回答生成。
        first = decode_event(await anext(response.body_iterator))
        self.assertEqual(first["type"], "metadata")
        self.assertEqual(first["knowledge_base_id"], 1)
        self.chain.stream.assert_not_called()

        events = [first] + await read_events(response)

        self.assertEqual(
            [event["type"] for event in events],
            ["metadata", "token", "token", "done"],
        )
        self.assertEqual(events[1]["content"], "第一段")
        self.assertEqual(events[2]["content"], "第二段")
        self.assertEqual(
            events[-1]["answer"],
            "第一段第二段",
        )
        self.assertEqual(
            events[-1]["citations"],
            self.prepared["citations"],
        )
        self.assertEqual(self.check_index.call_count, 2)

        self.save_record.assert_called_once_with(
            self.session_factory.return_value.__enter__.return_value,
            self.prepared,
            "测试问题",
            "第一段第二段",
        )

    async def test_model_failure_emits_error_without_done(self):
        def broken_stream(_inputs):
            yield SimpleNamespace(content="部分回答")
            raise RuntimeError("test model failure")

        self.chain.stream.side_effect = broken_stream

        with self.assertLogs(api.logger, level="ERROR"):
            events = await read_events(self.make_response())

        self.assertEqual(
            [event["type"] for event in events],
            ["metadata", "token", "error"],
        )
        self.assertEqual(events[1]["content"], "部分回答")
        self.assertFalse(
            any(event["type"] == "done" for event in events)
        )
        self.save_record.assert_not_called()

    async def test_index_change_prevents_done_event(self):
        self.check_index.side_effect = [
            None,
            HTTPException(
                status_code=409,
                detail="回答期间知识库发生变化",
            ),
        ]

        events = await read_events(self.make_response())

        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("知识库发生变化", events[-1]["message"])
        self.assertFalse(
            any(event["type"] == "done" for event in events)
        )
        self.save_record.assert_not_called()

    async def test_empty_context_does_not_call_model(self):
        self.prepared.update({
            "context": "",
            "sources": [],
            "citations": [],
        })

        events = await read_events(self.make_response())

        self.assertEqual(
            [event["type"] for event in events],
            ["metadata", "token", "done"],
        )
        self.assertEqual(
            events[-1]["answer"],
            "知识库中没有找到相关信息。",
        )
        self.model_factory.assert_not_called()
        self.chain.stream.assert_not_called()

    async def test_permission_error_is_returned_before_stream(self):
        self.prepare.side_effect = HTTPException(
            status_code=404,
            detail="知识库不存在",
        )

        with self.assertRaises(HTTPException) as caught:
            self.make_response()

        self.assertEqual(caught.exception.status_code, 404)
        self.model_factory.assert_not_called()
        self.chain.stream.assert_not_called()
        self.session_factory.assert_not_called()

    async def test_history_failure_prevents_done_event(self):
        self.save_record.side_effect = HTTPException(
            status_code=503,
            detail="回答已生成，但历史保存失败",
        )

        events = await read_events(self.make_response())

        self.assertEqual(
            [event["type"] for event in events],
            ["metadata", "token", "token", "error"],
        )
        self.assertIn(
            "历史保存失败",
            events[-1]["message"],
        )
        self.save_record.assert_called_once()
