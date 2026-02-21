from __future__ import annotations

"""Flask entrypoint and API routes for PDF Studio.

This module exposes a single Flask app with:
- Static frontend hosting from /static
- JSON API routes under /api/*
- Centralized input parsing and error handling

The app is intentionally self-contained so it can run on any machine with
`pip install -r requirements.txt`.
"""

import io
import logging
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from app import pdf_ops

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
LOGGER = logging.getLogger("pdf_studio")


def _download(data: bytes, filename: str, media_type: str):
    """Return a bytes payload as a download response."""
    output = io.BytesIO(data)
    output.seek(0)
    return send_file(output, mimetype=media_type, as_attachment=True, download_name=filename)


def _hex_to_rgb(color_hex: str) -> tuple[float, float, float]:
    """Convert #RRGGBB to tuple of floats in [0..1]."""
    value = (color_hex or "").strip().lstrip("#")
    if len(value) != 6:
        raise pdf_ops.PDFOperationError("Color must be a 6-digit hex value like #000000.")
    try:
        return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError as exc:
        raise pdf_ops.PDFOperationError("Invalid hex color.") from exc


def _form_required(name: str) -> str:
    """Read a required form field and ensure it is not blank."""
    value = request.form.get(name)
    if value is None or value.strip() == "":
        raise pdf_ops.PDFOperationError(f"Missing required form field: {name}")
    return value


def _form_optional(name: str) -> str | None:
    """Read an optional form field; return None for blank values."""
    value = request.form.get(name)
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed if trimmed != "" else None


def _form_float(name: str, default: float | None = None) -> float:
    """Read a float form field with optional default."""
    raw = request.form.get(name)
    if raw is None:
        if default is None:
            raise pdf_ops.PDFOperationError(f"Missing required form field: {name}")
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise pdf_ops.PDFOperationError(f"Invalid number for {name}: {raw}") from exc


def _form_int(name: str, default: int | None = None) -> int:
    """Read an integer form field with optional default."""
    raw = request.form.get(name)
    if raw is None:
        if default is None:
            raise pdf_ops.PDFOperationError(f"Missing required form field: {name}")
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise pdf_ops.PDFOperationError(f"Invalid integer for {name}: {raw}") from exc


def _form_bool(name: str, default: bool) -> bool:
    """Parse a boolean from string values used by HTML forms."""
    raw = request.form.get(name)
    if raw is None:
        return default

    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise pdf_ops.PDFOperationError(f"Invalid boolean for {name}: {raw}")


def _uploaded_file_bytes(name: str = "file") -> bytes:
    """Read bytes from a single uploaded file field."""
    file = request.files.get(name)
    if file is None:
        raise pdf_ops.PDFOperationError(f"Missing uploaded file: {name}")
    payload = file.read()
    if not payload:
        raise pdf_ops.PDFOperationError(f"Uploaded file is empty: {name}")
    return payload


def _uploaded_many(name: str) -> list[bytes]:
    """Read non-empty payloads from a multi-file upload field."""
    files = request.files.getlist(name)
    if not files:
        raise pdf_ops.PDFOperationError(f"Missing uploaded files: {name}")

    payloads: list[bytes] = []
    for file in files:
        content = file.read()
        if content:
            payloads.append(content)

    if not payloads:
        raise pdf_ops.PDFOperationError(f"Uploaded files are empty: {name}")

    return payloads


def create_app() -> Flask:
    """Create and configure Flask app instance."""
    # Disable Flask's implicit static route so our explicit SPA/static handler
    # controls all non-API paths consistently.
    flask_app = Flask(__name__, static_folder=None)

    # Keep uploads bounded for predictable memory usage.
    flask_app.config.setdefault("MAX_CONTENT_LENGTH", 250 * 1024 * 1024)

    @flask_app.errorhandler(pdf_ops.PDFOperationError)
    def handle_pdf_error(exc: pdf_ops.PDFOperationError):
        return jsonify({"error": str(exc)}), 400

    @flask_app.errorhandler(RequestEntityTooLarge)
    def handle_large_file(_: RequestEntityTooLarge):
        return jsonify({"error": "Upload too large. Max file size is 250 MB."}), 413

    @flask_app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception):
        # Preserve framework-managed HTTP errors (404/405/etc.).
        if isinstance(exc, HTTPException):
            return exc
        LOGGER.exception("Unhandled server error", exc_info=exc)
        return jsonify({"error": "Internal server error."}), 500

    @flask_app.get("/")
    def root():
        return send_from_directory(STATIC_DIR, "index.html")

    @flask_app.get("/<path:path>")
    def static_files(path: str):
        """Serve static files and fallback to index for client-side routes."""
        # Never return index.html for unknown API paths.
        if path.startswith("api/"):
            return jsonify({"error": "Not found"}), 404

        full_path = STATIC_DIR / path
        if full_path.exists() and full_path.is_file():
            return send_from_directory(STATIC_DIR, path)
        return send_from_directory(STATIC_DIR, "index.html")

    @flask_app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    @flask_app.post("/api/rotate")
    def rotate_pdf():
        payload = _uploaded_file_bytes("file")
        pages = _form_optional("pages")
        angle = _form_int("angle")
        output = pdf_ops.rotate_pages(payload, pages, angle)
        return _download(output, "rotated.pdf", "application/pdf")

    @flask_app.post("/api/reorder")
    def reorder_pdf():
        payload = _uploaded_file_bytes("file")
        order = _form_required("order")
        output = pdf_ops.reorder_pages(payload, order)
        return _download(output, "reordered.pdf", "application/pdf")

    @flask_app.post("/api/reverse")
    def reverse_pdf():
        payload = _uploaded_file_bytes("file")
        output = pdf_ops.reverse_pages(payload)
        return _download(output, "reversed.pdf", "application/pdf")

    @flask_app.post("/api/duplicate-pages")
    def duplicate_pdf_pages():
        payload = _uploaded_file_bytes("file")
        pages = _form_required("pages")
        copies = _form_int("copies", default=1)
        output = pdf_ops.duplicate_pages(payload, pages, copies)
        return _download(output, "duplicated-pages.pdf", "application/pdf")

    @flask_app.post("/api/delete-pages")
    def delete_pdf_pages():
        payload = _uploaded_file_bytes("file")
        pages = _form_required("pages")
        output = pdf_ops.delete_pages(payload, pages)
        return _download(output, "deleted-pages.pdf", "application/pdf")

    @flask_app.post("/api/extract-pages")
    def extract_pdf_pages():
        payload = _uploaded_file_bytes("file")
        pages = _form_required("pages")
        output = pdf_ops.extract_pages(payload, pages)
        return _download(output, "extracted-pages.pdf", "application/pdf")

    @flask_app.post("/api/split")
    def split_pdf():
        payload = _uploaded_file_bytes("file")
        groups = _form_optional("groups")
        output = pdf_ops.split_pdf(payload, groups)
        return _download(output, "split.zip", "application/zip")

    @flask_app.post("/api/merge")
    def merge_pdf():
        payloads = _uploaded_many("files")
        output = pdf_ops.merge_pdfs(payloads)
        return _download(output, "merged.pdf", "application/pdf")

    @flask_app.post("/api/add-text")
    def add_text():
        payload = _uploaded_file_bytes("file")
        page = _form_int("page")
        text = _form_required("text")
        x = _form_float("x")
        y = _form_float("y")
        font_size = _form_float("font_size", default=12)
        color = request.form.get("color", "#000000")

        output = pdf_ops.add_text(payload, page, text, x, y, font_size, _hex_to_rgb(color))
        return _download(output, "text-added.pdf", "application/pdf")

    @flask_app.post("/api/replace-text")
    def replace_text():
        payload = _uploaded_file_bytes("file")
        search_text = _form_required("search_text")
        replace_text_value = _form_required("replace_text")

        output, replacements = pdf_ops.replace_text(payload, search_text, replace_text_value)
        response = _download(output, "text-replaced.pdf", "application/pdf")
        response.headers["X-Replacements"] = str(replacements)
        response.headers["Access-Control-Expose-Headers"] = "X-Replacements"
        return response

    @flask_app.post("/api/watermark")
    def watermark_pdf():
        payload = _uploaded_file_bytes("file")
        text = _form_required("text")
        font_size = _form_float("font_size", default=32)
        density = _form_int("density", default=3)
        shade = _form_float("shade", default=0.75)

        output = pdf_ops.watermark_text(payload, text, font_size, density, shade)
        return _download(output, "watermarked.pdf", "application/pdf")

    @flask_app.post("/api/page-numbers")
    def page_numbers():
        payload = _uploaded_file_bytes("file")
        position = request.form.get("position", "bottom-right")
        font_size = _form_float("font_size", default=12)

        output = pdf_ops.add_page_numbers(payload, position, font_size)
        return _download(output, "page-numbered.pdf", "application/pdf")

    @flask_app.post("/api/pdf-to-images")
    def pdf_to_images():
        payload = _uploaded_file_bytes("file")
        fmt = request.form.get("fmt", "png")
        dpi = _form_int("dpi", default=150)
        pages = _form_optional("pages")

        output = pdf_ops.pdf_to_images_zip(payload, fmt, dpi, pages)
        return _download(output, "pdf-images.zip", "application/zip")

    @flask_app.post("/api/images-to-pdf")
    def images_to_pdf():
        payloads = _uploaded_many("files")
        output = pdf_ops.images_to_pdf(payloads)
        return _download(output, "images-to-pdf.pdf", "application/pdf")

    @flask_app.post("/api/encrypt")
    def encrypt_pdf():
        payload = _uploaded_file_bytes("file")
        user_password = _form_required("user_password")
        owner_password = _form_optional("owner_password")
        allow_print = _form_bool("allow_print", default=True)
        allow_copy = _form_bool("allow_copy", default=False)

        output = pdf_ops.encrypt_pdf(payload, user_password, owner_password, allow_print, allow_copy)
        return _download(output, "encrypted.pdf", "application/pdf")

    @flask_app.post("/api/decrypt")
    def decrypt_pdf():
        payload = _uploaded_file_bytes("file")
        password = _form_required("password")

        output = pdf_ops.decrypt_pdf(payload, password)
        return _download(output, "decrypted.pdf", "application/pdf")

    @flask_app.post("/api/metadata")
    def metadata_pdf():
        payload = _uploaded_file_bytes("file")

        output = pdf_ops.update_metadata(
            payload,
            title=_form_optional("title"),
            author=_form_optional("author"),
            subject=_form_optional("subject"),
            keywords=_form_optional("keywords"),
        )
        return _download(output, "metadata-updated.pdf", "application/pdf")

    @flask_app.post("/api/crop")
    def crop_pdf():
        payload = _uploaded_file_bytes("file")
        pages = _form_optional("pages")
        x0 = _form_float("x0")
        y0 = _form_float("y0")
        x1 = _form_float("x1")
        y1 = _form_float("y1")

        output = pdf_ops.crop_pages(payload, pages, x0, y0, x1, y1)
        return _download(output, "cropped.pdf", "application/pdf")

    @flask_app.post("/api/optimize")
    def optimize_pdf():
        payload = _uploaded_file_bytes("file")
        output = pdf_ops.optimize_pdf(payload)
        return _download(output, "optimized.pdf", "application/pdf")

    @flask_app.post("/api/text-editor/analyze")
    def text_editor_analyze():
        payload = _uploaded_file_bytes("file")
        return jsonify(pdf_ops.analyze_text_editability(payload))

    @flask_app.post("/api/text-editor/page")
    def text_editor_page():
        payload = _uploaded_file_bytes("file")
        page = _form_int("page")
        zoom = _form_float("zoom", default=1.45)

        analysis = pdf_ops.analyze_text_editability(payload)
        page_data = pdf_ops.get_page_text_items(payload, page)
        page_data["image_data_url"] = pdf_ops.render_page_image_data_url(payload, page, zoom=zoom)
        page_data["is_scanned"] = analysis["is_scanned"]
        page_data["scan_message"] = analysis["message"]
        return jsonify(page_data)

    @flask_app.post("/api/text-editor/apply")
    def text_editor_apply():
        payload = _uploaded_file_bytes("file")
        page = _form_int("page")
        x0 = _form_float("x0")
        y0 = _form_float("y0")
        x1 = _form_float("x1")
        y1 = _form_float("y1")
        new_text = request.form.get("new_text", "")

        font_size_raw = request.form.get("font_size")
        font_size = float(font_size_raw) if font_size_raw not in (None, "") else None

        output = pdf_ops.apply_click_text_edit(
            payload,
            page_number=page,
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            new_text=new_text,
            font_size=font_size,
        )
        return _download(output, "text-edited.pdf", "application/pdf")

    @flask_app.post("/api/text-editor/add")
    def text_editor_add():
        payload = _uploaded_file_bytes("file")
        page = _form_int("page")
        x = _form_float("x")
        y = _form_float("y")
        text = _form_required("text")
        font_size = _form_float("font_size", default=12)
        color = request.form.get("color", "#000000")

        output = pdf_ops.add_text_at_point(
            payload,
            page_number=page,
            x=x,
            y=y,
            text=text,
            font_size=font_size,
            color=_hex_to_rgb(color),
        )
        return _download(output, "text-added-interactive.pdf", "application/pdf")

    return flask_app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
