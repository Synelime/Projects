from typing import Dict, List
from ..utils import simple_tokenize, mk_chunk

def chunk(text: str, options, **kwargs) -> List[Dict]:
    tokens = simple_tokenize(text)
    if not tokens:
        return []

    size = max(options.min_tokens, options.target_tokens)
    stride = max(1, size - options.overlap_tokens)

    out: List[Dict] = []
    for i in range(0, len(tokens), stride):
        window = tokens[i:i + size]
        if not window:
            break
        out.append(
            mk_chunk(
                " ".join(window),
                {"strategy": "fixed_sliding", "start_token": i}
            )
        )
        if i + size >= len(tokens):
            break
    return out
