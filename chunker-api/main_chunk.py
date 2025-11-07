# main_chunk.py (only showing changes)

import os, json, argparse
from chunker import ChunkingOptions, guess_mime, read_file_text, select_strategy
from chunker.strategies import layout_aware, hierarchical, fixed_sliding, semantic, recursive_split, code_aware, adaptive, vector_sliding
from chunker.evaluator import evaluate_strategies

import sys, io
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


STRATEGY_MAP = {
    "layout_aware": layout_aware.chunk,
    "hierarchical": hierarchical.chunk,
    "fixed_sliding": fixed_sliding.chunk,
    "semantic": semantic.chunk,
    "recursive_split": recursive_split.chunk,
    "code_aware": code_aware.chunk,
    "adaptive": adaptive.chunk,
    "vector_sliding": vector_sliding.chunk,
}

def process_text(text: str, strategy: str, options: ChunkingOptions, mime: str = "", verify: bool = False):
    chosen = strategy if strategy != "auto" else select_strategy("<in-memory>", text, mime)
    fn = STRATEGY_MAP[chosen]
    chunks = fn(text, options, mime=mime)

    # Optional verification: evaluate a small, relevant candidate set
    if verify:
        # pick candidates based on mime/content to keep it fast
        candidates = {
            "semantic": STRATEGY_MAP["semantic"],
            "hierarchical": STRATEGY_MAP["hierarchical"],
            "adaptive": STRATEGY_MAP["adaptive"],
        }
        # Include layout_aware if docx/pdf or has tables
        if mime in {"application/pdf","application/vnd.openxmlformats-officedocument.wordprocessingml.document"}:
            candidates["layout_aware"] = STRATEGY_MAP["layout_aware"]
        # Include code_aware if looks code-y
        # (reuse selection’s initial guess to keep it cheap)
        if chosen == "code_aware":
            candidates["code_aware"] = STRATEGY_MAP["code_aware"]

        best, scores, all_chunks = evaluate_strategies(text, mime, options, candidates)
        if best and best != chosen:
            chosen = best
            chunks = all_chunks[best]

        meta = {
            "strategy_requested": strategy,
            "strategy_selected": chosen,
            "num_chunks": len(chunks),
            "target_tokens": options.target_tokens,
            "overlap_tokens": options.overlap_tokens,
            "scores": scores,                 # expose how the verifier ranked options
            "verified": True,
        }
    else:
        meta = {
            "strategy_requested": strategy,
            "strategy_selected": chosen,
            "num_chunks": len(chunks),
            "target_tokens": options.target_tokens,
            "overlap_tokens": options.overlap_tokens,
            "verified": False,
        }

    return chunks, meta

def process_file(path: str, strategy: str, options: ChunkingOptions, verify: bool = False):
    mime = guess_mime(path)
    text = read_file_text(path, mime)
    chunks, meta = process_text(text, strategy, options, mime=mime, verify=verify)
    meta.update({"file": os.path.abspath(path), "mime": mime})
    return chunks, meta

def main():
    p = argparse.ArgumentParser(description="Modular Dynamic Chunker (+ verifier)")
    p.add_argument("filepath", help="Input file")
    p.add_argument("--strategy", default="auto",
                   choices=["auto","layout_aware","hierarchical","fixed_sliding","semantic","recursive_split","code_aware","adaptive","vector_sliding"])
    p.add_argument("--target", type=int, default=400)
    p.add_argument("--overlap", type=int, default=80)
    p.add_argument("--verify", action="store_true", help="Run ML-style verifier and switch strategy if better")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    opts = ChunkingOptions(target_tokens=args.target, overlap_tokens=args.overlap)
    chunks, meta = process_file(args.filepath, args.strategy, opts, verify=args.verify)

    if args.json:
        print(json.dumps({"meta": meta, "chunks": chunks}, ensure_ascii=False, indent=2))
    else:
        print(f"[{meta['strategy_selected']}][verified={meta['verified']}] {meta['num_chunks']} chunks | target={meta['target_tokens']} overlap={meta['overlap_tokens']}")
        if meta.get("scores"):
            print("Scores:", {k: round(v,3) for k,v in meta["scores"].items()})
        for i, c in enumerate(chunks, 1):
            preview = c["text"][:200].replace("\n", " ")
            print(f"--- Chunk {i} --- {preview}{'...' if len(c['text'])>200 else ''}")

if __name__ == "__main__":
    main()
