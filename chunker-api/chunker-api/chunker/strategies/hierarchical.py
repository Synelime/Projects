from typing import Dict, List
from ..utils import split_by_headings, mk_chunk, toklen, split_by_sentences, simple_tokenize, slice_tokens, pack_to_target


def chunk(text: str, options, **kwargs) -> List[Dict]:
    sections = split_by_headings(text)
    if not sections:
        # fallback to semantic
        from .semantic import chunk as semantic_chunk
        return semantic_chunk(text, options)
    out = []
    for head, body in sections:
        pieces = _slice(body, options)
        for c in pieces:
            out.append(mk_chunk(c, {"strategy":"hierarchical", "heading": head}))
    return out

def _slice(text: str, options) -> List[str]:
    if toklen(text) <= int(options.target_tokens * 1.2):
        return [text]
    sents = split_by_sentences(text)
    if not sents:
        toks = simple_tokenize(text)
        return [" ".join(t) for t in slice_tokens(toks, options.target_tokens, options.overlap_tokens)]
    return pack_to_target(sents, options.target_tokens, options.overlap_tokens, options.max_tokens)
