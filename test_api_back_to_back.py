from __future__ import annotations

import io
import unittest
import warnings
import zipfile

import fitz

from flask_app import create_app
from tests.fixtures import make_digital_pdf, make_image_bytes, make_scanned_pdf

warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r"builtin type swigvarlink has no __module__ attribute",
)


class BackToBackFeatureFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = create_app()
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()

    def _as_file(self, payload: bytes, name: str = "sample.pdf"):
        return io.BytesIO(payload), name

    def _post_ok(
        self,
        endpoint: str,
        data: dict,
        expected_content_type: str | None = None,
    ):
        response = self.client.post(endpoint, data=data, content_type="multipart/form-data")
        self.assertEqual(
            response.status_code,
            200,
            msg=f"{endpoint} returned {response.status_code}: {response.data[:240]!r}",
        )
        if expected_content_type:
            self.assertIn(expected_content_type, response.headers.get("Content-Type", ""))
        return response

    def _assert_pdf_bytes(self, payload: bytes, expected_pages_min: int = 1) -> fitz.Document:
        doc = fitz.open(stream=payload, filetype="pdf")
        self.assertGreaterEqual(doc.page_count, expected_pages_min)
        return doc

    def test_all_features_back_to_back(self) -> None:
        current_pdf = make_digital_pdf(page_count=4, text_prefix="pipeline")

        response = self._post_ok(
            "/api/rotate",
            {"file": self._as_file(current_pdf), "pages": "2-3", "angle": "90"},
            expected_content_type="application/pdf",
        )
        current_pdf = response.data

        response = self._post_ok(
            "/api/reorder",
            {"file": self._as_file(current_pdf), "order": "4,1,2,3"},
            expected_content_type="application/pdf",
        )
        current_pdf = response.data

        response = self._post_ok(
            "/api/reverse",
            {"file": self._as_file(current_pdf)},
            expected_content_type="application/pdf",
        )
        current_pdf = response.data

        response = self._post_ok(
            "/api/duplicate-pages",
            {"file": self._as_file(current_pdf), "pages": "1", "copies": "1"},
            expected_content_type="application/pdf",
        )
        current_pdf = response.data
        with self._assert_pdf_bytes(current_pdf, expected_pages_min=5) as doc:
            self.assertEqual(doc.page_count, 5)

        response = self._post_ok(
            "/api/delete-pages",
            {"file": self._as_file(current_pdf), "pages": "2"},
            expected_content_type="application/pdf",
        )
        current_pdf = response.data
        with self._assert_pdf_bytes(current_pdf, expected_pages_min=4) as doc:
            self.assertEqual(doc.page_count, 4)

        response = self._post_ok(
            "/api/extract-pages",
            {"file": self._as_file(current_pdf), "pages": "1-2"},
            expected_content_type="application/pdf",
        )
        extracted_pdf = response.data
        with self._assert_pdf_bytes(extracted_pdf, expected_pages_min=2) as doc:
            self.assertEqual(doc.page_count, 2)

        split_response = self._post_ok(
            "/api/split",
            {"file": self._as_file(extracted_pdf), "groups": "1;2"},
            expected_content_type="application/zip",
        )
        with zipfile.ZipFile(io.BytesIO(split_response.data), "r") as archive:
            names = sorted(archive.namelist())
            self.assertEqual(names, ["split_01.pdf", "split_02.pdf"])

        merge_response = self._post_ok(
            "/api/merge",
            {
                "files": [
                    self._as_file(extracted_pdf, "extracted.pdf"),
                    self._as_file(make_digital_pdf(page_count=1, text_prefix="merge"), "merge.pdf"),
                ]
            },
            expected_content_type="application/pdf",
        )
        current_pdf = merge_response.data
        with self._assert_pdf_bytes(current_pdf, expected_pages_min=3) as doc:
            self.assertEqual(doc.page_count, 3)

        response = self._post_ok(
            "/api/add-text",
            {
                "file": self._as_file(current_pdf),
                "page": "1",
                "text": "Manual text insert",
                "x": "120",
                "y": "180",
                "font_size": "12",
                "color": "#111111",
            },
            expected_content_type="application/pdf",
        )
        current_pdf = response.data

        response = self._post_ok(
            "/api/replace-text",
            {
                "file": self._as_file(current_pdf),
                "search_text": "pipeline",
                "replace_text": "updated",
            },
            expected_content_type="application/pdf",
        )
        self.assertIsNotNone(response.headers.get("X-Replacements"))
        current_pdf = response.data

        response = self._post_ok(
            "/api/watermark",
            {
                "file": self._as_file(current_pdf),
                "text": "CONFIDENTIAL",
                "font_size": "28",
                "density": "2",
                "shade": "0.8",
            },
            expected_content_type="application/pdf",
        )
        current_pdf = response.data

        response = self._post_ok(
            "/api/page-numbers",
            {"file": self._as_file(current_pdf), "position": "bottom-right", "font_size": "11"},
            expected_content_type="application/pdf",
        )
        current_pdf = response.data

        response = self._post_ok(
            "/api/crop",
            {
                "file": self._as_file(current_pdf),
                "pages": "1-2",
                "x0": "20",
                "y0": "20",
                "x1": "560",
                "y1": "780",
            },
            expected_content_type="application/pdf",
        )
        current_pdf = response.data

        response = self._post_ok(
            "/api/metadata",
            {
                "file": self._as_file(current_pdf),
                "title": "Pipeline Title",
                "author": "Pipeline Test",
                "subject": "Feature Flow",
                "keywords": "pdf,studio,pipeline",
            },
            expected_content_type="application/pdf",
        )
        current_pdf = response.data
        with fitz.open(stream=current_pdf, filetype="pdf") as doc:
            metadata = doc.metadata or {}
            self.assertEqual(metadata.get("title"), "Pipeline Title")
            self.assertEqual(metadata.get("author"), "Pipeline Test")

        response = self._post_ok(
            "/api/optimize",
            {"file": self._as_file(current_pdf)},
            expected_content_type="application/pdf",
        )
        current_pdf = response.data
        with self._assert_pdf_bytes(current_pdf, expected_pages_min=3):
            pass

        pdf_to_images = self._post_ok(
            "/api/pdf-to-images",
            {"file": self._as_file(current_pdf), "fmt": "png", "dpi": "100", "pages": "1-2"},
            expected_content_type="application/zip",
        )
        with zipfile.ZipFile(io.BytesIO(pdf_to_images.data), "r") as archive:
            image_names = sorted(archive.namelist())
            self.assertEqual(len(image_names), 2)
            self.assertTrue(all(name.endswith(".png") for name in image_names))

        images_to_pdf = self._post_ok(
            "/api/images-to-pdf",
            {
                "files": [
                    (io.BytesIO(make_image_bytes((300, 200), (190, 40, 40))), "one.png"),
                    (io.BytesIO(make_image_bytes((200, 300), (30, 150, 60))), "two.png"),
                ]
            },
            expected_content_type="application/pdf",
        )
        with self._assert_pdf_bytes(images_to_pdf.data, expected_pages_min=2) as doc:
            self.assertEqual(doc.page_count, 2)

        encrypted = self._post_ok(
            "/api/encrypt",
            {
                "file": self._as_file(current_pdf),
                "user_password": "userpass123",
                "owner_password": "ownerpass123",
                "allow_print": "true",
                "allow_copy": "false",
            },
            expected_content_type="application/pdf",
        )
        encrypted_pdf = encrypted.data
        with fitz.open(stream=encrypted_pdf, filetype="pdf") as doc:
            self.assertTrue(doc.needs_pass)

        decrypted = self._post_ok(
            "/api/decrypt",
            {"file": self._as_file(encrypted_pdf, "encrypted.pdf"), "password": "userpass123"},
            expected_content_type="application/pdf",
        )
        current_pdf = decrypted.data
        with fitz.open(stream=current_pdf, filetype="pdf") as doc:
            self.assertFalse(doc.needs_pass)

        analysis = self._post_ok(
            "/api/text-editor/analyze",
            {"file": self._as_file(current_pdf)},
        ).get_json()
        self.assertFalse(bool(analysis.get("is_scanned")))

        page_data = self._post_ok(
            "/api/text-editor/page",
            {"file": self._as_file(current_pdf), "page": "1", "zoom": "1.2"},
        ).get_json()
        self.assertGreater(len(page_data["text_items"]), 0)
        self.assertTrue(page_data["image_data_url"].startswith("data:image/png;base64,"))

        x0, y0, x1, y1 = page_data["text_items"][0]["bbox"]
        edited = self._post_ok(
            "/api/text-editor/apply",
            {
                "file": self._as_file(current_pdf),
                "page": "1",
                "x0": str(x0),
                "y0": str(y0),
                "x1": str(x1),
                "y1": str(y1),
                "new_text": "Edited in pipeline",
                "font_size": "12",
            },
            expected_content_type="application/pdf",
        )
        current_pdf = edited.data

        added = self._post_ok(
            "/api/text-editor/add",
            {
                "file": self._as_file(current_pdf),
                "page": "1",
                "x": "130",
                "y": "240",
                "text": "Added in pipeline",
                "font_size": "12",
                "color": "#000000",
            },
            expected_content_type="application/pdf",
        )
        current_pdf = added.data
        with self._assert_pdf_bytes(current_pdf, expected_pages_min=3):
            pass

        scanned_pdf = make_scanned_pdf(page_count=1)
        scanned_analysis = self._post_ok(
            "/api/text-editor/analyze",
            {"file": self._as_file(scanned_pdf, "scanned.pdf")},
        ).get_json()
        self.assertTrue(bool(scanned_analysis.get("is_scanned")))

        blocked_add = self.client.post(
            "/api/text-editor/add",
            data={
                "file": self._as_file(scanned_pdf, "scanned.pdf"),
                "page": "1",
                "x": "100",
                "y": "100",
                "text": "Should fail",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(blocked_add.status_code, 400)
        self.assertIn("scanned", blocked_add.get_json()["error"].lower())

        blocked_edit = self.client.post(
            "/api/text-editor/apply",
            data={
                "file": self._as_file(scanned_pdf, "scanned.pdf"),
                "page": "1",
                "x0": "10",
                "y0": "10",
                "x1": "80",
                "y1": "40",
                "new_text": "Should fail",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(blocked_edit.status_code, 400)
        self.assertIn("scanned", blocked_edit.get_json()["error"].lower())


if __name__ == "__main__":
    unittest.main()

