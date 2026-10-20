import unittest
from uuid import uuid4

import requests

from test_document_loader import make_pdf


class PdfUploadTests(unittest.TestCase):
    def test_upload_pdf_and_delete(self):
        filename = f"api_test_{uuid4().hex}.pdf"
        base_url = "http://127.0.0.1:8001"

        with requests.Session() as client:
            # 本机请求不走系统代理。
            client.trust_env = False

            response = client.post(
                f"{base_url}/api/upload",
                files={
                    "file": (
                        filename,
                        make_pdf(),
                        "application/pdf",
                    )
                },
                timeout=30,
            )
            self.assertEqual(response.status_code, 200, response.text)

            try:
                self.assertEqual(response.json()["filename"], filename)

                listing = client.get(
                    f"{base_url}/api/files",
                    timeout=10,
                )
                self.assertEqual(listing.status_code, 200, listing.text)
                names = [item["name"] for item in listing.json()]
                self.assertIn(filename, names)
            finally:
                deleted = client.delete(
                    f"{base_url}/api/files/{filename}",
                    timeout=30,
                )
                self.assertEqual(deleted.status_code, 200, deleted.text)

            listing = client.get(
                f"{base_url}/api/files",
                timeout=10,
            )
            self.assertEqual(listing.status_code, 200, listing.text)
            names = [item["name"] for item in listing.json()]
            self.assertNotIn(filename, names)