# chunker/quality.py
import math, re
from typing import List, Dict
from .utils import toklen, simple_tokenize, split_by_headings, split_by_sentences

PUNCT_END = re.compile(r"[.!?:;)\]\}\"\']$")

def heading_density(text: str) -> float:
    secs = split_by_headings(text)
    return 0.0 if not text else min(1.0, len(secs) / max(1, len(text.splitlines()) / 20))

def table_line_ratio(text: str) -> float:
    lines = [ln for ln in re.sub(r"\r\n?", "\n", text).split("\n") if ln.strip()]
    if not lines: return 0.0
    tableish = sum(1 for ln in lines if "|" in ln or ln.count("\t") >= 2)
    return tableish / len(lines)

def code_density(text: str) -> float:
    toks = max(1, len(re.findall(r"\S+", text)))
    code_chars = len(re.findall(r"[{}();<>]", text))
    return min(1.0, code_chars / toks)

def avg_std_chunk_len(chunks: List[Dict]) -> Dict[str, float]:
    if not chunks: return {"avg":0.0, "std":0.0}
    lens = [toklen(c["text"]) for c in chunks]
    avg = sum(lens) / len(lens)
    var = sum((x-avg)**2 for x in lens) / max(1, len(lens)-1)
    return {"avg": avg, "std": math.sqrt(var)}

def boundary_alignment(chunks: List[Dict]) -> float:
    """
    Approximate: start/end should look like boundaries (start with capital or heading; end with punctuation).
    Score in [0,1].
    """
    if not chunks: return 0.0
    ok = 0
    for c in chunks:
        t = c["text"].strip()
        if not t: 
            continue
        start_ok = bool(re.match(r"^[A-Z0-9#\"'(_-]", t))
        end_ok = bool(PUNCT_END.search(t))
        ok += (1 if start_ok else 0) + (1 if end_ok else 0)
    return ok / (2 * len(chunks))

def overlap_redundancy(chunks: List[Dict]) -> float:
    """
    Estimate redundancy between neighboring chunks via prefix/suffix overlap on raw text.
    Returns ratio in [0,1] (higher = more redundant).
    """
    if len(chunks) < 2: return 0.0
    def tail(t, n): 
        toks = simple_tokenize(t); 
        return " ".join(toks[-n:]) if toks else ""
    def head(t, n): 
        toks = simple_tokenize(t); 
        return " ".join(toks[:n]) if toks else ""
    units = 30  # small, token-agnostic window
    matches = 0
    for i in range(len(chunks)-1):
        if tail(chunks[i]["text"], units) and head(chunks[i+1]["text"], units) and \
            tail(chunks[i]["text"], units) == head(chunks[i+1]["text"], units):
            matches += 1
    return matches / (len(chunks)-1)

def sentence_integrity(chunks: List[Dict]) -> float:
    """
    Fraction of chunks whose first and last sentences are 'complete-ish'.
    """
    if not chunks: return 0.0
    good = 0
    for c in chunks:
        sents = split_by_sentences(c["text"])
        if not sents: 
            continue
        first, last = sents[0].strip(), sents[-1].strip()
        first_ok = bool(re.match(r"^[A-Z0-9\"'([{#]", first))
        last_ok  = bool(PUNCT_END.search(last))
        good += 1 if (first_ok and last_ok) else 0
    return good / len(chunks)
