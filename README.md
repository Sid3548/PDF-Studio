# PDF Studio

A local full-featured PDF editor web app.

## Features

- Page operations: rotate selected pages, reorder pages, reverse page order, duplicate selected pages, delete pages, extract pages, split PDF, merge PDFs
- Text tools: interactive visual editor (click text to edit, add text by clicking anywhere, page arrows, digital PDFs only), add text at coordinates, find & replace text, add tiled watermark, add page numbers
- Layout tools: crop selected pages, optimize/compress PDF
- Conversion: PDF to images (PNG/JPG ZIP), images to PDF
- Security: encrypt PDF, decrypt PDF
- Metadata: update title, author, subject, keywords
- UX: labeled card-based homepage (Smallpdf-style flow), single-screen workspace, popup editing windows, before/after preview in each popup, result chaining (`Use Result as Source`), and scanned-file warning/lock in visual text editor

## Tech Stack

- Backend: Flask + PyMuPDF + Pillow
- Frontend: Vanilla HTML/CSS/JS

## Run Locally

```bash
cd /Users/jsidharth/Desktop/ideas/pdf-studio
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_flask.py --dev --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000)

## Run As Portable App (Any Computer On Network)

```bash
cd /Users/jsidharth/Desktop/ideas/pdf-studio
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_flask.py --host 0.0.0.0 --port 8000
```

Then open from another computer on same network using:

`http://<your-computer-ip>:8000`

## Run Tests

```bash
cd /Users/jsidharth/Desktop/ideas/pdf-studio
source .venv/bin/activate
PYTHONWARNINGS='error::ResourceWarning' python -m unittest discover -s tests -v
```

## Notes

- Page numbers in the UI are 1-based.
- Coordinates for `Add Text` and `Crop` are PDF points.
- Find & Replace works best on text-based PDFs; scanned PDFs usually need OCR first.
