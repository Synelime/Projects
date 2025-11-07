import re
from typing import Dict, List
from ..utils import mk_chunk, toklen, simple_tokenize, slice_tokens

BOUNDARY = re.compile(
    r"(?m)^(?:\s*(def|class)\s+\w+\s*\(|"                   # Python
    r"\s*(export\s+)?(function|class)\s+\w+\s*\(|"          # JS/TS
    r"\s*(public|private|protected)?\s*(class|interface)\s+\w+|"  # Java/C#
    r"\s*(?:void|int|float|double|char|bool)\s+\w+\s*\(|"   # C/C++
    r"\s*CREATE\s+(?:FUNCTION|PROCEDURE|VIEW)\b|\s*BEGIN\b)"# SQL-ish
)

def chunk(text: str, options, **kwargs) -> List[Dict]:
    parts = BOUNDARY.split(text)
    if len(parts) <= 1:
        from .fixed_sliding import chunk as fixed
        return fixed(text, options)

    blocks, cur = [], []
    for seg in parts:
        if seg is None: continue
        if re.match(r"^(def|class|export|function|public|private|protected|void|int|float|double|char|bool|CREATE|BEGIN)\b", (seg or "").strip()):
            if cur:
                blocks.append("".join(cur).strip()); cur = []
        cur.append(seg)
    if cur: blocks.append("".join(cur).strip())

    out, buf, buf_len = [], [], 0
    for b in blocks:
        ln = toklen(b)
        if buf and buf_len + ln > int(options.target_tokens * 1.2):
            out.append(mk_chunk("\n\n".join(buf), {"strategy":"code_aware"}))
            buf, buf_len = [], 0
        if ln > options.max_tokens:
            toks = simple_tokenize(b)
            for s in slice_tokens(toks, options.target_tokens, options.overlap_tokens):
                out.append(mk_chunk(" ".join(s), {"strategy":"code_aware", "split":"hard"}))
        else:
            buf.append(b); buf_len += ln
    if buf:
        out.append(mk_chunk("\n\n".join(buf), {"strategy":"code_aware"}))
    return out
