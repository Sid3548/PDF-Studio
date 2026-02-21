from __future__ import annotations

import io
import zipfile
import unittest
import warnings

import fitz

from app import pdf_ops
from tests.fixtures import make_digital_pdf, make_image_bytes, make_scanned_pdf

warnings.filterwarnings("ignore", category=ResourceWarning, module=r"PIL\..*")
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r"builtin type swigvarlink has no __module__ attribute",
)


def _open_pdf(payload: bytes) -> fitz.Document:
    return fitz.open(stream=payload, filetype="pdf")


class PDFOpsTests(unittest.TestCase):
    def test_parse_page_selection_supports_ranges(self) -> None:
        selection = pdf_ops.parse_page_selection("1,3-2,3", total_pages=4)
        self.assertEqual(selection, [0, 2, 1])

    def test_parse_reorder_requires_all_pages(self) -> None:
        with self.assertRaises(pdf_ops.PDFOperationError):
            pdf_ops.parse_reorder("1,2", total_pages=3)

    def test_rotate_pages_rotates_only_targets(self) -> None:
        source = make_digital_pdf(page_count=2)
        rotated = pdf_ops.rotate_pages(source, "2", 90)

        doc = _open_pdf(rotated)
        try:
            self.assertEqual(doc.page_count, 2)
            self.assertEqual(doc[0].rotation, 0)
            self.assertEqual(doc[1].rotation, 90)
        finally:
            doc.close()

    def test_duplicate_pages_adds_requested_copies(self) -> None:
        source = make_digital_pdf(page_count=2)
        duplicated = pdf_ops.duplicate_pages(source, "1", copies=2)

        doc = _open_pdf(duplicated)
        try:
            self.assertEqual(doc.page_count, 4)
        finally:
            doc.close()

    def test_delete_pages_rejects_deleting_everything(self) -> None:
        source = make_digital_pdf(page_count=2)
        with self.assertRaises(pdf_ops.PDFOperationError):
            pdf_ops.delete_pages(source, "1-2")

    def test_split_pdf_writes_zip_members(self) -> None:
        source = make_digital_pdf(page_count=3)
        archive_bytes = pdf_ops.split_pdf(source, "1-2;3")

        with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as zf:
            self.assertEqual(sorted(zf.namelist()), ["split_01.pdf", "split_02.pdf"])
            split_one = _open_pdf(zf.read("split_01.pdf"))
            split_two = _open_pdf(zf.read("split_02.pdf"))
            try:
                self.assertEqual(split_one.page_count, 2)
                self.assertEqual(split_two.page_count, 1)
            finally:
                split_one.close()
                split_two.close()

    def test_merge_pdfs_combines_inputs(self) -> None:
        merged = pdf_ops.merge_pdfs(
            [
                make_digital_pdf(page_count=1, text_prefix="A"),
                make_digital_pdf(page_count=2, text_prefix="B"),
            ]
        )
        doc = _open_pdf(merged)
        try:
            self.assertEqual(doc.page_count, 3)
        finally:
            doc.close()

    def test_replace_text_reports_replacement_count(self) -> None:
        source = make_digital_pdf(page_count=2, text_prefix="replace-me")
        updated, replacements = pdf_ops.replace_text(source, "replace-me", "done")
        self.assertGreaterEqual(replacements, 2)

        doc = _open_pdf(updated)
        try:
            all_text = "\n".join(doc[idx].get_text() for idx in range(doc.page_count))
            self.assertIn("done", all_text)
        finally:
            doc.close()

    def test_pdf_to_images_zip_generates_png_entries(self) -> None:
        source = make_digital_pdf(page_count=2)
        archive_bytes = pdf_ops.pdf_to_images_zip(source, fmt="png", dpi=120, pages_text="1")

        with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as zf:
            names = zf.namelist()
            self.assertEqual(len(names), 1)
            self.assertTrue(names[0].endswith(".png"))
            self.assertGreater(len(zf.read(names[0])), 0)

    def test_images_to_pdf_creates_expected_page_count(self) -> None:
        image_one = make_image_bytes((400, 300), (220, 10, 10))
        image_two = make_image_bytes((300, 400), (10, 180, 30))
        pdf_bytes = pdf_ops.images_to_pdf([image_one, image_two])

        doc = _open_pdf(pdf_bytes)
        try:
            self.assertEqual(doc.page_count, 2)
        finally:
            doc.close()

    def test_encrypt_then_decrypt_round_trip(self) -> None:
        source = make_digital_pdf(page_count=1)
        encrypted = pdf_ops.encrypt_pdf(source, user_password="secret123")

        encrypted_doc = _open_pdf(encrypted)
        try:
            self.assertTrue(encrypted_doc.needs_pass)
        finally:
            encrypted_doc.close()

        with self.assertRaises(pdf_ops.PDFOperationError):
            pdf_ops.decrypt_pdf(encrypted, password="wrong")

        decrypted = pdf_ops.decrypt_pdf(encrypted, password="secret123")
        decrypted_doc = _open_pdf(decrypted)
        try:
            self.assertFalse(decrypted_doc.needs_pass)
        finally:
            decrypted_doc.close()

    def test_scanned_detection_flags_image_only_pdfs(self) -> None:
        digital = make_digital_pdf(page_count=1)
        scanned = make_scanned_pdf(page_count=1)

        digital_analysis = pdf_ops.analyze_text_editability(digital)
        scanned_analysis = pdf_ops.analyze_text_editability(scanned)

        self.assertFalse(digital_analysis["is_scanned"])
        self.assertTrue(scanned_analysis["is_scanned"])

    def test_apply_click_text_edit_blocks_scanned_pdf(self) -> None:
        scanned = make_scanned_pdf(page_count=1)
        with self.assertRaises(pdf_ops.PDFOperationError):
            pdf_ops.apply_click_text_edit(
                scanned,
                page_number=1,
                x0=10,
                y0=10,
                x1=150,
                y1=50,
                new_text="edit",
            )

    def test_apply_click_text_edit_updates_text_for_digital_pdf(self) -> None:
        source = make_digital_pdf(page_count=1, text_prefix="Old Title")
        page_data = pdf_ops.get_page_text_items(source, page_number=1)
        bbox = page_data["text_items"][0]["bbox"]

        updated = pdf_ops.apply_click_text_edit(
            source,
            page_number=1,
            x0=bbox[0],
            y0=bbox[1],
            x1=bbox[2],
            y1=bbox[3],
            new_text="New Title",
            font_size=12,
        )

        doc = _open_pdf(updated)
        try:
            text = doc[0].get_text()
            self.assertIn("New Title", text)
        finally:
            doc.close()

    def test_add_text_at_point_blocks_scanned_pdf(self) -> None:
        scanned = make_scanned_pdf(page_count=1)
        with self.assertRaises(pdf_ops.PDFOperationError):
            pdf_ops.add_text_at_point(scanned, page_number=1, x=40, y=40, text="blocked")


if __name__ == "__main__":
    unittest.main()
