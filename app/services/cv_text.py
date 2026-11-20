"""Turns an uploaded CV file (PDF, DOCX, TXT) into clean plain text."""

import io
import re
import zipfile

from fastapi import HTTPException, status

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 10
MAX_TEXT_CHARS = 60_000
MIN_TEXT_CHARS = 60  # letters/digits only; below this a PDF is almost certainly a scan
MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024  # guards against zip bombs


def _reject(message: str, code: int = 422) -> HTTPException:
    return HTTPException(code, detail=message)


def clean_text(text: str) -> str:
    text = text.replace("\r", "").replace("\x00", "")
    text = re.sub(r"[  -​  　﻿]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise _reject("This PDF is password-protected. Remove the password and try again.")
        pages = [(page.extract_text() or "") for page in reader.pages[:MAX_PDF_PAGES]]
    except HTTPException:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, OSError, RecursionError):
        raise _reject("This PDF could not be opened — it may be damaged.") from None
    return "\n\n".join(pages)


def _docx_text(data: bytes) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_DOCX_UNCOMPRESSED:
                raise _reject("This DOCX file is too large to read.")
        doc = Document(io.BytesIO(data))
    except HTTPException:
        raise
    except Exception:
        raise _reject("This file is not a valid DOCX document, or it is damaged.") from None

    lines: list[str] = []

    def paragraph(p: Paragraph) -> None:
        t = p.text.strip()
        if not t:
            lines.append("")
            return
        style = (p.style.name if p.style is not None else "") or ""
        is_list = p._p.pPr is not None and p._p.pPr.numPr is not None or re.search(r"list|bullet", style, re.I)
        lines.append(f"• {t}" if is_list else t)

    # Body order matters (paragraphs and tables interleave), so walk the XML children.
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph(Paragraph(child, doc))
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                seen = []
                for cell in row.cells:
                    if cell not in seen:
                        seen.append(cell)
                for cell in seen:
                    for p in cell.paragraphs:
                        paragraph(p)
    return "\n".join(lines)


def _txt_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def extract_text(file_name: str, data: bytes) -> str:
    """Checks the type and size, extracts the text, and rejects empty or scanned files."""
    name = (file_name or "").lower()
    if len(data) > MAX_FILE_BYTES:
        raise _reject("The file is larger than 5 MB.", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    if not data:
        raise _reject("The file is empty.")
    if name.endswith(".doc"):
        raise _reject("Old .doc files can't be read. Open it in Word and use Save As → .docx or PDF.")

    if name.endswith(".pdf"):
        if not data.lstrip()[:5] == b"%PDF-":
            raise _reject("This file is not a valid PDF.")
        text = _pdf_text(data)
    elif name.endswith(".docx"):
        if data[:2] != b"PK":
            raise _reject("This file is not a valid DOCX document.")
        text = _docx_text(data)
    elif name.endswith(".txt"):
        if b"\x00" in data[:1024]:
            raise _reject("This file does not look like a text file.")
        text = _txt_text(data)
    else:
        raise _reject("Please choose a PDF, DOCX or TXT file.", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    text = clean_text(text)
    if len(re.sub(r"[^A-Za-z0-9]", "", text)) < MIN_TEXT_CHARS:
        raise _reject(
            "This PDF has almost no selectable text — it is probably a scanned image. "
            "Export your CV from Word/Google Docs as PDF, or upload the DOCX."
            if name.endswith(".pdf")
            else "We couldn't find readable text in this file."
        )
    return text[:MAX_TEXT_CHARS]
