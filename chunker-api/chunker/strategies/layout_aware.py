import re
from typing import Dict, List
from ..utils import toklen, mk_chunk, split_by_sentences

def chunk(text: str, options, **kwargs) -> List[Dict]:
    if not text: return []
    lines = re.sub(r"\r\n?", "\n", text).split("\n")
    blocks, buf = [], []
    for ln in lines:
        if "|" in ln or (ln.count("\t") >= 2) or re.search(r"\s{2,}\|\s{2,}", ln):
            if buf:
                blocks.append("\n".join(buf).strip()); buf = []
            blocks.append(ln.strip())
        elif ln.strip() == "":
            if buf:
                blocks.append("\n".join(buf).strip()); buf = []
        else:
            buf.append(ln)
    if buf: blocks.append("\n".join(buf).strip())

    out, cur, cur_tokens = [], [], 0
    for b in blocks:
        bt = toklen(b)
        if cur and cur_tokens + bt > int(options.target_tokens * 1.3):
            text_block = "\n\n".join(cur)
            out.extend(_slice_to_chunks(text_block, options))
            cur, cur_tokens = [], 0
        cur.append(b); cur_tokens += bt
    if cur:
        out.extend(_slice_to_chunks("\n\n".join(cur), options))
    return [mk_chunk(c, {"strategy":"layout_aware"}) for c in out]

def _slice_to_chunks(text: str, options) -> List[str]:
    if toklen(text) <= int(options.target_tokens * 1.2):
        return [text]
    sents = split_by_sentences(text)
    if not sents:
        from ..utils import simple_tokenize, slice_tokens
        toks = simple_tokenize(text)
        return [" ".join(t) for t in slice_tokens(toks, options.target_tokens, options.overlap_tokens)]
    from ..utils import pack_to_target
    return pack_to_target(sents, options.target_tokens, options.overlap_tokens, options.max_tokens)
