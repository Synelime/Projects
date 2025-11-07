from typing import Dict, List
from ..utils import simple_tokenize, slice_tokens, mk_chunk

def chunk(text: str, options, **kwargs) -> List[Dict]:
    toks = simple_tokenize(text)
    wins = slice_tokens(toks, options.target_tokens, options.overlap_tokens)
    texts = [" ".join(w) for w in wins]
    if options.embedder is None:
        return [mk_chunk(t, {"strategy":"vector_sliding", "embedding": None}) for t in texts]
    vecs = options.embedder(texts)
    out = []
    for t, v in zip(texts, vecs):
        out.append(mk_chunk(t, {"strategy":"vector_sliding", "embedding": v}))
    return out
