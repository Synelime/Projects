# agents/tools.py
import os, json, time, hashlib
from typing import Dict, List, Tuple, Callable
from chunker.utils import ChunkingOptions
from chunker.readers import guess_mime, read_file_text
from chunker.select import select_strategy
from chunker.strategies import (
    layout_aware, hierarchical, fixed_sliding, semantic,
    recursive_split, code_aware, adaptive, vector_sliding
)
from chunker.evaluator import evaluate_strategies  # optional verifier

STRATEGY_MAP: Dict[str, Callable] = {
    "layout_aware": layout_aware.chunk,
    "hierarchical": hierarchical.chunk,
    "fixed_sliding": fixed_sliding.chunk,
    "semantic": semantic.chunk,
    "recursive_split": recursive_split.chunk,
    "code_aware": code_aware.chunk,
    "adaptive": adaptive.chunk,
    "vector_sliding": vector_sliding.chunk,
}

def _relable_chunks(chunks: List[Dict], final_label: str) -> List[Dict]:
    for c in chunks:
        m = c.setdefault("meta", {})
        # Preserve original as "inner_strategy" if present
        if "strategy" in m and m["strategy"] != final_label:
            m["inner_strategy"] = m["strategy"]
        m["strategy"] = final_label
    return chunks


def choose_candidates(text: str, mime: str, first_choice: str):
    pool = {"semantic": STRATEGY_MAP["semantic"],
            "adaptive": STRATEGY_MAP["adaptive"],
            "hierarchical": STRATEGY_MAP["hierarchical"]}

    # Include layout for table-like mimes
    if mime in {"application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "text/csv",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-excel"}:
        pool["layout_aware"] = STRATEGY_MAP["layout_aware"]

    # NEW: include code_aware if mime or filename suggest code OR initial is code_aware
    looks_code = mime.startswith("text/x-") or any(
        (k in (text or "")) for k in ("def ", "class ", "#include", "package main", "fn ")
    )
    if first_choice == "code_aware" or looks_code:
        pool["code_aware"] = STRATEGY_MAP["code_aware"]

    return pool

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

def load_doc(path: str) -> Tuple[str, str, str]:
    mime = guess_mime(path)
    text = read_file_text(path, mime)
    return text, mime, sha256_file(path)

def run_strategy(text: str, mime: str, strategy: str, options: ChunkingOptions):
    fn = STRATEGY_MAP[strategy]
    chunks = fn(text, options, mime=mime)
    meta = {
        "strategy_selected": strategy,
        "num_chunks": len(chunks),
        "target_tokens": options.target_tokens,
        "overlap_tokens": options.overlap_tokens,
    }
    return chunks, meta

def choose_candidates(text: str, mime: str, first_choice: str) -> Dict[str, Callable]:
    pool: Dict[str, Callable] = {
        "semantic": STRATEGY_MAP["semantic"],
        "adaptive": STRATEGY_MAP["adaptive"],
        "hierarchical": STRATEGY_MAP["hierarchical"],
    }
    if mime in {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    }:
        pool["layout_aware"] = STRATEGY_MAP["layout_aware"]
    if first_choice == "code_aware":
        pool["code_aware"] = STRATEGY_MAP["code_aware"]
    return pool

def verify_best(text: str, mime: str, options: ChunkingOptions, initial_choice: str):
    candidates = choose_candidates(text, mime, initial_choice)
    best, scores, all_chunks = evaluate_strategies(text, mime, options, candidates)
    if best == "code_aware" and mime == "application/pdf":
    # Penalize code_aware on PDF docs (likely false positive)
        scores["code_aware"] -= 50
    return best, scores, all_chunks

def export_results(outdir: str, prefix: str, file_abs: str, mime: str,
                   chosen: str, chunks: List[Dict], meta_extra: Dict):
    os.makedirs(outdir, exist_ok=True)
    exported = []
    for i, c in enumerate(chunks, 1):
        idx = f"{i:03d}"
        txt_name = f"{prefix}_chunk_{idx}.txt"
        meta_name = f"{prefix}_chunk_{idx}.meta.json"

        with open(os.path.join(outdir, txt_name), "w", encoding="utf-8") as f:
            f.write(c["text"])

        sidecar = {
            "id": c.get("id"),
            "meta": c.get("meta", {}),
            "index": i,
            "rel_text_path": txt_name,
        }
        with open(os.path.join(outdir, meta_name), "w", encoding="utf-8") as f:
            json.dump(sidecar, f, ensure_ascii=False, indent=2)

        exported.append({
            "index": i,
            "id": c.get("id"),
            "text_file": txt_name,
            "meta_file": meta_name,
            "meta": c.get("meta", {}),
        })

    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_file": file_abs,
        "mime": mime,
        "strategy_selected": chosen,
        "num_chunks": len(chunks),
        **(meta_extra or {}),
        "chunks": exported,
    }
    man_path = os.path.join(outdir, f"{prefix}_manifest.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return man_path

def export_results_inline_json(out_path: str, file_abs: str, mime: str,
                               chosen: str, chunks: List[Dict], meta_extra: Dict):
    meta = {
        "strategy_selected": chosen,
        "num_chunks": len(chunks),
        "file": file_abs,
        "mime": mime,
        **(meta_extra or {}),
    }
    obj = {"meta": meta, "chunks": chunks}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return out_path
