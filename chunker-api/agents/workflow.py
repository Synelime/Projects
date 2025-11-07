# agents/workflow.py
import os
from typing import Dict, Optional
from .tools import load_doc, run_strategy, verify_best, export_results, export_results_inline_json, _relable_chunks
from .policy import Planner               # ✅ bring Planner in
from chunker.utils import ChunkingOptions



class AgentMemory:
    def __init__(self):
        self.trace = []

    def log(self, event: str, payload: Dict):
        self.trace.append({"event": event, "data": payload})

class ChunkingAgent:
    def __init__(self, verify: bool = True, max_iters: int = 2, outdir: Optional[str] = None,
                 json_inline: bool = False, json_out: Optional[str] = None):
        self.verify = verify
        self.max_iters = max_iters
        self.outdir = outdir or os.path.join(os.getcwd(), "agent_out")
        self.json_inline = json_inline
        self.json_out = json_out
        self.planner = Planner()          # ✅ now defined
        self.mem = AgentMemory()

    # agents/workflow.py (inside class ChunkingAgent)

    # agents/workflow.py
import os
from typing import Dict, Optional
from .tools import (
    load_doc, run_strategy, verify_best,
    export_results, export_results_inline_json,
    _relable_chunks,
)
from .policy import Planner
from chunker.utils import ChunkingOptions

class AgentMemory:
    def __init__(self):
        self.trace = []

    def log(self, event: str, payload: Dict):
        self.trace.append({"event": event, "data": payload})

class ChunkingAgent:
    def __init__(
        self,
        verify: bool = True,
        max_iters: int = 2,
        outdir: Optional[str] = None,
        json_inline: bool = False,
        json_out: Optional[str] = None,
    ):
        self.verify = verify
        self.max_iters = max_iters
        self.outdir = outdir or os.path.join(os.getcwd(), "agent_out")
        self.json_inline = json_inline
        self.json_out = json_out
        self.planner = Planner()
        self.mem = AgentMemory()

    def run(self, filepath: str, prefix: Optional[str] = None) -> Dict:
        # -------- Load & Plan --------
        text, mime, digest = load_doc(filepath)
        plan = self.planner.plan(filepath, text, mime)
        self.mem.log("plan", {
            "mime": mime, "digest": digest,
            "strategy": plan["strategy"], "options": vars(plan["options"])
        })

        opts: ChunkingOptions = plan["options"]
        best: str = plan["strategy"]

        chunks = None  # will hold the final chunks

        # -------- Plan → Run → Verify → Refine loop --------
        for it in range(self.max_iters):
            run_chunks, _meta = run_strategy(text, mime, best, opts)
            chunks = run_chunks
            self.mem.log("run", {
                "iter": it, "choice": best,
                "num_chunks": len(chunks), "opts": vars(opts)
            })

            if not self.verify:
                break

            cand_best, cand_scores, cand_chunks = verify_best(text, mime, opts, best)
            self.mem.log("verify", {
                "iter": it,
                "scores": {k: round(v, 3) for k, v in (cand_scores or {}).items()},
                "candidate_best": cand_best
            })

            if cand_best and cand_best != best:
                best = cand_best
                chunks = cand_chunks[cand_best]
                self.mem.log("switch", {"iter": it, "new_choice": best})
                break
            elif it + 1 < self.max_iters:
                opts = self.planner.refine(best, cand_scores or {}, opts)
                self.mem.log("refine", {"iter": it, "new_opts": vars(opts)})
            else:
                break

        # Safety: if no chunks yet, run once
        if chunks is None:
            chunks, _ = run_strategy(text, mime, best, opts)

        # Normalize per-chunk label to final selected strategy
        chunks = _relable_chunks(chunks, best)

        # -------- Export --------
        file_abs = os.path.abspath(filepath)

        # pull last verify scores if present
        last_scores = None
        for ev in reversed(self.mem.trace):
            if ev["event"] == "verify":
                last_scores = ev["data"].get("scores")
                break

        meta_extra = {
            "verified": self.verify,
            "scores": last_scores,
            "target_tokens": opts.target_tokens,
            "overlap_tokens": opts.overlap_tokens,
            "strategy_requested": "auto",
        }

        if self.json_inline:
            out_path = self.json_out
            if not out_path:
                prefix = prefix or os.path.splitext(os.path.basename(filepath))[0]
                out_path = os.path.join(self.outdir, f"{prefix}.json")
            manifest_path = export_results_inline_json(out_path, file_abs, mime, best, chunks, meta_extra)
            return {"manifest": manifest_path, "strategy": best, "outdir": os.path.dirname(manifest_path)}
        else:
            prefix = prefix or os.path.splitext(os.path.basename(filepath))[0]
            manifest_path = export_results(self.outdir, prefix, file_abs, mime, best, chunks, meta_extra)
            return {"manifest": manifest_path, "strategy": best, "outdir": self.outdir}


        # ----- export -----
        file_abs = os.path.abspath(filepath)
        # Pull last verify scores if present
        last_scores = None
        for ev in reversed(self.mem.trace):
            if ev["event"] == "verify":
                last_scores = ev["data"].get("scores")
                break

        meta_extra = {
            "verified": self.verify,
            "scores": last_scores,
            "target_tokens": opts.target_tokens,
            "overlap_tokens": opts.overlap_tokens,
            "strategy_requested": "auto",
        }

        if self.json_inline:
            out_path = self.json_out
            if not out_path:
                prefix = prefix or os.path.splitext(os.path.basename(filepath))[0]
                out_path = os.path.join(self.outdir, f"{prefix}.json")
            manifest_path = export_results_inline_json(out_path, file_abs, mime, best, chunks, meta_extra)
            return {"manifest": manifest_path, "strategy": best, "outdir": os.path.dirname(manifest_path)}
        else:
            prefix = prefix or os.path.splitext(os.path.basename(filepath))[0]
            manifest_path = export_results(self.outdir, prefix, file_abs, mime, best, chunks, meta_extra)
            return {"manifest": manifest_path, "strategy": best, "outdir": self.outdir}
