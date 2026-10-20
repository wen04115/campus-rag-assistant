import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient

# 避免导入 main 时初始化真实历史数据库。
with patch("sqlite3.connect"):
    from app import main


class LegacyDisabledTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)

        # 即使停用保护被误删，测试也不能操作真实共享文件、
        # 历史数据库、向量索引或模型。
        self.guards = [
            stack.enter_context(
                patch.object(main, "KNOWLEDGE_DIR")
            ),
            stack.enter_context(
                patch.object(main.sqlite3, "connect")
            ),
        ]

        for name in (
            "load_document_bytes",
            "rebuild_index",
            "delete_source_from_index",
            "ask",
            "ask_stream",
            "save_chat_history",
        ):
            mocked = stack.enter_context(
                patch.object(main, name)
            )
            self.guards.append(mocked)

        self.client = stack.enter_context(
            TestClient(main.app)
        )

    def assert_disabled(self, method, path, **kwargs):
        # 分别验证无凭证和携带占位 Bearer 头的请求。
        # 占位字符串不是真实登录令牌。
        for headers in (
            {},
            {"Authorization": "Bearer placeholder"},
        ):
            with self.subTest(method=method, path=path, headers=headers):
                response = self.client.request(
                    method,
                    path,
                    headers=headers,
                    **kwargs,
                )

                self.assertEqual(
                    response.status_code,
                    410,
                    response.text,
                )
                self.assertEqual(
                    response.json(),
                    {
                        "detail": (
                            "旧版共享接口已停用，"
                            "请使用登录后的个人知识库接口"
                        ),
                    },
                )

                for guard in self.guards:
                    self.assertEqual(
                        guard.mock_calls,
                        [],
                        "旧接口不应进入文件、数据库或模型处理逻辑",
                    )

    def test_upload_disabled(self):
        self.assert_disabled(
            "POST",
            "/api/upload",
            files={
                "file": (
                    "legacy-test.txt",
                    b"test content",
                    "text/plain",
                ),
            },
        )

    def test_list_files_disabled(self):
        self.assert_disabled("GET", "/api/files")

    def test_delete_file_disabled(self):
        self.assert_disabled(
            "DELETE",
            "/api/files/legacy-test.txt",
        )

    def test_index_disabled(self):
        self.assert_disabled("POST", "/api/index")

    def test_history_disabled(self):
        self.assert_disabled("GET", "/api/history")

    def test_chat_disabled(self):
        self.assert_disabled(
            "POST",
            "/api/chat",
            json={"question": "测试问题"},
        )

    def test_stream_disabled(self):
        self.assert_disabled(
            "POST",
            "/api/chat/stream",
            json={"question": "测试问题"},
        )


if __name__ == "__main__":
    unittest.main()