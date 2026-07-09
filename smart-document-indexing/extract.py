"""PDF text extraction with OCR and vision fallbacks for scanned documents."""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

import fitz  # pymupdf

logger = logging.getLogger(__name__)

MIN_TEXT_LENGTH = 50
PAGE_SEPARATOR = "\n\n--- Page {page} of {total} ---\n\n"
VISION_TRANSCRIBE_PROMPT = (
    "Transcribe all visible text from this clinical document page. "
    "Preserve names, dates, identifiers, and layout clues. "
    "Return plain text only."
)


def _meaningful_length(text: str) -> int:
    return len("".join(ch for ch in text if ch.isalnum()))


def _extract_with_pymupdf(file_path: Path) -> str:
    """Extract text per page using pymupdf."""
    parts: list[str] = []
    with fitz.open(file_path) as doc:
        total = len(doc)
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            parts.append(PAGE_SEPARATOR.format(page=i, total=total))
            parts.append(text)
    return "".join(parts).strip()


def _extract_with_tesseract(file_path: Path) -> str:
    """OCR each page with Tesseract (uses pymupdf rendering)."""
    import io

    import pytesseract
    from PIL import Image

    parts: list[str] = []
    with fitz.open(file_path) as doc:
        total = len(doc)
        for i, page in enumerate(doc, start=1):
            pixmap = page.get_pixmap(dpi=200)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            text = pytesseract.image_to_string(image).strip()
            parts.append(PAGE_SEPARATOR.format(page=i, total=total))
            parts.append(text)
    return "".join(parts).strip()


def _extract_with_vision(file_path: Path) -> str:
    """Transcribe scanned pages using GPT-4o vision when OCR is unavailable."""
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required for vision-based extraction of scanned PDFs."
        )

    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    client = OpenAI(api_key=api_key)
    parts: list[str] = []

    with fitz.open(file_path) as doc:
        total = len(doc)
        for i, page in enumerate(doc, start=1):
            pixmap = page.get_pixmap(dpi=150)
            image_b64 = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": VISION_TRANSCRIBE_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_b64}"
                                },
                            },
                        ],
                    }
                ],
            )
            text = (response.choices[0].message.content or "").strip()
            parts.append(PAGE_SEPARATOR.format(page=i, total=total))
            parts.append(text)

    return "".join(parts).strip()


def extract_text(file_path: str | Path) -> str:
    """
    Extract raw text from a PDF.

    Uses pymupdf first, then Tesseract OCR, then GPT-4o vision as final fallback.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")

    text = _extract_with_pymupdf(path)

    if _meaningful_length(text) < MIN_TEXT_LENGTH:
        logger.info("Low text yield for %s; attempting OCR fallback", path.name)
        try:
            text = _extract_with_tesseract(path)
        except Exception as exc:
            logger.warning("Tesseract OCR failed for %s: %s", path.name, exc)
            logger.info("Attempting vision-based extraction for %s", path.name)
            text = _extract_with_vision(path)

    if not text.strip():
        raise ValueError(f"No text could be extracted from {path.name}")

    return text
