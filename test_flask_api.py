from __future__ import annotations

import io
import unittest
import warnings

from flask_app import create_app
from tests.fixtures import make_digital_pdf, make_scanned_pdf

warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r"builtin type swigvarlink has no __module__ attribute",
)


class FlaskApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = create_app()
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()

    def test_health_endpoint(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_root_serves_ui(self) -> None:
        response = self.client.get("/")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"PDF STUDIO", response.data)
        finally:
            response.close()

    def test_unknown_api_path_returns_json_404(self) -> None:
        response = self.client.get("/api/not-real")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {"error": "Not found"})

    def test_rotate_endpoint_returns_pdf(self) -> None:
        payload = {
            "file": (io.BytesIO(make_digital_pdf(page_count=2)), "sample.pdf"),
            "angle": "90",
            "pages": "2",
        }
        response = self.client.post("/api/rotate", data=payload, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/pdf", response.headers.get("Content-Type", ""))

    def test_rotate_missing_angle_returns_400(self) -> None:
        payload = {"file": (io.BytesIO(make_digital_pdf(page_count=1)), "sample.pdf")}
        response = self.client.post("/api/rotate", data=payload, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Missing required form field", response.get_json()["error"])

    def test_merge_endpoint_returns_pdf(self) -> None:
        payload = {
            "files": [
                (io.BytesIO(make_digital_pdf(page_count=1, text_prefix="one")), "one.pdf"),
                (io.BytesIO(make_digital_pdf(page_count=1, text_prefix="two")), "two.pdf"),
            ]
        }
        response = self.client.post("/api/merge", data=payload, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/pdf", response.headers.get("Content-Type", ""))

    def test_replace_text_exposes_replacements_header(self) -> None:
        payload = {
            "file": (io.BytesIO(make_digital_pdf(page_count=1, text_prefix="abc")), "sample.pdf"),
            "search_text": "abc",
            "replace_text": "xyz",
        }
        response = self.client.post("/api/replace-text", data=payload, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.headers.get("X-Replacements"))

    def test_text_editor_page_returns_image_and_items(self) -> None:
        payload = {
            "file": (io.BytesIO(make_digital_pdf(page_count=1)), "sample.pdf"),
            "page": "1",
            "zoom": "1.2",
        }
        response = self.client.post(
            "/api/text-editor/page",
            data=payload,
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["page_number"], 1)
        self.assertFalse(data["is_scanned"])
        self.assertTrue(data["image_data_url"].startswith("data:image/png;base64,"))
        self.assertGreater(len(data["text_items"]), 0)

    def test_text_editor_apply_works_for_digital_pdf(self) -> None:
        source = make_digital_pdf(page_count=1)
        page_response = self.client.post(
            "/api/text-editor/page",
            data={"file": (io.BytesIO(source), "source.pdf"), "page": "1"},
            content_type="multipart/form-data",
        )
        self.assertEqual(page_response.status_code, 200)
        bbox = page_response.get_json()["text_items"][0]["bbox"]

        payload = {
            "file": (io.BytesIO(source), "source.pdf"),
            "page": "1",
            "x0": str(bbox[0]),
            "y0": str(bbox[1]),
            "x1": str(bbox[2]),
            "y1": str(bbox[3]),
            "new_text": "Edited from API test",
        }
        response = self.client.post(
            "/api/text-editor/apply",
            data=payload,
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/pdf", response.headers.get("Content-Type", ""))

    def test_scanned_pdf_is_flagged_and_blocked_for_interactive_edit(self) -> None:
        scanned = make_scanned_pdf(page_count=1)

        analyze_resp = self.client.post(
            "/api/text-editor/analyze",
            data={"file": (io.BytesIO(scanned), "scan.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(analyze_resp.status_code, 200)
        self.assertTrue(analyze_resp.get_json()["is_scanned"])

        add_resp = self.client.post(
            "/api/text-editor/add",
            data={
                "file": (io.BytesIO(scanned), "scan.pdf"),
                "page": "1",
                "x": "50",
                "y": "50",
                "text": "blocked",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(add_resp.status_code, 400)
        self.assertIn("scanned", add_resp.get_json()["error"].lower())

        apply_resp = self.client.post(
            "/api/text-editor/apply",
            data={
                "file": (io.BytesIO(scanned), "scan.pdf"),
                "page": "1",
                "x0": "10",
                "y0": "10",
                "x1": "100",
                "y1": "40",
                "new_text": "blocked",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(apply_resp.status_code, 400)
        self.assertIn("scanned", apply_resp.get_json()["error"].lower())

    def test_request_too_large_returns_413_json(self) -> None:
        app = create_app()
        app.config.update(TESTING=True, MAX_CONTENT_LENGTH=128)
        client = app.test_client()

        too_large_payload = b"x" * 4096
        response = client.post(
            "/api/rotate",
            data={"file": (io.BytesIO(too_large_payload), "large.pdf"), "angle": "90"},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 413)
        self.assertIn("Upload too large", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
