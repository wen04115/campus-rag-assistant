import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class FrontendServingTests(unittest.TestCase):
    def setUp(self):
        outputs = Path(__file__).resolve().parents[1] / "outputs"
        outputs.mkdir(exist_ok=True)
        temporary = TemporaryDirectory(dir=outputs, prefix="frontend_test_")
        self.addCleanup(temporary.cleanup)
        self.web = Path(temporary.name)
        patcher = patch.object(main, "FRONTEND_DIR", self.web)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def test_development_root_points_to_vite_not_legacy_ui(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("5173", response.json()["message"])

    def test_built_index_is_served(self):
        (self.web / "index.html").write_text("<html>test frontend</html>", encoding="utf-8")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("test frontend", response.text)
        self.assertIn("text/html", response.headers["content-type"])

    def test_favicon(self):
        self.assertEqual(self.client.get("/favicon.svg").status_code, 404)
        (self.web / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
        response = self.client.get("/favicon.svg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "<svg></svg>")
