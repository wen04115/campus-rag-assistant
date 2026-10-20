import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.documents import Document

from app import kb_index as api


class KBIndexTests(unittest.TestCase):
    def setUp(self):
        outputs = Path(__file__).resolve().parents[1] / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)

        temporary = TemporaryDirectory(
            prefix="kb_index_test_",
            dir=outputs,
        )
        self.addCleanup(temporary.cleanup)

        self.root = Path(temporary.name)
        self.storage = self.root / "documents"

        self.patch_attribute("DOCUMENT_DIR", self.storage)
        self.patch_attribute("VECTOR_DIR", self.root / "vectors")
        self.embeddings = self.mock_attribute("_embeddings")
        self.chroma = self.mock_attribute("Chroma")
        self.store = self.chroma.return_value

    def patch_attribute(self, name, value):
        patcher = patch.object(api, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def mock_attribute(self, name):
        patcher = patch.object(api, name)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def make_document(self):
        directory = self.storage / "1"
        directory.mkdir(parents=True, exist_ok=True)

        storage_name = f"{'a' * 32}.txt"
        content = b"hello"
        (directory / storage_name).write_bytes(content)

        return api.IndexDocument(
            id=10,
            knowledge_base_id=1,
            original_name="example.txt",
            storage_name=storage_name,
            size=len(content),
        )

    def test_invalid_inputs_do_not_create_collection(self):
        document = self.make_document()

        cases = [
            (0, [document]),
            (1, []),
            (1, [replace(document, knowledge_base_id=2)]),
            (1, [replace(document, storage_name="../outside.txt")]),
            (1, [replace(document, size=999)]),
        ]

        for library_id, documents in cases:
            with self.subTest(library_id=library_id, documents=documents):
                with self.assertRaises(ValueError):
                    api.build_knowledge_base_index(
                        library_id,
                        documents,
                    )

        self.chroma.assert_not_called()
        self.embeddings.assert_not_called()

    def test_build_uses_only_listed_documents_and_new_collection(self):
        document = self.make_document()

        # 不在数据库清单中的文件，不应被读取。
        (self.storage / "1" / "unlisted.txt").write_bytes(b"secret")

        first = api.build_knowledge_base_index(1, [document])
        second = api.build_knowledge_base_index(1, [document])

        self.assertEqual(first["documents"], 1)
        self.assertEqual(first["chunks"], 1)
        self.assertNotEqual(
            first["collection_name"],
            second["collection_name"],
        )
        self.assertRegex(
            first["collection_name"],
            r"^kb_1_[0-9a-f]{32}$",
        )

        names = [
            call.kwargs["collection_name"]
            for call in self.chroma.call_args_list
        ]
        self.assertEqual(
            names,
            [
                first["collection_name"],
                second["collection_name"],
            ],
        )

        written = self.store.add_documents.call_args.kwargs
        self.assertEqual(written["ids"], ["10_1"])

        chunk = written["documents"][0]
        self.assertEqual(chunk.page_content, "hello")
        self.assertEqual(chunk.metadata["source"], "example.txt")
        self.assertEqual(chunk.metadata["knowledge_base_id"], 1)
        self.assertEqual(chunk.metadata["document_id"], 10)
        self.assertEqual(chunk.metadata["chunk_index"], 1)

        self.store.delete_collection.assert_not_called()

    def test_chunks_are_written_in_batches_and_keep_page(self):
        document = self.make_document()

        chunks = [
            Document(
                page_content=f"chunk {number}",
                metadata={"source": "example.txt", "page": 2},
            )
            for number in range(130)
        ]

        with patch.object(
            api,
            "RecursiveCharacterTextSplitter",
        ) as splitter:
            splitter.return_value.split_documents.return_value = chunks
            result = api.build_knowledge_base_index(1, [document])

        calls = self.store.add_documents.call_args_list

        self.assertEqual(result["chunks"], 130)
        self.assertEqual(
            [len(call.kwargs["documents"]) for call in calls],
            [64, 64, 2],
        )

        ids = [
            item
            for call in calls
            for item in call.kwargs["ids"]
        ]
        self.assertEqual(len(set(ids)), 130)
        self.assertEqual(ids[0], "10_1")
        self.assertEqual(ids[-1], "10_130")

        for chunk in chunks:
            self.assertEqual(chunk.metadata["page"], 2)
            self.assertEqual(chunk.metadata["knowledge_base_id"], 1)
            self.assertEqual(chunk.metadata["document_id"], 10)

    def test_write_failure_cleans_up_new_collection(self):
        document = self.make_document()
        failure = RuntimeError("test vector write failure")
        self.store.add_documents.side_effect = failure

        with self.assertRaises(RuntimeError) as caught:
            api.build_knowledge_base_index(1, [document])

        self.assertIs(caught.exception, failure)
        self.chroma.assert_called_once()
        self.store.delete_collection.assert_called_once_with()

        name = self.chroma.call_args.kwargs["collection_name"]
        self.assertRegex(name, r"^kb_1_[0-9a-f]{32}$")
        self.assertNotEqual(name, "intern_rag")

    def test_missing_file_does_not_create_collection(self):
        document = self.make_document()
        missing = replace(
            document,
            storage_name=f"{'e' * 32}.txt",
        )

        with self.assertRaises(FileNotFoundError):
            api.build_knowledge_base_index(1, [missing])

        self.chroma.assert_not_called()
        self.embeddings.assert_not_called()