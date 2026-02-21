from __future__ import annotations

import io
import re
import zipfile
from base64 import b64encode
from typing import Sequence

import fitz  # PyMuPDF
from PIL import Image


class PDFOperationError(ValueError):
    """Raised when operation inputs are invalid."""


def _parse_int(value: str, *, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PDFOperationError(f"Invalid {label}: '{value}'.") from exc


def parse_page_selection(selection: str | None, total_pages: int, *, default_all: bool = True) -> list[int]:
    """
    Parse a human page selection string (1-based) into 0-based page indexes.

    Supported syntax:
    - "1,3,5"
    - "1-4,8,10-12"
    - empty string => all pages when default_all=True
    """
    if total_pages <= 0:
        raise PDFOperationError("PDF has no pages.")

    if selection is None or not selection.strip():
        return list(range(total_pages)) if default_all else []

    indexes: list[int] = []
    seen: set[int] = set()

    for raw_part in selection.split(","):
        part = raw_part.strip()
        if not part:
            continue

        if "-" in part:
            start_s, end_s = [p.strip() for p in part.split("-", 1)]
            start = _parse_int(start_s, label="range start")
            end = _parse_int(end_s, label="range end")
            step = 1 if end >= start else -1
            page_numbers = range(start, end + step, step)
        else:
            page_numbers = [_parse_int(part, label="page number")]

        for page_number in page_numbers:
            if page_number < 1 or page_number > total_pages:
                raise PDFOperationError(
                    f"Page {page_number} is out of bounds. Valid range: 1-{total_pages}."
                )
            idx = page_number - 1
            if idx not in seen:
                indexes.append(idx)
                seen.add(idx)

    if not indexes:
        raise PDFOperationError("No valid pages were selected.")

    return indexes


def parse_split_groups(groups_text: str | None, total_pages: int) -> list[list[int]]:
    """
    Parse split groups.

    Example: "1-3;4-6;7,8" => [[0,1,2], [3,4,5], [6,7]]
    """
    if groups_text is None or not groups_text.strip():
        return [[i] for i in range(total_pages)]

    chunks = [c.strip() for c in re.split(r"[;|]+", groups_text) if c.strip()]
    if not chunks:
        raise PDFOperationError("Split ranges are empty.")

    used: set[int] = set()
    groups: list[list[int]] = []

    for chunk in chunks:
        group = parse_page_selection(chunk, total_pages, default_all=False)
        overlap = set(group).intersection(used)
        if overlap:
            dup = sorted(i + 1 for i in overlap)
            raise PDFOperationError(f"Split ranges overlap at pages: {dup}")
        groups.append(group)
        used.update(group)

    return groups


def parse_reorder(order_text: str, total_pages: int) -> list[int]:
    order = parse_page_selection(order_text, total_pages, default_all=False)
    if len(order) != total_pages:
        raise PDFOperationError(
            f"Reorder list must include every page exactly once (expected {total_pages} pages)."
        )
    return order


def _open_pdf(pdf_bytes: bytes, password: str | None = None) -> fitz.Document:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # pragma: no cover - depends on fitz internals
        raise PDFOperationError("Could not read PDF file.") from exc

    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            doc.close()
            raise PDFOperationError("PDF is password protected. Invalid or missing password.")
    return doc


def _save_pdf(doc: fitz.Document, **kwargs) -> bytes:
    output = io.BytesIO()
    doc.save(output, **kwargs)
    return output.getvalue()


def rotate_pages(pdf_bytes: bytes, pages_text: str | None, angle: int) -> bytes:
    if angle % 90 != 0:
        raise PDFOperationError("Rotation angle must be a multiple of 90.")

    doc = _open_pdf(pdf_bytes)
    try:
        targets = parse_page_selection(pages_text, doc.page_count)
        for idx in targets:
            page = doc[idx]
            page.set_rotation((page.rotation + angle) % 360)
        return _save_pdf(doc)
    finally:
        doc.close()


def reorder_pages(pdf_bytes: bytes, order_text: str) -> bytes:
    src = _open_pdf(pdf_bytes)
    result = fitz.open()
    try:
        order = parse_reorder(order_text, src.page_count)
        for idx in order:
            result.insert_pdf(src, from_page=idx, to_page=idx)
        return _save_pdf(result)
    finally:
        result.close()
        src.close()


def reverse_pages(pdf_bytes: bytes) -> bytes:
    src = _open_pdf(pdf_bytes)
    result = fitz.open()
    try:
        for idx in range(src.page_count - 1, -1, -1):
            result.insert_pdf(src, from_page=idx, to_page=idx)
        return _save_pdf(result)
    finally:
        result.close()
        src.close()


def duplicate_pages(pdf_bytes: bytes, pages_text: str, copies: int = 1) -> bytes:
    if copies < 1 or copies > 10:
        raise PDFOperationError("Copies must be between 1 and 10.")

    src = _open_pdf(pdf_bytes)
    result = fitz.open()
    try:
        selected = set(parse_page_selection(pages_text, src.page_count, default_all=False))
        for idx in range(src.page_count):
            result.insert_pdf(src, from_page=idx, to_page=idx)
            if idx in selected:
                for _ in range(copies):
                    result.insert_pdf(src, from_page=idx, to_page=idx)
        return _save_pdf(result)
    finally:
        result.close()
        src.close()


def delete_pages(pdf_bytes: bytes, pages_text: str) -> bytes:
    src = _open_pdf(pdf_bytes)
    result = fitz.open()
    try:
        to_delete = set(parse_page_selection(pages_text, src.page_count, default_all=False))
        if len(to_delete) >= src.page_count:
            raise PDFOperationError("Cannot delete all pages. Keep at least one page.")

        for idx in range(src.page_count):
            if idx not in to_delete:
                result.insert_pdf(src, from_page=idx, to_page=idx)
        return _save_pdf(result)
    finally:
        result.close()
        src.close()


def extract_pages(pdf_bytes: bytes, pages_text: str) -> bytes:
    src = _open_pdf(pdf_bytes)
    result = fitz.open()
    try:
        selected = parse_page_selection(pages_text, src.page_count, default_all=False)
        for idx in selected:
            result.insert_pdf(src, from_page=idx, to_page=idx)
        return _save_pdf(result)
    finally:
        result.close()
        src.close()


def split_pdf(pdf_bytes: bytes, groups_text: str | None) -> bytes:
    src = _open_pdf(pdf_bytes)
    try:
        groups = parse_split_groups(groups_text, src.page_count)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for index, group in enumerate(groups, start=1):
                chunk = fitz.open()
                try:
                    for page_idx in group:
                        chunk.insert_pdf(src, from_page=page_idx, to_page=page_idx)
                    zf.writestr(f"split_{index:02d}.pdf", _save_pdf(chunk))
                finally:
                    chunk.close()
        return archive.getvalue()
    finally:
        src.close()


def merge_pdfs(pdf_files: Sequence[bytes]) -> bytes:
    result = fitz.open()
    try:
        for payload in pdf_files:
            if not payload:
                continue
            doc = _open_pdf(payload)
            try:
                result.insert_pdf(doc)
            finally:
                doc.close()

        if result.page_count == 0:
            raise PDFOperationError("No valid PDF files were uploaded.")

        return _save_pdf(result)
    finally:
        result.close()


def add_text(
    pdf_bytes: bytes,
    page_number: int,
    text: str,
    x: float,
    y: float,
    font_size: float = 12,
    color: tuple[float, float, float] = (0, 0, 0),
) -> bytes:
    if not text.strip():
        raise PDFOperationError("Text cannot be empty.")
    if font_size <= 0:
        raise PDFOperationError("Font size must be positive.")

    doc = _open_pdf(pdf_bytes)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise PDFOperationError(f"Page must be between 1 and {doc.page_count}.")

        page = doc[page_number - 1]
        page.insert_text((x, y), text, fontsize=font_size, color=color, overlay=True)
        return _save_pdf(doc)
    finally:
        doc.close()


def add_text_at_point(
    pdf_bytes: bytes,
    *,
    page_number: int,
    text: str,
    x: float,
    y: float,
    font_size: float = 12,
    color: tuple[float, float, float] = (0, 0, 0),
) -> bytes:
    analysis = analyze_text_editability(pdf_bytes)
    if bool(analysis.get("is_scanned")):
        raise PDFOperationError(
            "This file looks scanned. Direct text editing is available only for digital PDFs."
        )
    return add_text(
        pdf_bytes,
        page_number=page_number,
        text=text,
        x=x,
        y=y,
        font_size=font_size,
        color=color,
    )


def replace_text(pdf_bytes: bytes, search_text: str, replace_text_value: str) -> tuple[bytes, int]:
    if not search_text:
        raise PDFOperationError("Search text cannot be empty.")

    doc = _open_pdf(pdf_bytes)
    total_replacements = 0
    try:
        for page in doc:
            rects = page.search_for(search_text)
            if not rects:
                continue

            for rect in rects:
                page.add_redact_annot(rect, fill=(1, 1, 1))
            page.apply_redactions()

            for rect in rects:
                font_size = max(6, min(18, rect.height * 0.8))
                target = fitz.Rect(
                    rect.x0,
                    rect.y0,
                    rect.x1 + max(8, rect.width * 0.6),
                    rect.y1 + 2,
                )
                placed = page.insert_textbox(
                    target,
                    replace_text_value,
                    fontsize=font_size,
                    color=(0, 0, 0),
                    align=fitz.TEXT_ALIGN_LEFT,
                    overlay=True,
                )
                if placed < 0:
                    baseline_y = min(page.rect.y1 - 2, rect.y1 - 1)
                    page.insert_text(
                        (rect.x0, baseline_y),
                        replace_text_value,
                        fontsize=max(6, font_size - 1),
                        color=(0, 0, 0),
                        overlay=True,
                    )
                total_replacements += 1

        return _save_pdf(doc), total_replacements
    finally:
        doc.close()


def watermark_text(
    pdf_bytes: bytes,
    text: str,
    font_size: float = 32,
    density: int = 3,
    shade: float = 0.75,
) -> bytes:
    if not text.strip():
        raise PDFOperationError("Watermark text cannot be empty.")
    if font_size <= 0:
        raise PDFOperationError("Font size must be positive.")
    if density < 1 or density > 8:
        raise PDFOperationError("Density must be between 1 and 8.")
    if not (0 <= shade <= 1):
        raise PDFOperationError("Shade must be between 0 and 1.")

    color = (shade, shade, shade)

    doc = _open_pdf(pdf_bytes)
    try:
        for page in doc:
            rect = page.rect
            x_step = max(120, rect.width / density)
            y_step = max(120, rect.height / density)

            y = -rect.height * 0.25
            while y < rect.height * 1.2:
                x = -rect.width * 0.25
                while x < rect.width * 1.2:
                    page.insert_text(
                        (x, y),
                        text,
                        fontsize=font_size,
                        color=color,
                        rotate=0,
                        overlay=True,
                    )
                    x += x_step
                y += y_step

        return _save_pdf(doc)
    finally:
        doc.close()


def add_page_numbers(
    pdf_bytes: bytes,
    position: str = "bottom-right",
    font_size: float = 12,
) -> bytes:
    if font_size <= 0:
        raise PDFOperationError("Font size must be positive.")

    valid_positions = {
        "top-left",
        "top-center",
        "top-right",
        "bottom-left",
        "bottom-center",
        "bottom-right",
    }
    if position not in valid_positions:
        raise PDFOperationError(f"Invalid position. Choose from: {', '.join(sorted(valid_positions))}")

    doc = _open_pdf(pdf_bytes)
    margin = 18

    try:
        for idx, page in enumerate(doc, start=1):
            label = str(idx)
            width = fitz.get_text_length(label, fontsize=font_size)
            rect = page.rect

            if "left" in position:
                x = margin
            elif "center" in position:
                x = (rect.width - width) / 2
            else:
                x = rect.width - width - margin

            y = margin + font_size if "top" in position else rect.height - margin
            page.insert_text((x, y), label, fontsize=font_size, color=(0, 0, 0), overlay=True)

        return _save_pdf(doc)
    finally:
        doc.close()


def pdf_to_images_zip(
    pdf_bytes: bytes,
    fmt: str = "png",
    dpi: int = 150,
    pages_text: str | None = None,
    jpeg_quality: int = 90,
) -> bytes:
    fmt = fmt.lower()
    if fmt not in {"png", "jpg", "jpeg"}:
        raise PDFOperationError("Image format must be png or jpg.")
    if dpi < 72 or dpi > 600:
        raise PDFOperationError("DPI must be between 72 and 600.")

    doc = _open_pdf(pdf_bytes)
    try:
        pages = parse_page_selection(pages_text, doc.page_count)
        archive = io.BytesIO()

        with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zoom = dpi / 72
            matrix = fitz.Matrix(zoom, zoom)

            for idx in pages:
                page = doc[idx]
                pix = page.get_pixmap(matrix=matrix, alpha=False)

                if fmt == "png":
                    image_bytes = pix.tobytes("png")
                    extension = "png"
                else:
                    mode = "RGB" if pix.n < 4 else "RGBA"
                    img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    out = io.BytesIO()
                    img.save(out, format="JPEG", quality=jpeg_quality, optimize=True)
                    image_bytes = out.getvalue()
                    extension = "jpg"

                zf.writestr(f"page_{idx + 1:03d}.{extension}", image_bytes)

        return archive.getvalue()
    finally:
        doc.close()


def images_to_pdf(image_files: Sequence[bytes]) -> bytes:
    if not image_files:
        raise PDFOperationError("Upload at least one image.")

    images: list[Image.Image] = []
    try:
        for payload in image_files:
            with Image.open(io.BytesIO(payload)) as img:
                normalized = img.convert("RGB") if img.mode != "RGB" else img.copy()
                images.append(normalized)

        if not images:
            raise PDFOperationError("No valid images found.")

        first, *rest = images
        output = io.BytesIO()
        first.save(output, format="PDF", save_all=True, append_images=rest)
        return output.getvalue()
    finally:
        for img in images:
            img.close()


def encrypt_pdf(
    pdf_bytes: bytes,
    user_password: str,
    owner_password: str | None = None,
    allow_print: bool = True,
    allow_copy: bool = False,
) -> bytes:
    if not user_password:
        raise PDFOperationError("User password is required.")

    doc = _open_pdf(pdf_bytes)
    try:
        owner = owner_password or user_password
        permissions = fitz.PDF_PERM_ACCESSIBILITY
        if allow_print:
            permissions |= fitz.PDF_PERM_PRINT
        if allow_copy:
            permissions |= fitz.PDF_PERM_COPY

        return _save_pdf(
            doc,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw=user_password,
            owner_pw=owner,
            permissions=permissions,
        )
    finally:
        doc.close()


def decrypt_pdf(pdf_bytes: bytes, password: str) -> bytes:
    if not password:
        raise PDFOperationError("Password is required.")

    doc = _open_pdf(pdf_bytes, password=password)
    try:
        return _save_pdf(doc, encryption=fitz.PDF_ENCRYPT_NONE)
    finally:
        doc.close()


def update_metadata(
    pdf_bytes: bytes,
    *,
    title: str | None = None,
    author: str | None = None,
    subject: str | None = None,
    keywords: str | None = None,
) -> bytes:
    doc = _open_pdf(pdf_bytes)
    try:
        metadata = dict(doc.metadata or {})

        updates = {
            "title": title,
            "author": author,
            "subject": subject,
            "keywords": keywords,
        }
        for key, value in updates.items():
            if value is not None:
                metadata[key] = value

        doc.set_metadata(metadata)
        return _save_pdf(doc)
    finally:
        doc.close()


def crop_pages(
    pdf_bytes: bytes,
    pages_text: str | None,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> bytes:
    if x1 <= x0 or y1 <= y0:
        raise PDFOperationError("Invalid crop rectangle. Ensure x1>x0 and y1>y0.")

    doc = _open_pdf(pdf_bytes)
    try:
        targets = parse_page_selection(pages_text, doc.page_count)

        for idx in targets:
            page = doc[idx]
            requested = fitz.Rect(x0, y0, x1, y1)
            bounded = requested & page.rect
            if bounded.is_empty or bounded.width <= 0 or bounded.height <= 0:
                raise PDFOperationError(f"Crop area is outside page {idx + 1}.")
            page.set_cropbox(bounded)

        return _save_pdf(doc)
    finally:
        doc.close()


def optimize_pdf(pdf_bytes: bytes) -> bytes:
    doc = _open_pdf(pdf_bytes)
    try:
        return _save_pdf(doc, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()


def analyze_text_editability(pdf_bytes: bytes, sample_pages: int = 6) -> dict[str, object]:
    """
    Heuristic scanner detection:
    - A scanned PDF usually has near-zero extractable words and full-page image blocks.
    - Digital PDFs usually contain many text words/spans.
    """
    doc = _open_pdf(pdf_bytes)
    try:
        if doc.page_count == 0:
            raise PDFOperationError("PDF has no pages.")

        sampled_count = min(sample_pages, doc.page_count)
        total_words = 0
        scanned_like_pages = 0
        per_page: list[dict[str, object]] = []

        for page_index in range(sampled_count):
            page = doc[page_index]
            words = page.get_text("words")
            word_count = len(words)
            total_words += word_count

            page_area = max(1.0, float(page.rect.width * page.rect.height))
            image_area = 0.0
            image_blocks = 0
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                if block.get("type") == 1:
                    bbox = block.get("bbox", (0, 0, 0, 0))
                    if len(bbox) == 4:
                        image_blocks += 1
                        image_area += max(0.0, float((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])))

            image_coverage = min(1.0, image_area / page_area)
            page_scanned_like = (word_count <= 2 and image_coverage >= 0.65) or (
                word_count == 0 and image_blocks > 0
            )
            if page_scanned_like:
                scanned_like_pages += 1

            per_page.append(
                {
                    "page_number": page_index + 1,
                    "word_count": word_count,
                    "image_coverage": round(image_coverage, 3),
                }
            )

        strict_ratio = scanned_like_pages / sampled_count
        is_scanned = (total_words == 0) or (
            total_words <= max(2, sampled_count) and strict_ratio >= 0.8
        )

        message = (
            "Scanned PDF detected. Direct text editing is disabled for scanned files."
            if is_scanned
            else "Digital PDF detected. Direct text editing is enabled."
        )

        return {
            "is_scanned": is_scanned,
            "message": message,
            "page_count": doc.page_count,
            "sampled_pages": sampled_count,
            "total_words_in_sample": total_words,
            "scanned_like_pages": scanned_like_pages,
            "pages": per_page,
        }
    finally:
        doc.close()


def get_page_text_items(
    pdf_bytes: bytes,
    page_number: int,
    *,
    max_items: int = 2500,
) -> dict[str, object]:
    doc = _open_pdf(pdf_bytes)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise PDFOperationError(f"Page must be between 1 and {doc.page_count}.")

        page = doc[page_number - 1]
        page_dict = page.get_text("dict")
        items: list[dict[str, object]] = []

        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = (span.get("text") or "").strip()
                    if not text:
                        continue

                    bbox = span.get("bbox")
                    if not bbox or len(bbox) != 4:
                        continue
                    x0, y0, x1, y1 = [float(v) for v in bbox]
                    if x1 <= x0 or y1 <= y0:
                        continue

                    items.append(
                        {
                            "id": len(items) + 1,
                            "text": text,
                            "bbox": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)],
                            "font_size": round(float(span.get("size") or 12), 2),
                        }
                    )
                    if len(items) >= max_items:
                        break
                if len(items) >= max_items:
                    break
            if len(items) >= max_items:
                break

        return {
            "page_number": page_number,
            "page_width": round(float(page.rect.width), 3),
            "page_height": round(float(page.rect.height), 3),
            "text_items": items,
        }
    finally:
        doc.close()


def render_page_image_data_url(
    pdf_bytes: bytes,
    page_number: int,
    *,
    zoom: float = 1.45,
) -> str:
    if zoom < 0.8 or zoom > 3.0:
        raise PDFOperationError("Zoom must be between 0.8 and 3.0.")

    doc = _open_pdf(pdf_bytes)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise PDFOperationError(f"Page must be between 1 and {doc.page_count}.")
        page = doc[page_number - 1]
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        encoded = b64encode(pix.tobytes("png")).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    finally:
        doc.close()


def apply_click_text_edit(
    pdf_bytes: bytes,
    *,
    page_number: int,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    new_text: str,
    font_size: float | None = None,
) -> bytes:
    analysis = analyze_text_editability(pdf_bytes)
    if bool(analysis.get("is_scanned")):
        raise PDFOperationError(
            "This file looks scanned. Direct text editing is available only for digital PDFs."
        )

    if page_number < 1:
        raise PDFOperationError("Page must be >= 1.")
    if x1 <= x0 or y1 <= y0:
        raise PDFOperationError("Invalid text area. Ensure x1>x0 and y1>y0.")
    if font_size is not None and font_size <= 0:
        raise PDFOperationError("Font size must be positive.")

    doc = _open_pdf(pdf_bytes)
    try:
        if page_number > doc.page_count:
            raise PDFOperationError(f"Page must be between 1 and {doc.page_count}.")

        page = doc[page_number - 1]
        rect = fitz.Rect(float(x0), float(y0), float(x1), float(y1))
        rect = rect & page.rect
        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
            raise PDFOperationError("Selected text area is outside the page.")

        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()

        text = new_text or ""
        if text.strip():
            size = font_size if font_size is not None else max(6, min(18, rect.height * 0.8))
            target = fitz.Rect(rect.x0, rect.y0, rect.x1 + max(10, rect.width * 0.6), rect.y1 + 2)
            placed = page.insert_textbox(
                target,
                text,
                fontsize=size,
                color=(0, 0, 0),
                align=fitz.TEXT_ALIGN_LEFT,
                overlay=True,
            )
            if placed < 0:
                baseline_y = min(page.rect.y1 - 2, rect.y1 - 1)
                page.insert_text(
                    (rect.x0, baseline_y),
                    text,
                    fontsize=max(6, size - 1),
                    color=(0, 0, 0),
                    overlay=True,
                )

        return _save_pdf(doc)
    finally:
        doc.close()
