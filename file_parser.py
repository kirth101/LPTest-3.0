"""
file_parser.py
Handles Step 2-3 of the pipeline: detect file type, extract raw text,
clean it, and prepare it for chunking.

Supported formats: .pdf, .docx, .doc (best-effort), .txt
Designed modularly so more extractors (.pptx, .rtf) can be dropped in later
by adding a new EXTRACTORS entry.
"""

from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExtractionResult:
    text: str = ""
    headings: list[tuple[str, int]] = field(default_factory=list)  # (heading_text, char_offset)
    warning: Optional[str] = None      # non-fatal notice shown to the user
    error: Optional[str] = None        # fatal problem, extraction failed


def detect_file_type(filepath: str) -> str:
    """Detect file type from extension (MIME sniffing kept simple/offline)."""
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
            return ExtractionResult(error="This PDF is password-protected. Please remove the password and try again.")

    page_texts = []
    for page in reader.pages:
        try:
            page_texts.append(page.extract_text() or "")
        except Exception:
            page_texts.append("")

    total_chars = sum(len(t.strip()) for t in page_texts)
    avg_chars_per_page = total_chars / max(len(page_texts), 1)

    if total_chars == 0:
        return ExtractionResult(
            error="This looks like a scanned/image-based PDF with no extractable text. "
                  "Please run OCR on it (e.g. Adobe Acrobat, Google Drive OCR) and re-upload."
        )
    if avg_chars_per_page < 40 and len(page_texts) > 1:
        result.warning = (
            "This PDF has very little extractable text per page — it may be partially "
            "scanned. Some pages might be skipped. OCR is recommended for best results."
        )

    # Remove repeated header/footer lines (appear on most pages -> noise)
    line_counts: dict[str, int] = {}
    for t in page_texts:
        for line in set(l.strip() for l in t.splitlines() if l.strip()):
            line_counts[line] = line_counts.get(line, 0) + 1
    noisy_lines = {
        line for line, count in line_counts.items()
        if len(page_texts) > 2 and count >= max(3, int(len(page_texts) * 0.6)) and len(line) < 80
    }

    cleaned_pages = []
    for t in page_texts:
        kept = [l for l in t.splitlines() if l.strip() not in noisy_lines]
        cleaned_pages.append("\n".join(kept))

    result.text = "\n\n".join(cleaned_pages)
    return result


def _extract_docx(filepath: str) -> ExtractionResult:
    try:
        import docx
    except ImportError:
        return ExtractionResult(error="DOCX support isn't installed. Run: pip install python-docx")

    try:
        document = docx.Document(filepath)
    except Exception as e:
        return ExtractionResult(error=f"Couldn't open this Word document ({e}).")

    result = ExtractionResult()
    parts = []
    offset = 0
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = (para.style.name if para.style else "") or ""
        if style_name.lower().startswith("heading"):
            result.headings.append((text, offset))
        parts.append(text)
        offset += len(text) + 1

    result.text = "\n".join(parts)
    if not result.text.strip():
        result.error = "This document has no readable text (it may only contain images)."
    return result


def _extract_doc(filepath: str) -> ExtractionResult:
    """Legacy binary .doc — no reliable pure-Python offline reader.

    We try python-docx in case the file is mislabeled, otherwise fail
    loudly with a clear, actionable message rather than silently.
    """
    try:
        return _extract_docx(filepath)
    except Exception:
        pass
    return ExtractionResult(
        error="Legacy .doc files aren't fully supported offline. "
              "Please re-save the file as .docx or .pdf in Word and re-upload."
    )


def _extract_txt(filepath: str) -> ExtractionResult:
    encodings = ("utf-8", "utf-16", "latin-1")
    for enc in encodings:
        try:
            with open(filepath, "r", encoding=enc) as f:
                text = f.read()
            if not text.strip():
                return ExtractionResult(error="This text file appears to be empty.")
            return ExtractionResult(text=text)
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception as e:
            return ExtractionResult(error=f"Couldn't read this text file ({e}).")
    return ExtractionResult(error="Couldn't decode this text file's encoding.")


EXTRACTORS = {
    "pdf": _extract_pdf,
    "docx": _extract_docx,
    "doc": _extract_doc,
    "txt": _extract_txt,
}


def clean_text(text: str) -> str:
    """Strip page numbers, stray whitespace, and collapse blank lines."""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r"(page\s*)?\d{1,4}(\s*/\s*\d{1,4})?", stripped, flags=re.IGNORECASE):
            continue  # standalone page-number line
        cleaned.append(stripped)
    text = "\n".join(cleaned)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text(filepath: str) -> ExtractionResult:
    """Main entry point: Steps 1-3 of the parsing pipeline."""
    if not os.path.exists(filepath):
        return ExtractionResult(error="File not found.")

    file_type = detect_file_type(filepath)
    extractor = EXTRACTORS.get(file_type)
    if extractor is None:
        return ExtractionResult(
            error=f"Unsupported file type '{file_type or 'unknown'}'. "
                  f"Supported formats: PDF, DOCX, DOC, TXT."
        )

    result = extractor(filepath)
    if result.error:
        return result

    result.text = clean_text(result.text)
    if len(result.text) < 20:
        result.error = "This file doesn't contain enough text to build a quiz from."
        return result

    return result
