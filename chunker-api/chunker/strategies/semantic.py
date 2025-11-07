from typing import Dict, List
from ..utils import split_by_sentences, toklen, mk_chunk, simple_tokenize, slice_tokens, pack_to_target

def chunk(text: str, options, **kwargs) -> List[Dict]:
    sents = split_by_sentences(text)
    if not sents:
        toks = simple_tokenize(text)
        wins = slice_tokens(toks, options.target_tokens, options.overlap_tokens)
        return [mk_chunk(" ".join(w), {"strategy": "semantic"}) for w in wins]

    pieces: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for s in sents:
        st = toklen(s)
        if st > options.max_tokens:
            toks = simple_tokenize(s)
            for p in slice_tokens(toks, options.target_tokens, options.overlap_tokens):
                pieces.append(" ".join(p))
            continue
        if cur_len + st > int(options.target_tokens * 1.1) and cur:
            pieces.append(" ".join(cur))
            cur, cur_len = [], 0
        cur.append(s)
        cur_len += st
    if cur:
        pieces.append(" ".join(cur))

    return [mk_chunk(p, {"strategy": "semantic"}) for p in pieces]
