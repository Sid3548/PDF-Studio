from __future__ import annotations

import io

import fitz
from PIL import Image, ImageDraw

A4_WIDTH = 595
A4_HEIGHT = 842


def make_digital_pdf(page_count: int = 2, text_prefix: str = "Hello PDF Studio") -> bytes:
    """Create a simple text-based PDF suitable for edit operations."""
    doc = fitz.open()
    try:
        for index in range(page_count):
            page = doc.new_page(width=A4_WIDTH, height=A4_HEIGHT)
            page.insert_text((72, 72), f"{text_prefix} page {index + 1}", fontsize=14)
            page.insert_text((72, 110), "This line is editable text.", fontsize=12)
        return doc.tobytes()
    finally:
        doc.close()


def make_scanned_pdf(page_count: int = 1, label: str = "SCANNED PAGE") -> bytes:
    """Create an image-only PDF that should be flagged as scanned."""
    image = Image.new("RGB", (A4_WIDTH, A4_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 100), label, fill="black")

    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_bytes = image_buffer.getvalue()

    doc = fitz.open()
    try:
        for _ in range(page_count):
            page = doc.new_page(width=A4_WIDTH, height=A4_HEIGHT)
            page.insert_image(page.rect, stream=image_bytes)
        return doc.tobytes()
    finally:
        doc.close()


def make_image_bytes(size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    """Create a solid-color PNG image payload."""
    image = Image.new("RGB", size, color)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()

