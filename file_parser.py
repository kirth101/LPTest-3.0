"""
file_parser.py
Handles file type detection, text extraction (.pdf, .docx, .doc, .txt),
and text cleaning.
"""

from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ExtractionResult:
    text: str = ""
    headings: list[tuple[str, int]] = field(default_factory=list)
    warning: Optional[str] = None
    error: Optional[str] = None
    # Populated instead of `text` for a PDF whose pages are scanned
    # photos with no real text layer (see _looks_like_real_text) --
    # each entry is one page's raw JPEG bytes, in page order. When this
    # is non-empty, the caller should generate questions from these
    # images directly (Gemini can read photographed/handwritten notes
    # far better than traditional OCR, especially highlighted/colored
    # handwriting) rather than treating this as a text-extraction
    # failure -- see generate_questions_from_images() in
    # question_generator.py.
    page_images: list[bytes] = field(default_factory=list)

def detect_file_type(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower().lstrip(".")
    if ext in ("pdf",):
        return "pdf"
    if ext in ("docx",):
        return "docx"
    if ext in ("doc",):
        return "doc"
    if ext in ("txt",):
        return "txt"
    return "unknown"

def _looks_like_real_text(page_texts: "list[str]") -> bool:
    """True if per-page extracted text looks like genuine document
    content rather than noise. Catches the common case of an
    image-based/scanned PDF (a photo of each page, no real embedded
    text layer) where pypdf can only pull out a scanning app's own
    watermark -- e.g. "CamScanner" on every page. That passes a bare
    "at least 20 characters total" check just fine (a short watermark
    repeated across several pages easily clears it) while being
    completely useless as quiz material -- worse, an AI asked to write
    questions "based on" that text may not refuse; it can free-associate
    from whatever word IS there (seen in practice: a PDF whose only
    extractable text was "CamScanner" produced a quiz about document
    *scanning* technology, having nothing to do with the actual
    photographed notes)."""
    non_empty = [t.strip() for t in page_texts if t.strip()]
    if not non_empty:
        return False
    avg_chars_per_page = sum(len(t) for t in non_empty) / len(non_empty)
    if avg_chars_per_page < 40:
        return False  # barely anything per page -- almost certainly just a watermark/stamp
    # The same short snippet repeated on nearly every page is itself a
    # watermark signature, even if that snippet is a little longer than
    # the bare character-count check alone would catch.
    unique_pages = set(non_empty)
    if len(unique_pages) <= 2 and len(non_empty) >= 4:
        return False
    return True


MAX_SCANNED_PAGES = 20  # keep proxy request payloads reasonable


def _largest_page_image(page) -> "bytes | None":
    """The biggest embedded image on a PDF page is, in practice, the
    actual scanned/photographed page content -- a scanning app's own
    logo/watermark (seen in the wild: CamScanner embeds a small,
    identical icon on every page alongside the real photo) is always
    much smaller. Picking the largest is a simple, reliable way to grab
    real content without hand-listing every scanning app's watermark
    filename/size."""
    try:
        images = list(page.images)
    except Exception:
        return None
    if not images:
        return None
    try:
        return max(images, key=lambda im: len(im.data)).data
    except Exception:
        return None


def _extract_pdf(filepath: str) -> ExtractionResult:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ExtractionResult(error="PDF support isn't installed. Run: pip install pypdf")

    result = ExtractionResult()
    try:
        reader = PdfReader(filepath)
    except Exception as e:
        return ExtractionResult(error=f"Couldn't open this PDF ({e}).")

    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:
            return ExtractionResult(error="This PDF is password-protected.")

    page_texts = []
    for page in reader.pages:
        try:
            page_texts.append(page.extract_text() or "")
        except Exception:
            page_texts.append("")

    if not _looks_like_real_text(page_texts):
        # No real text layer -- this is a scanned/photographed
        # document (or, sometimes, no images at all -- e.g. a truly
        # blank PDF). Try pulling out each page's own photo instead of
        # just giving up: an AI that can see images can read
        # handwritten/highlighted notes directly, no OCR app or extra
        # re-export step required from the user.
        page_images = []
        for page in reader.pages[:MAX_SCANNED_PAGES]:
            img_bytes = _largest_page_image(page)
            if img_bytes:
                page_images.append(img_bytes)

        if page_images:
            result.page_images = page_images
            if len(reader.pages) > MAX_SCANNED_PAGES:
                result.warning = (
                    f"This PDF has {len(reader.pages)} pages -- only the first "
                    f"{MAX_SCANNED_PAGES} were used to keep things fast."
                )
            return result

        sample = next((t.strip() for t in page_texts if t.strip()), "")
        hint = f' (the only text found was "{sample[:40]}", repeated across pages)' if sample else ""
        return ExtractionResult(
            error=(
                "This PDF looks like scanned or photographed pages, but LPTest "
                f"couldn't find any page images to read either{hint}. Try "
                "re-exporting it from your scanning app, or type the notes "
                "into a .txt or .docx file instead."
            )
        )

    result.text = "\n\n".join(page_texts)
    if not result.text.strip():
        result.error = "This PDF contains no extractable text or is image-based."
    return result

def _extract_docx(filepath: str) -> ExtractionResult:
    import zipfile
    import xml.etree.ElementTree as ET

    W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    try:
        with zipfile.ZipFile(filepath) as zf:
            with zf.open("word/document.xml") as f:
                tree = ET.parse(f)
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as e:
        return ExtractionResult(error=f"Couldn't open this Word document ({e}).")

    body = tree.getroot().find(f"{W_NS}body")
    if body is None:
        return ExtractionResult(error="This document has no readable body text.")

    result = ExtractionResult()
    parts = []
    offset = 0
    for para in body.findall(f"{W_NS}p"):
        text = "".join(node.text or "" for node in para.iter(f"{W_NS}t")).strip()
        if not text:
            continue
        parts.append(text)
        offset += len(text) + 1

    result.text = "\n".join(parts)
    if not result.text.strip():
        result.error = "This document has no readable text."
    return result

def _extract_doc(filepath: str) -> ExtractionResult:
    try:
        return _extract_docx(filepath)
    except Exception:
        pass
    return ExtractionResult(error="Legacy .doc files are not fully supported. Please save as .docx or .pdf.")

def _extract_txt(filepath: str) -> ExtractionResult:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            with open(filepath, "r", encoding=enc) as f:
                text = f.read()
            if not text.strip():
                return ExtractionResult(error="This text file appears to be empty.")
            return ExtractionResult(text=text)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return ExtractionResult(error="Couldn't decode text file encoding.")

EXTRACTORS = {
    "pdf": _extract_pdf,
    "docx": _extract_docx,
    "doc": _extract_doc,
    "txt": _extract_txt,
}

def clean_text(text: str) -> str:
    lines = text.splitlines()
    cleaned = [line.strip() for line in lines if line.strip()]
    text = "\n".join(cleaned)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def extract_text(filepath: str) -> ExtractionResult:
    if not os.path.exists(filepath):
        return ExtractionResult(error="File not found.")

    file_type = detect_file_type(filepath)
    extractor = EXTRACTORS.get(file_type)
    if extractor is None:
        return ExtractionResult(error=f"Unsupported file type '{file_type}'. Supported: PDF, DOCX, TXT.")

    result = extractor(filepath)
    if result.error:
        return result

    if result.page_images:
        # Scanned/photographed pages -- there's no text to clean or
        # length-check here; the caller generates questions straight
        # from the images instead (see generate_questions_from_images()
        # in question_generator.py).
        return result

    result.text = clean_text(result.text)
    if len(result.text) < 20:
        result.error = "This file doesn't contain enough text to build a quiz from."
        return result

    return result
