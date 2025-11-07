import re
from typing import Dict, List
from ..utils import toklen
from .semantic import chunk as semantic_chunk

def chunk(text: str, options, mime: str = "", **kwargs) -> List[Dict]:
    tok = toklen(text)
    density = min(1.0, len(re.findall(r"[;:{}()\[\]]", text)) / max(1, tok))
    target, overlap = options.target_tokens, options.overlap_tokens

    if density > 0.03 or _is_code_mime(mime):
        target = int(target * 0.75); overlap = int(overlap * 0.6)
    elif _has_headings(text):
        target = int(target * 1.1);  overlap = int(overlap * 0.9)
    elif tok < 800:
        target = int(max(200, target * 0.8))

    class _Local:
        target_tokens = max(80, min(options.max_tokens, target))
        overlap_tokens = max(10, min(target - 10, overlap))
        max_tokens = options.max_tokens
        min_tokens = options.min_tokens
        embedder = options.embedder

    return semantic_chunk(text, _Local())

def _is_code_mime(mime: str) -> bool:
    return mime.startswith("text/x-") or mime in {"text/javascript","text/typescript","application/sql"}

def _has_headings(text: str) -> bool:
    return bool(re.search(r"^#{1,6}\s|^\d+(\.\d+)*[\.\)]\s+|^[A-Z0-9][A-Z0-9\s\-/&]{3,}$", text, flags=re.M))
