#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hierarchical chunking for .docx using heading levels.
- Parses paragraphs and tables in document order.
- Builds a heading-based hierarchy (Heading 1..9).
- Emits JSONL chunks with breadcrumb metadata.
- Splits long sections into sub-chunks with overlap.

Requires: python-docx
  pip install python-docx
"""

import re
import json
from pathlib import Path
from typing import List, Dict, Any, Iterator, Tuple, Union

from docx import Document
from docx.document import Document as _Document
from docx.text.paragraph import Paragraph
from docx.table import Table, _Row, _Cell
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P

# ========== Low-level iteration of block items in document order ==========

def iter_block_items(parent) -> Iterator[Union[Paragraph, Table]]:
    """
    Yield paragraphs and tables in document order for the given parent,
    using low-level oxml tree to maintain correct ordering.
    Supports Document, _Cell, and _Row as parents.
    """
    if isinstance(parent, _Document):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    elif isinstance(parent, _Row):
        parent_elm = parent._tr
    else:
        raise ValueError("Unsupported parent for iteration")

    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


# ========== Helpers for identifying headings and converting blocks ==========

_heading_re = re.compile(r"^Heading\s+([1-9])$", re.IGNORECASE)

def get_heading_level(p: Paragraph) -> int:
    """
    Return heading level 1..9 if paragraph style name matches 'Heading N', else 0.
    """
    try:
        style_name = p.style.name or ""
    except Exception:
        style_name = ""
    m = _heading_re.match(style_name.strip())
    if m:
        return int(m.group(1))
    return 0

def para_to_text(p: Paragraph) -> str:
    """
    Extract visible text from a paragraph, stripping excessive whitespace.
    """
    return " ".join(p.text.strip().split())

def table_to_markdown(t: Table, max_cols: int = 64) -> str:
    """
    Convert a Word table to simple GitHub-style Markdown.
    Uses the first row as header if all cells are non-empty, else creates generic headers.
    """
    rows = []
    for r in t.rows:
        row_vals = []
        for c in r.cells[:max_cols]:
            # Join runs inside each cell; python-docx merges grid spans implicitly.
            cell_text = " ".join(c.text.split())
            # Escape pipes to avoid breaking MD tables
            cell_text = cell_text.replace("|", "\\|")
            row_vals.append(cell_text)
        rows.append(row_vals)

    if not rows:
        return ""

    n_cols = max(len(r) for r in rows)
    rows = [r + [""] * (n_cols - len(r)) for r in rows]

    # Decide header
    header = rows[0]
    header_nonempty = all(cell != "" for cell in header)
    if header_nonempty:
        md = []
        md.append("| " + " | ".join(header) + " |")
        md.append("| " + " | ".join(["---"] * n_cols) + " |")
        for r in rows[1:]:
            md.append("| " + " | ".join(r) + " |")
        return "\n".join(md)
    else:
        # Generic header
        hdr = [f"Col {i+1}" for i in range(n_cols)]
        md = []
        md.append("| " + " | ".join(hdr) + " |")
        md.append("| " + " | ".join(["---"] * n_cols) + " |")
        for r in rows:
            md.append("| " + " | ".join(r) + " |")
        return "\n".join(md)


# ========== Tree construction from headings ==========

def build_hierarchy(doc: Document) -> Dict[str, Any]:
    """
    Build a tree from a .docx document based on heading levels.
    Each node: {title, level, blocks: List[Dict], children: List[node]}
    Blocks are dicts with type in {"paragraph", "table"} and text payload.
    """
    root = {"title": "", "level": 0, "blocks": [], "children": []}
    stack = [root]

    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            level = get_heading_level(block)
            if level > 0:
                title = para_to_text(block)
                # Pop until a parent level < current level is on top
                while stack and stack[-1]["level"] >= level:
                    stack.pop()
                node = {"title": title, "level": level, "blocks": [], "children": []}
                stack[-1]["children"].append(node)
                stack.append(node)
            else:
                txt = para_to_text(block)
                if txt:
                    stack[-1]["blocks"].append({"type": "paragraph", "text": txt})
        elif isinstance(block, Table):
            md = table_to_markdown(block)
            if md.strip():
                stack[-1]["blocks"].append({"type": "table", "text": md})

    return root


# ========== Chunking (flatten tree to JSONL) ==========

def split_text_with_overlap(text: str, max_chars: int, overlap: int) -> List[str]:
    """
    Simple character-based splitter with overlap between consecutive chunks.
    Splits on paragraph boundaries when possible, else hard-splits.
    """
    if max_chars <= 0:
        return [text]

    parts = []
    # Prefer split by double-newline if present, else by sentences/punctuation
    units = re.split(r"(\n\s*\n)|([.!?]\s+)", text)
    # Re-join tokens while respecting size
    buf = ""
    for u in units:
        if u is None:
            continue
        candidate = (buf + u) if buf else u
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                parts.append(buf.strip())
            # start new buffer with overlap from end of previous buf
            if overlap > 0 and parts:
                tail = parts[-1][-overlap:]
                buf = (tail + u)[:max_chars]
            else:
                buf = u[:max_chars]
    if buf.strip():
        parts.append(buf.strip())
    return [p for p in parts if p]

def node_breadcrumb(node: Dict[str, Any]) -> List[str]:
    """
    Collect titles from root to this node (excluding root which has empty title).
    """
    crumb = []
    cur = node
    while cur is not None:
        if cur.get("title"):
            crumb.append(cur["title"])
        cur = cur.get("_parent")
    return list(reversed(crumb))

def attach_parents(node: Dict[str, Any], parent=None):
    node["_parent"] = parent
    for ch in node.get("children", []):
        attach_parents(ch, node)

def flatten_to_chunks(
    root: Dict[str, Any],
    doc_id: str,
    max_chars: int = 1200,
    overlap: int = 120,
) -> List[Dict[str, Any]]:
    """
    Produce a flat list of chunk dicts with breadcrumb metadata.
    Each chunk:
      - id: f"{doc_id}::N"
      - doc_id
      - path: list[str] of headings
      - level: heading depth (0 for root content)
      - text: chunk content
      - block_types: set of block types included
    """
    attach_parents(root, None)
    chunks = []
    counter = 0

    def emit_chunk(path: List[str], level: int, text: str, block_types: List[str]):
        nonlocal counter
        counter += 1
        chunks.append({
            "id": f"{doc_id}::{counter}",
            "doc_id": doc_id,
            "path": path,
            "level": level,
            "text": text,
            "block_types": sorted(set(block_types)),
        })

    def process_node(node: Dict[str, Any]):
        path = node_breadcrumb(node)
        level = node.get("level", 0)
        # Combine local blocks into one text (with clear separators)
        texts = []
        types = []
        for b in node.get("blocks", []):
            types.append(b["type"])
            if b["type"] == "paragraph":
                texts.append(b["text"])
            elif b["type"] == "table":
                texts.append("\n" + b["text"] + "\n")
        combined = "\n\n".join(t for t in texts if t.strip())

        if combined.strip():
            parts = split_text_with_overlap(combined, max_chars, overlap)
            for p in parts:
                emit_chunk(path, level, p, types if types else ["paragraph"])

        for ch in node.get("children", []):
            process_node(ch)

    process_node(root)
    return chunks


# ========== Public API ==========

def chunk_docx_hierarchical(
    filepath: Union[str, Path],
    max_chars: int = 1200,
    overlap: int = 120,
) -> List[Dict[str, Any]]:
    """
    Load a .docx file, build heading hierarchy, and return flattened chunks.
    """
    doc = Document(str(filepath))
    tree = build_hierarchy(doc)
    doc_id = Path(filepath).stem
    chunks_dict = flatten_to_chunks(tree, doc_id=doc_id, max_chars=max_chars, overlap=overlap)
    chunk_list = []
    for chunk in chunks_dict:
        chunk_text = chunk['text']
        chunk_list.append(chunk_text)
    return chunk_list


def save_chunks_jsonl(chunks: List[Dict[str, Any]], outpath: Union[str, Path]):
    with open(outpath, "w", encoding="utf-8") as f:
        for ch in chunks:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")


# ========== CLI ==========

# if __name__ == "__main__":


#     import argparse

#     ap = argparse.ArgumentParser(description="Hierarchical chunking for .docx")
#     ap.add_argument("docx_path", type=str, help="Path to input .docx")
#     ap.add_argument("--max-chars", type=int, default=1200, help="Max characters per chunk")
#     ap.add_argument("--overlap", type=int, default=120, help="Character overlap between chunks")
#     ap.add_argument("--out", type=str, default="", help="Output JSONL path (default: <stem>.chunks.jsonl)")
#     args = ap.parse_args()

#     in_path = Path(args.docx_path)
#     out_path = Path(args.out) if args.out else in_path.with_suffix(".chunks.jsonl")

    # chunks = chunk_docx_hierarchical(doc_path, max_chars=args.max_chars, overlap=args.overlap)
    # print(chunks)

    # print(f"Chunks written: {out_path} (count={len(chunks)})")


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# """
# Hierarchical chunking for .docx using heading levels (Heading 1..9).
# - Parses paragraphs and tables in document order (CT_P / CT_Tbl).
# - Builds a nested tree following the heading structure.
# - Flattens to size-bounded chunks with overlap and breadcrumb path metadata.
# - Converts tables to Markdown for structured retention.

# Install:
#   pip install python-docx
# """

# import re
# import json
# from pathlib import Path
# from typing import List, Dict, Any, Iterator, Union, Optional

# from docx import Document
# from docx.document import Document as _Document
# from docx.text.paragraph import Paragraph
# from docx.table import Table, _Row, _Cell
# from docx.oxml.text.paragraph import CT_P
# from docx.oxml.table import CT_Tbl

# # -------------------- Iteration in true document order --------------------

# def iter_block_items(parent) -> Iterator[Union[Paragraph, Table]]:
#     """
#     Yield Paragraph and Table in the order they appear, using oxml tree.
#     Supports Document, _Cell, and _Row parents.
#     """
#     if isinstance(parent, _Document):
#         parent_elm = parent.element.body
#     elif isinstance(parent, _Cell):
#         parent_elm = parent._tc
#     elif isinstance(parent, _Row):
#         parent_elm = parent._tr
#     else:
#         raise ValueError("Unsupported parent for iteration")
#     for child in parent_elm.iterchildren():
#         if isinstance(child, CT_P):
#             yield Paragraph(child, parent)
#         elif isinstance(child, CT_Tbl):
#             yield Table(child, parent)

# # -------------------- Helpers: headings, text, tables --------------------

# _heading_re = re.compile(r"^Heading\s+([1-9])$", re.IGNORECASE)

# def get_heading_level(p: Paragraph) -> int:
#     try:
#         name = p.style.name or ""
#     except Exception:
#         name = ""
#     m = _heading_re.match(name.strip())
#     return int(m.group(1)) if m else 0

# def para_to_text(p: Paragraph) -> str:
#     return " ".join(p.text.strip().split())

# def table_to_markdown(t: Table, max_cols: int = 64) -> str:
#     rows = []
#     for r in t.rows:
#         row_vals = []
#         for c in r.cells[:max_cols]:
#             txt = " ".join(c.text.split()).replace("|", "\\|")
#             row_vals.append(txt)
#         rows.append(row_vals)
#     if not rows:
#         return ""
#     n_cols = max(len(r) for r in rows)
#     rows = [r + [""] * (n_cols - len(r)) for r in rows]
#     header = rows[0]
#     header_nonempty = all(cell != "" for cell in header)
#     md_lines = []
#     if header_nonempty:
#         md_lines.append("| " + " | ".join(header) + " |")
#         md_lines.append("| " + " | ".join(["---"] * n_cols) + " |")
#         for r in rows[1:]:
#             md_lines.append("| " + " | ".join(r) + " |")
#     else:
#         hdr = [f"Col {i+1}" for i in range(n_cols)]
#         md_lines.append("| " + " | ".join(hdr) + " |")
#         md_lines.append("| " + " | ".join(["---"] * n_cols) + " |")
#         for r in rows:
#             md_lines.append("| " + " | ".join(r) + " |")
#     return "\n".join(md_lines)

# # -------------------- Build heading-based tree --------------------

# def build_hierarchy(doc: Document) -> Dict[str, Any]:
#     """
#     Create a tree where each node holds: {title, level, blocks, children}.
#     blocks: list of {"type": "paragraph"|"table", "text": str}
#     """
#     root = {"title": "", "level": 0, "blocks": [], "children": []}
#     stack = [root]

#     for block in iter_block_items(doc):
#         if isinstance(block, Paragraph):
#             level = get_heading_level(block)
#             if level > 0:
#                 title = para_to_text(block)
#                 while stack and stack[-1]["level"] >= level:
#                     stack.pop()
#                 node = {"title": title, "level": level, "blocks": [], "children": []}
#                 stack[-1]["children"].append(node)
#                 stack.append(node)
#             else:
#                 txt = para_to_text(block)
#                 if txt:
#                     stack[-1]["blocks"].append({"type": "paragraph", "text": txt})
#         elif isinstance(block, Table):
#             md = table_to_markdown(block)
#             if md.strip():
#                 stack[-1]["blocks"].append({"type": "table", "text": md})

#     return root

# # -------------------- Flatten to chunks --------------------

# def split_text_with_overlap(text: str, max_chars: int, overlap: int) -> List[str]:
#     """
#     Split text into chunks up to max_chars with character overlap.
#     Prefer paragraph/sentence boundaries when possible.
#     """
#     if max_chars <= 0:
#         return [text]
#     parts: List[str] = []
#     # Split on double newline or punctuation spacing
#     tokens = re.split(r"(\n\s*\n)|([.!?]\s+)", text)
#     buf = ""
#     for tok in tokens:
#         if tok is None:
#             continue
#         candidate = (buf + tok) if buf else tok
#         if len(candidate) <= max_chars:
#             buf = candidate
#         else:
#             if buf.strip():
#                 parts.append(buf.strip())
#             if overlap > 0 and parts:
#                 tail = parts[-1][-overlap:]
#                 buf = (tail + tok)[:max_chars]
#             else:
#                 buf = tok[:max_chars]
#     if buf.strip():
#         parts.append(buf.strip())
#     return [p for p in parts if p]

# def attach_parents(node: Dict[str, Any], parent: Optional[Dict[str, Any]] = None):
#     node["_parent"] = parent
#     for ch in node.get("children", []):
#         attach_parents(ch, node)

# def node_breadcrumb(node: Dict[str, Any]) -> List[str]:
#     crumb: List[str] = []
#     cur = node
#     while cur is not None:
#         if cur.get("title"):
#             crumb.append(cur["title"])
#         cur = cur.get("_parent")
#     return list(reversed(crumb))

# def flatten_to_chunks(
#     root: Dict[str, Any],
#     doc_id: str,
#     max_chars: int = 1200,
#     overlap: int = 120,
# ) -> List[Dict[str, Any]]:
#     """
#     Flatten the tree to a list of chunks with:
#       id, doc_id, path, level, text, block_types
#     """
#     attach_parents(root, None)
#     chunks: List[Dict[str, Any]] = []
#     counter = 0

#     def emit(path: List[str], level: int, text: str, block_types: List[str]):
#         nonlocal counter
#         counter += 1
#         chunks.append({
#             "id": f"{doc_id}::{counter}",
#             "doc_id": doc_id,
#             "path": path,
#             "level": level,
#             "text": text,
#             "block_types": sorted(set(block_types)),
#         })

#     def process(node: Dict[str, Any]):
#         path = node_breadcrumb(node)
#         level = node.get("level", 0)
#         texts: List[str] = []
#         types: List[str] = []
#         for b in node.get("blocks", []):
#             types.append(b["type"])
#             if b["type"] == "paragraph":
#                 texts.append(b["text"])
#             elif b["type"] == "table":
#                 texts.append("\n" + b["text"] + "\n")
#         combined = "\n\n".join(t for t in texts if t.strip())

#         if combined.strip():
#             for part in split_text_with_overlap(combined, max_chars=max_chars, overlap=overlap):
#                 emit(path, level, part, types if types else ["paragraph"])

#         for ch in node.get("children", []):
#             process(ch)

#     process(root)
#     return chunks

# # -------------------- Public API and CLI --------------------

# def chunk_docx_hierarchical(
#     filepath: Union[str, Path],
#     max_chars: int = 1200,
#     overlap: int = 120,
# ) -> List[Dict[str, Any]]:
#     doc = Document(str(filepath))
#     tree = build_hierarchy(doc)
#     doc_id = Path(filepath).stem
#     return flatten_to_chunks(tree, doc_id=doc_id, max_chars=max_chars, overlap=overlap)

# def save_chunks_jsonl(chunks: List[Dict[str, Any]], outpath: Union[str, Path]):
#     out = Path(outpath)
#     with open(out, "w", encoding="utf-8") as f:
#         for ch in chunks:
#             f.write(json.dumps(ch, ensure_ascii=False) + "\n")

# if __name__ == "__main__":
#     import argparse
#     ap = argparse.ArgumentParser(description="Hierarchical chunking for .docx (headings + tables)")
#     ap.add_argument("docx_path", type=str, help="Path to input .docx")
#     ap.add_argument("--max-chars", type=int, default=1200, help="Max characters per chunk")
#     ap.add_argument("--overlap", type=int, default=120, help="Character overlap between chunks")
#     ap.add_argument("--out", type=str, default="", help="Output JSONL (default: <stem>.chunks.jsonl)")
#     args = ap.parse_args()

#     in_path = Path(args.docx_path)
#     out_path = Path(args.out) if args.out else in_path.with_suffix(".chunks.jsonl")

#     chunks = chunk_docx_hierarchical(in_path, max_chars=args.max_chars, overlap=args.overlap)
#     print(chunks[5])
#     # save_chunks_jsonl(chunks, out_path)
#     # print(f"Wrote {len(chunks)} chunks -> {out_path}")
