# agents/policy.py
from typing import Dict
from chunker.select import select_strategy
from chunker.utils import ChunkingOptions

class Planner:
    """Decides initial strategy + options; can tweak on retry."""
    def plan(self, path: str, text: str, mime: str) -> Dict:
        initial = select_strategy(path, text, mime)
        opts = ChunkingOptions()  # start with defaults
        # minor nudges
        if initial == "code_aware":
            opts.target_tokens = 280; opts.overlap_tokens = 40
        elif initial == "layout_aware":
            opts.target_tokens = 260; opts.overlap_tokens = 70
        return {"strategy": initial, "options": opts}

    def refine(self, last_choice: str, last_scores: Dict[str, float], opts: ChunkingOptions) -> ChunkingOptions:
        # simple refinement: if boundary-focused strategies underperformed, increase overlap a bit
        new_opts = ChunkingOptions(
            target_tokens=opts.target_tokens,
            overlap_tokens=min(opts.target_tokens-10, int(opts.overlap_tokens * 1.25)),
            max_tokens=opts.max_tokens, min_tokens=opts.min_tokens, embedder=opts.embedder
        )
        return new_opts
