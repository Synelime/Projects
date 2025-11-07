# readers.py
import os, re, csv
from typing import List

_HAS_PDF = False
_HAS_DOCX = False
_HAS_PANDAS = False

try:
    import pdfplumber
    _HAS_PDF = True
except Exception:
    pass

try:
    from docx import Document
    _HAS_DOCX = True
except Exception:
    pass

try:
    import pandas as pd
    _HAS_PANDAS = True
except Exception:
    pass


def guess_mime(path: str) -> str:
    ext = os.path.splitext(path.lower())[1]
    return {
         ".py": "text/x-python",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain", ".md": "text/markdown", ".markdown": "text/markdown",
        ".html": "text/html", ".htm": "text/html", ".json": "application/json",
        ".csv": "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls":  "application/vnd.ms-excel",
        ".py": "text/x-python", ".js": "text/javascript", ".ts": "text/typescript",
        ".java": "text/x-java-source", ".cs": "text/x-csharp", ".cpp": "text/x-c++src",
        ".c": "text/x-c", ".go": "text/x-go", ".rb": "text/x-ruby", ".php": "text/x-php",
        ".rs": "text/x-rustsrc", ".sql": "application/sql",
    }.get(ext, "application/octet-stream")


def _rows_to_pipe(rows: List[List[str]]) -> str:
    out_lines: List[str] = []
    for r in rows:
        # normalize cells and collapse whitespace
        cells = [(" " + (str(c) if c is not None else "").strip() + " ") for c in r]
        out_lines.append(" | ".join(cells))
    return "\n".join(out_lines)


def _read_csv_pipe(path: str) -> str:
    # Stream as CSV and emit pipe-delimited lines
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample)
        except Exception:
            dialect = csv.excel
        reader = csv.reader(f, dialect)
        rows = list(reader)
    return _rows_to_pipe(rows)


def _read_xlsx_pipe(path: str) -> str:
    if not _HAS_PANDAS:
        raise RuntimeError("Excel support requires pandas (pip install pandas openpyxl).")
    # Read every sheet -> section header + pipe table
    book = pd.read_excel(path, sheet_name=None, dtype=str)  # dict of DataFrame
    parts: List[str] = []
    for sheet_name, df in book.items():
        df = df.fillna("")  # strings only
        parts.append(f"## Sheet: {sheet_name}")
        # include header
        rows = [list(df.columns)] + df.values.tolist()
        parts.append(_rows_to_pipe(rows))
        parts.append("")  # blank line between sheets
    return "\n".join(parts).strip()


def read_file_text(path: str, mime: str) -> str:
    # PDFs
    if mime == "application/pdf":
        if not _HAS_PDF:
            raise RuntimeError("pdfplumber not installed")
        pages: List[str] = []
        with pdfplumber.open(path) as pdf:
            for p in pdf.pages:
                try:
                    pages.append(p.extract_text() or "")
                except Exception:
                    pages.append("")
        return "\n\n".join(pages).strip()

    # DOCX
    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        if not _HAS_DOCX:
            raise RuntimeError("python-docx not installed")
        doc = Document(path)
        parts: List[str] = []
        for para in doc.paragraphs:
            t = (para.text or "").strip()
            if t:
                parts.append(t)
        for table in doc.tables:
            for row in table.rows:
                cells = [(cell.text or "").strip() for cell in row.cells]
                if any(cells):
                    parts.append(" | ".join([c for c in cells if c]))
        out = "\n\n".join(parts).strip()
        return re.sub(r"\n{3,}", "\n\n", out)

    # CSV
    if mime == "text/csv":
        return _read_csv_pipe(path)

    # Excel
    if mime in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    }:
        return _read_xlsx_pipe(path)

    # Plain text-like fallback
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()
