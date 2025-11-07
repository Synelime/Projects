# main_agent.py
import os, json, argparse, sys, io
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from agents.workflow import ChunkingAgent

def main():
    p = argparse.ArgumentParser(description="Agentic Chunking Orchestrator")
    p.add_argument("filepath", help="Input file (pdf/docx/csv/xlsx/txt/md/code)")
    p.add_argument("--verify", action="store_true", help="Enable ML-style verification & auto-switch")
    p.add_argument("--max-iters", type=int, default=2, help="Max agent passes (plan→verify→refine)")
    p.add_argument("--outdir", default=None, help="Output directory (default: ./agent_out)")
    p.add_argument("--prefix", default=None, help="Prefix for output files")

    # NEW: single-file JSON mode
    p.add_argument("--json-inline", action="store_true",
                   help="Write a single JSON containing meta + all chunks inline (no per-chunk files).")
    p.add_argument("--json-out", default=None,
                   help="Path to write the inline JSON (e.g., D:\\chunker\\chunked_files\\sample.json). If omitted, writes to <outdir>/<prefix>.json")

    args = p.parse_args()

    agent = ChunkingAgent(
        verify=args.verify,
        max_iters=args.max_iters,
        outdir=args.outdir,
        json_inline=args.json_inline,
        json_out=args.json_out
    )
    result = agent.run(args.filepath, prefix=args.prefix)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nManifest at: {result['manifest']}")

if __name__ == "__main__":
    main()
