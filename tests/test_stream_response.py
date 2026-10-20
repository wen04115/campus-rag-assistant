import json
import unittest
from unittest.mock import patch

# 导入接口时，模拟数据库连接，避免初始化真实历史库。
with patch("sqlite3.connect"):
    from app import main


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


class StreamResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_saves_complete_answer(self):
        finished = {
            "type": "done",
            "answer": "完整回答",
            "sources": ["测试.pdf"],
            "citations": [],
        }

        fake_events = iter([
            {
                "type": "metadata",
                "sources": ["测试.pdf"],
                "citations": [],
            },
            {"type": "token", "content": "完整回答"},
            finished,
        ])

        with (
            patch.object(main, "ask_stream", return_value=fake_events) as ask,
            patch.object(main, "save_chat_history") as save,
        ):
            response = main.chat_stream(
                main.Question(question="测试问题", source="测试.pdf")
            )

            # 尚未消费数据流，不应该提前保存历史。
            save.assert_not_called()

            events = await read_events(response)

            self.assertEqual(
                response.media_type,
                "application/x-ndjson",
            )
            self.assertEqual(
                [event["type"] for event in events],
                ["metadata", "token", "done"],
            )
            self.assertEqual(events[-1], finished)

            ask.assert_called_once_with(
                "测试问题",
                source="测试.pdf",
            )
            save.assert_called_once_with("测试问题", finished)

    async def test_failure_returns_error_without_saving(self):
        def broken_events():
            yield {"type": "token", "content": "半截回答"}
            raise RuntimeError("模拟生成中断")

        with (
            patch.object(main, "ask_stream", return_value=broken_events()),
            patch.object(main, "save_chat_history") as save,
        ):
            response = main.chat_stream(
                main.Question(question="测试问题")
            )
            events = await read_events(response)

            self.assertEqual(
                [event["type"] for event in events],
                ["token", "error"],
            )
            self.assertIn("失败", events[-1]["message"])
            save.assert_not_called()