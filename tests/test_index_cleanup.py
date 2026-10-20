import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.index_cleanup import clean_unused, cleanup_candidates


class IndexCleanupTests(unittest.TestCase):
    def setUp(self):
        self.old = f"kb_1_{'a' * 32}"
        self.active = f"kb_1_{'b' * 32}"
        self.client = MagicMock()
        self.client.list_collections.return_value = [
            SimpleNamespace(name=self.old), self.active, "intern_rag", "unknown",
        ]
        self.db = MagicMock()
        self.db.scalars.return_value.all.return_value = [self.active]

    def test_only_valid_unreferenced_collections_are_candidates(self):
        names = [self.old, self.active, "intern_rag", "kb_0_" + "c" * 32, "kb_1_bad", "../x"]
        self.assertEqual(cleanup_candidates(names, {self.active}), [self.old])

    def test_preview_does_not_delete(self):
        result = clean_unused(self.client, self.db)
        self.assertEqual(result["candidates"], [self.old])
        self.assertEqual(result["removed"], [])
        self.client.delete_collection.assert_not_called()

    def test_apply_preserves_active_and_shared_collections(self):
        result = clean_unused(self.client, self.db, apply=True)
        self.assertEqual(result["removed"], [self.old])
        self.client.delete_collection.assert_called_once_with(name=self.old)

    def test_new_reference_is_rechecked_before_delete(self):
        self.db.scalars.return_value.all.side_effect = [[self.active], [self.active, self.old]]
        result = clean_unused(self.client, self.db, apply=True)
        self.assertEqual(result["removed"], [])
        self.client.delete_collection.assert_not_called()
