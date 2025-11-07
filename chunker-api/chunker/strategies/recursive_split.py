import re
from typing import Dict, List
from ..utils import split_by_headings, mk_chunk, toklen, split_by_sentences, simple_tokenize, slice_tokens, pack_to_target


def chunk(text: str, options, **kwargs) -> List[Dict]:
    sections = split_by_headings(text)
    bases = [b for _, b in sections] if sections else [text]
    out: List[Dict] = []
    for base in bases:
        if toklen(base) <= int(options.target_tokens * 1.2):
            out.append(mk_chunk(base, {"strategy":"recursive", "level":"base"})); continue
        paras = [p.strip() for p in re.split(r"\n\s*\n", base) if p.strip()]
        for p in paras if paras else [base]:
            if toklen(p) <= int(options.target_tokens * 1.2):
                out.append(mk_chunk(p, {"strategy":"recursive", "level":"para"}))
            else:
                sents = split_by_sentences(p) or [p]
                for c in pack_to_target(sents, options.target_tokens, options.overlap_tokens, options.max_tokens):
                    out.append(mk_chunk(c, {"strategy":"recursive", "level":"sentences"}))
    return out
