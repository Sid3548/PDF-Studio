"""Test package for PDF Studio."""

import warnings

# PyMuPDF / Pillow can emit non-fatal runtime warnings in short-lived tests.
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r"builtin type swigvarlink has no __module__ attribute",
)
