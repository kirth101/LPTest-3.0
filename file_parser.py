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

    result.text = clean_text(result.text)
    if len(result.text) < 20:
        result.error = "This file doesn't contain enough text to build a quiz from."
        return result

    return result
