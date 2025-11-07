# chunker/select.py
import re
from .utils import toklen, split_by_headings



def select_strategy(filepath: str, text: str, mime: str) -> str:
    # --- quick extension check for code ---
    path_l = (filepath or "").lower()
    if path_l.endswith((".py",".js",".ts",".java",".cs",".cpp",".c",".go",".rb",".php",".rs",".sql")):
        return "code_aware"
    
    if mime == "application/pdf":
         if re.search(r"\b(Abstract|Introduction|Results|Conclusion|References)\b", text):
            return "hierarchical"

    # existing code detection (MIME + content)
    if is_code_text(text, mime):
        return "code_aware"

# --- Markdown fenced-code detection ---
FENCE_RE = re.compile(r"(?ms)^```[^\n]*\n(.*?)\n```")

def _markdown_code_ratio(text: str) -> float:
    """Fraction of lines that live inside fenced code blocks in Markdown."""
    if not text:
        return 0.0
    lines_total = max(1, len(re.sub(r"\r\n?", "\n", text).split("\n")))
    code_lines = 0
    for m in FENCE_RE.finditer(text):
        block = m.group(1) or ""
        code_lines += len(block.split("\n"))
    return min(1.0, code_lines / lines_total)

# --- Table-ish cues (for layout-aware) ---
def _has_table_cues(text: str) -> bool:
    """Detect pipes/tabs/column spacing; avoids counting blank lines as 'layout'."""
    if not text:
        return False
    lines = [ln for ln in re.sub(r"\r\n?", "\n", text).split("\n") if ln.strip()]
    if not lines:
        return False
    tableish = 0
    for ln in lines:
        if "|" in ln:
            tableish += 1
        elif ln.count("\t") >= 2:
            tableish += 1
        elif re.search(r"\s{2,}\S+\s{2,}\S+", ln):  # spaced columns
            tableish += 1
    ratio = tableish / len(lines)
    return tableish >= 2 and ratio >= 0.03

# --- Code vs prose heuristic ---
def is_code_text(text: str, mime: str) -> bool:
    # existing quick path for MIME
    if mime.startswith("text/x-") or mime in {"application/sql", "application/javascript"}:
        return True
    if mime.startswith("application/pdf"):
        return False  # <-- PDF is never code
    
    # content-based density check
    if not text:
        return False

    # count likely code characters
    code_chars = sum(text.count(ch) for ch in "{}[]();<>")
    total = len(text)
    code_ratio = code_chars / max(total, 1)

    # heuristics: require high code ratio & keywords
    code_keywords = ["def ", "class ", "#include", "public ", "function ", "=>", "::"]
    keyword_hits = sum(kw in text for kw in code_keywords)

    # Lower ratio threshold, but skip scientific notation patterns
    if code_ratio > 0.08 or keyword_hits > 0:
        # Exclude mathematical papers (digits + scientific notation)
        math_tokens = re.findall(r"\b10[\-\^]?\d+|\d+\s*[×x*]\s*10", text)
        if len(math_tokens) > 10:
            return False
        return True

    return False


# --- Main auto-selector ---
def select_strategy(filepath: str, text: str, mime: str) -> str:
    # 1) Code first
    if is_code_text(text, mime):
        return "code_aware"

    # 2) Strong table formats → layout-aware
    if mime in {
        "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    }:
        return "layout_aware"

    # 3) Markdown with lots of fenced code → code-aware
    if mime == "text/markdown" and _markdown_code_ratio(text) >= 0.18:
        return "code_aware"

    # 4) DOCX/PDF with real table cues → layout-aware
    if mime in {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    } and _has_table_cues(text):
        return "layout_aware"

    # 5) Clear section structure → hierarchical
    if split_by_headings(text):
        return "hierarchical"

    # 6) Length-based fallbacks
    n = toklen(text)
    if n > 6000:
        return "recursive_split"
    if 1200 <= n <= 6000:
        return "adaptive"
    return "semantic"
