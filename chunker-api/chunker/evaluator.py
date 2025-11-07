# chunker/evaluator.py
from typing import Dict, List, Callable, Tuple
from .quality import (
    heading_density, table_line_ratio, code_density, 
    avg_std_chunk_len, boundary_alignment, overlap_redundancy, sentence_integrity
)
from .utils import toklen

# --------- Feature extraction ---------
def extract_features(text: str, chunks: List[Dict], mime: str) -> Dict[str, float]:
    dens_h  = heading_density(text)
    dens_tbl= table_line_ratio(text)
    dens_cd = code_density(text)
    ls      = avg_std_chunk_len(chunks)
    align   = boundary_alignment(chunks)
    redun   = overlap_redundancy(chunks)
    integ   = sentence_integrity(chunks)

    return {
        "heading_density": dens_h,
        "table_ratio": dens_tbl,
        "code_density": dens_cd,
        "avg_len": ls["avg"],
        "std_len": ls["std"],
        "boundary_align": align,
        "overlap_redundancy": redun,
        "sentence_integrity": integ,
        "num_chunks": float(len(chunks)),
        "doc_len": float(toklen(text)),
        # optional MIME dummies
        "is_pdf_docx": 1.0 if mime in {"application/pdf","application/vnd.openxmlformats-officedocument.wordprocessingml.document"} else 0.0,
        "is_code_mime": 1.0 if mime.startswith("text/x-") or mime in {"text/javascript","text/typescript","application/sql"} else 0.0,
    }

# --------- Tiny “model” (pluggable) ---------
class LinearModel:
    """
    A simple, interpretable linear scorer. Replace with a real model by 
    implementing predict(features: Dict[str,float]) -> float.
    """
    def __init__(self, weights: Dict[str, float], bias: float = 0.0):
        self.w = weights
        self.b = bias

    def predict(self, feats: Dict[str, float]) -> float:
        score = self.b
        for k, v in self.w.items():
            score += v * feats.get(k, 0.0)
        return score

# Good default weights (heuristic):
# - Prefer boundary alignment, sentence integrity.
# - Penalize high std of lengths (unstable packing).
# - For PDFs with tables, reward table_ratio with layout_aware; for heading-y docs, reward heading_density.
DEFAULT_WEIGHTS = {
    "boundary_align":      1.6,
    "sentence_integrity":  1.4,
    "heading_density":     0.8,
    "table_ratio":         0.7,
    "std_len":            -0.4,
    "overlap_redundancy": -0.6,   # too much redundancy is wasteful
    "code_density":        0.4,   # ok if truly code
}

DEFAULT_MODEL = LinearModel(DEFAULT_WEIGHTS, bias=0.0)

# --------- Strategy evaluation wrapper ---------
def evaluate_strategies(
    text: str,
    mime: str,
    options,
    candidates: Dict[str, Callable[[str, object], List[Dict]]],
    model: LinearModel = DEFAULT_MODEL
) -> Tuple[str, Dict[str, float], Dict[str, List[Dict]]]:
    """
    Runs each candidate strategy, extracts features, scores them, and returns:
      (best_strategy, scores_per_strategy, chunks_per_strategy)
    """
    scores: Dict[str, float] = {}
    all_chunks: Dict[str, List[Dict]] = {}

    for name, fn in candidates.items():
        chunks = fn(text, options, mime=mime)  # **kwargs safe for all strategies
        all_chunks[name] = chunks
        feats = extract_features(text, chunks, mime)
        # Small per-strategy flavor nudges (prior)
        # e.g., hierarchical benefits more from headings; layout_aware from tables; code_aware from code.
        prior = 0.0
        if name == "hierarchical": prior += 0.6 * feats["heading_density"]
        if name == "layout_aware": prior += 0.6 * feats["table_ratio"]
        if name == "code_aware":   prior += 0.6 * feats["code_density"]
        score = model.predict(feats) + prior
        scores[name] = score

    best = max(scores, key=lambda k: scores[k]) if scores else None
    return best, scores, all_chunks
