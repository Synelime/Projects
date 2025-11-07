import re, uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

_TOKENIZER = None  # set via set_tokenizer()

def set_tokenizer(tok):  # e.g., tiktoken.get_encoding("cl100k_base")
    global _TOKENIZER; _TOKENIZER = tok

def simple_tokenize(text: str) -> list[str]:
    if _TOKENIZER:
        # Return token *strings* for compatibility; keep count fast:
        ids = _TOKENIZER.encode(text or "")
        return [str(i) for i in ids]  # cheap surrogate tokens
    import re
    return re.findall(r"\S+", text or "")

def toklen(text: str) -> int:
    return len(simple_tokenize(text))

def split_by_sentences(text: str) -> List[str]:
    if not text:
        return []
    t = re.sub(r"\r\n?", "\n", text)
    paras = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    out = []
    for p in paras:
        parts = re.split(r"(?<=[!.?])\s+(?=[A-Z0-9\"'])", p)
        tmp = []
        for s in parts:
            tmp.extend([x for x in re.split(r"\n+", s) if x.strip()])
        out.extend(tmp)
    return out

def split_by_headings(text: str):
    if not text:
        return []
    lines = re.sub(r"\r\n?", "\n", text).split("\n")
    sections, current, buf = [], "ROOT", []
    heading_re = re.compile(
        r"^(?:#{1,6}\s.+|(?:\d+(\.\d+){0,4}[\.\)])\s+.+|(?:[A-Z0-9][A-Z0-9\s\-/&]{3,})$)"
    )
    for ln in lines:
        if heading_re.match(ln.strip()):
            if buf:
                sections.append((current, "\n".join(buf).strip()))
                buf = []
            current = ln.strip()
        else:
            buf.append(ln)
    if buf:
        sections.append((current, "\n".join(buf).strip()))
    return [(h, s) for h, s in sections if s]

def slice_tokens(tokens: List[str], target: int, overlap: int) -> List[List[str]]:
    if target <= 0:
        return [tokens]
    stride = max(1, target - max(0, overlap))
    out = []
    for i in range(0, len(tokens), stride):
        win = tokens[i:i+target]
        if not win:
            break
        out.append(win)
        if i + target >= len(tokens):
            break
    return out

def pack_to_target(pieces: List[str], target: int, overlap: int, max_tokens: int) -> List[str]:
    out, cur, cur_len = [], [], 0
    for p in pieces:
        pl = toklen(p)
        if pl > max_tokens:
            toks = simple_tokenize(p)
            for s in slice_tokens(toks, target, overlap):
                out.append(" ".join(s))
            continue
        if cur and cur_len + pl > int(target * 1.1):
            out.append(" ".join(cur))
            cur = [cur[-1]] if cur else []
            cur_len = toklen(cur[0]) if cur else 0
        cur.append(p); cur_len += pl
    if cur:
        out.append(" ".join(cur))
    return out

@dataclass
class ChunkingOptions:
    target_tokens: int = 400
    overlap_tokens: int = 80
    max_tokens: int = 1200
    min_tokens: int = 40
    embedder: Optional[Callable[[List[str]], List[List[float]]]] = None

def mk_chunk(text: str, meta: Dict) -> Dict:
    return {"id": str(uuid.uuid4()), "text": text, "meta": meta}
