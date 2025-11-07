# app.py
import os, json, tempfile, traceback, sys, io
from typing import Optional
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename

# Make sure local package imports work no matter where you start the server
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --- Import your agent workflow ---
from agents.workflow import ChunkingAgent
from chunker.utils import ChunkingOptions
from chunker.readers import guess_mime

# Ensure UTF-8 responses on Windows terminals if you print logs
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ---------------- Flask setup ----------------
app = Flask(__name__)
# 50 MB default; tune for your needs
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024

# Optional: where to keep temp outputs if you also want files persisted
DEFAULT_OUTDIR = os.getenv("CHUNK_OUTDIR", os.path.join(os.getcwd(), "api_out"))
os.makedirs(DEFAULT_OUTDIR, exist_ok=True)

def _bool(v: Optional[str], default=False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1","true","yes","y","on"}

def _int(v: Optional[str], default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default

# ---------------- Routes ----------------

@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.post("/chunk")
def chunk_file():
    """
    Multipart form-data:
      file: the document
      verify: bool (default true)
      target: int (default 400)
      overlap: int (default 80)
      max_iters: int (default 2)
      prefix: optional string
      json_inline: bool (default true)
      outdir: optional (if you want the file to be saved on disk as well)
    Returns:
      JSON with meta + chunks[] inline.
    """
    try:
        if "file" not in request.files:
            return jsonify({"error": "file is required (multipart/form-data)"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "empty filename"}), 400

        # Read form options
        verify = _bool(request.form.get("verify"), True)
        target = _int(request.form.get("target"), 400)
        overlap = _int(request.form.get("overlap"), 80)
        max_iters = _int(request.form.get("max_iters"), 2)
        prefix = request.form.get("prefix") or os.path.splitext(secure_filename(file.filename))[0]
        json_inline = _bool(request.form.get("json_inline"), True)
        outdir = request.form.get("outdir") or DEFAULT_OUTDIR

        # Save upload to a temp file (so readers/pdf/docx can work)
        with tempfile.TemporaryDirectory() as td:
            saved_path = os.path.join(td, secure_filename(file.filename))
            file.save(saved_path)

            # Build agent; force json_inline so we get a single JSON output
            agent = ChunkingAgent(
                verify=verify,
                max_iters=max_iters,
                outdir=outdir,
                json_inline=json_inline,
                json_out=None  # we let the agent pick <outdir>/<prefix>.json when inline
            )

            # Nudge base options (target/overlap) via planner refinement inputs
            # We do this by temporarily monkey-patching planner.plan to inject your target/overlap
            # without changing your existing code paths.
            orig_plan = agent.planner.plan
            def _plan(path, text, mime):
                plan = orig_plan(path, text, mime)
                # override options with client-provided target/overlap
                plan["options"] = ChunkingOptions(
                    target_tokens=target,
                    overlap_tokens=overlap,
                    max_tokens=plan["options"].max_tokens,
                    min_tokens=plan["options"].min_tokens,
                    embedder=plan["options"].embedder,
                )
                return plan
            agent.planner.plan = _plan  # type: ignore

            # Run agent
            result = agent.run(saved_path, prefix=prefix)

            # Read the inline JSON file the agent produced (at outdir/prefix.json)
            # When json_inline=True, agent returns manifest path that IS the json file path.
            manifest_path = result["manifest"]
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Enrich meta with request-level context (strategy_requested is always "auto" in agent)
            # Keep exactly your desired top-level shape
            # No extra wrapping; just return the manifest JSON
            return jsonify(data), 200

    except Exception as e:
        app.logger.exception("Chunking failed")
        return jsonify({
            "error": str(e),
            "trace": traceback.format_exc()
        }), 500


@app.post("/chunk-text")
def chunk_text():
    """
    JSON body:
      {
        "text": "...",
        "mime": "text/plain" | "text/markdown" | ... (optional, default text/plain),
        "verify": true,
        "target": 400,
        "overlap": 80,
        "max_iters": 2,
        "prefix": "optional-output-name"
      }
    Returns:
      JSON with meta + chunks[] inline.
    """
    try:
        body = request.get_json(force=True, silent=False) or {}
        text = body.get("text", "")
        if not text.strip():
            return jsonify({"error": "text is required in JSON body"}), 400

        mime = body.get("mime") or "text/plain"
        verify = bool(body.get("verify", True))
        target = int(body.get("target", 400))
        overlap = int(body.get("overlap", 80))
        max_iters = int(body.get("max_iters", 2))
        prefix = body.get("prefix") or "inmemory"

        # To reuse the same agent path, write text to a temp file with a derived extension
        ext_map = {
            "text/markdown": ".md",
            "text/csv": ".csv",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/pdf": ".pdf",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
            "application/vnd.ms-excel": ".xls",
            "text/plain": ".txt",
        }
        ext = ext_map.get(mime, ".txt")

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, f"{prefix}{ext}")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)

            agent = ChunkingAgent(
                verify=verify,
                max_iters=max_iters,
                outdir=DEFAULT_OUTDIR,
                json_inline=True,
                json_out=None
            )

            # Inject options
            orig_plan = agent.planner.plan
            def _plan(p, t, m):
                plan = orig_plan(p, t, m)
                plan["options"] = ChunkingOptions(
                    target_tokens=target,
                    overlap_tokens=overlap,
                    max_tokens=plan["options"].max_tokens,
                    min_tokens=plan["options"].min_tokens,
                    embedder=plan["options"].embedder,
                )
                return plan
            agent.planner.plan = _plan  # type: ignore

            result = agent.run(path, prefix=prefix)
            manifest_path = result["manifest"]
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            return jsonify(data), 200

    except Exception as e:
        app.logger.exception("Chunking(text) failed")
        return jsonify({
            "error": str(e),
            "trace": traceback.format_exc()
        }), 500
    
@app.get("/")
def index():
    return (
        "<h2>Chunker API</h2>"
        "<p>Use POST /chunk (multipart) or POST /chunk-text (JSON).</p>"
        '<form action="/chunk" method="post" enctype="multipart/form-data">'
        '<input type="file" name="file" required /> '
        '<input type="hidden" name="verify" value="true" /> '
        '<input type="hidden" name="json_inline" value="true" /> '
        '<button type="submit">Upload & Chunk</button>'
        "</form>",
        200, {"Content-Type": "text/html"}
    )

if __name__ == "__main__":
    # For Windows, use waitress or Flask dev server; in prod on Linux, use gunicorn/uvicorn
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=_bool(os.getenv("FLASK_DEBUG"), False))
