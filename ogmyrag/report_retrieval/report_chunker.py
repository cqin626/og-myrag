import re
import time
import random
import logging
from typing import List, Tuple, Optional, Dict, Any

retrieval_logger = logging.getLogger("retrieval")

# ---------------- (kept for compatibility, but not used in fast path) ----------------
def _get_encoder(model: str = "text-embedding-3-small"):
    try:
        import tiktoken
        return tiktoken.encoding_for_model(model)
    except Exception:
        try:
            import tiktoken
            return tiktoken.get_encoding("cl100k_base")
        except Exception:
            class _Dummy:
                def encode(self, s: str):
                    return [0] * max(1, len(s) // 4)
            return _Dummy()

def _count_tokens(enc, s: str) -> int:
    return len(enc.encode(s))

# ---------------- Fast length helpers (≈ 4 chars per token) ----------------
def _approx_limit_tokens_to_chars(tokens: int) -> int:
    # Heuristic: ~4 chars per token (fast and good enough for gating)
    return max(1, tokens * 4)

def _fits(limit_chars: int, text: str) -> bool:
    return len(text) <= limit_chars

# ---------------- Precompiled regexes (speed) ----------------
RE_ATX = re.compile(r'^\s{0,3}(#{1,6})\s+(\S.*)$')
RE_ATX_ONLY = re.compile(r'^\s{0,3}#{1,6}\s+\S')
RE_BOLD = re.compile(r'^\s*\*\*(.+?)\*\*\s*$')
RE_ENUM = re.compile(r'^\s*\d+(?:\.\d+)*\s+[A-Z].{3,}$')
RE_ALLCAPS = re.compile(r'^\s*[A-Z0-9\s,&()\/\-\–\.]{8,}$')
RE_ROMAN = re.compile(r'^\s*\(?[ivxlcdmIVXLCDM]+\)\s+.+$')
RE_BRACKET_ENUM = re.compile(r'^\s*\[\s*\(?[ivxlcdmIVXLCDM]+\)\s*.+\]\s*$')

RE_LIST_START = re.compile(r'^\s*(?:[-*•]\s+|\d{1,3}[.)]\s+|\(?[ivxlcdmIVXLCDM]+\)\s+)')
RE_MD_TABLE_DIV = re.compile(r'^\s*\|?.*?-{3,}.*\|?.*$')
RE_HAS_PIPE = re.compile(r'\|')
RE_TABLE_LABEL = re.compile(r'^\s*Table:\s*(.+)$', re.IGNORECASE)
RE_FIGURE_LABEL = re.compile(r'^\s*Figure:\s*(.+)$', re.IGNORECASE)
RE_PAGE_PAREN = re.compile(r'\(p\.\s*([0-9]+(?:\s*[\-–]\s*[0-9]+)?)\)')

# ---------------- Pseudo-heading detection ----------------
def _is_pseudo_heading(s: str) -> bool:
    s = s.strip()
    if s.startswith("|") and s.endswith("|"):
        return False
    return (
        RE_BOLD.match(s) is not None
        or RE_ENUM.match(s) is not None
        or RE_ROMAN.match(s) is not None
        or RE_BRACKET_ENUM.match(s) is not None
        or (RE_ALLCAPS.match(s) is not None and not s.endswith("."))
    )

def _normalize_heading_line(ln: str) -> str:
    s = ln.strip()
    if RE_ATX_ONLY.match(s):
        return s
    s = re.sub(r"^\s*\*\*|\*\*\s*$", "", s)
    s = re.sub(r"^\[\s*|\s*\]\s*$", "", s)
    return "## " + s

# ---------------- Markdown table parsing ----------------
def _parse_md_table(lines: List[str]) -> Tuple[List[str], List[List[str]]]:
    if len(lines) < 2:
        return [], []
    header_line = lines[0].strip()
    divider = lines[1].strip()
    if "|" not in header_line or RE_MD_TABLE_DIV.match(divider) is None:
        return [], []
    header = [c.strip() for c in header_line.strip("|").split("|")]
    rows: List[List[str]] = []
    for ln in lines[2:]:
        if not ln.strip() or "|" not in ln:
            break
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        rows.append(cells[:len(header)])
    return header, rows

# ---------------- Emit under cap (character-based) ----------------
def _emit_under_cap_fast(
    path: str,
    body: str,
    max_chars: int,
    chunks: List[str],
) -> None:
    """Emit body (with [path]) ensuring it never exceeds max_chars. Split by sentences/words if needed."""
    prefix = f"[{path}]\n" if path else ""
    payload = prefix + body
    if _fits(max_chars, payload):
        chunks.append(payload)
        return

    # Sentence-level split (char-based)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", body.strip()) if body.strip() else [body]
    buf: List[str] = []
    for s in parts:
        candidate = "\n".join(buf + [s]).strip()
        if _fits(max_chars, prefix + candidate):
            buf.append(s)
        else:
            if buf:
                chunks.append(prefix + "\n".join(buf))
            # try single sentence
            if _fits(max_chars, prefix + s):
                buf = [s]
            else:
                # Word-level hard cut (char-based)
                words = s.split()
                cur: List[str] = []
                for w in words:
                    cand = (" ".join(cur + [w])).strip()
                    if not _fits(max_chars, prefix + cand) and cur:
                        chunks.append(prefix + " ".join(cur))
                        cur = [w]
                    else:
                        cur.append(w)
                if cur:
                    chunks.append(prefix + " ".join(cur))
                buf = []
    if buf:
        last = "\n".join(buf).strip()
        if _fits(max_chars, prefix + last):
            chunks.append(prefix + last)
        else:
            # final safety word split
            words = last.split()
            cur: List[str] = []
            for w in words:
                cand = (" ".join(cur + [w])).strip()
                if not _fits(max_chars, prefix + cand) and cur:
                    chunks.append(prefix + " ".join(cur))
                    cur = [w]
                else:
                    cur.append(w)
            if cur:
                chunks.append(prefix + " ".join(cur))

def _extract_path(chunk: str) -> str:
    if chunk.startswith("[") and "]\n" in chunk:
        return chunk[1:].split("]\n", 1)[0]
    return ""

def _preview(chunk: str, max_len: int = 280) -> str:
    return chunk[:max_len].replace("\n", " ").strip()

# ---------------- MAIN: FAST, SEMANTIC-ATOMIC CHUNKER (single pass) ----------------
def chunk_markdown_financial_reports(
    text: str,
    max_tokens: int = 8000,
    overlap_tokens: int = 0,        # <- default 0: emit atomic units, no cross-merge
    min_chunk_chars: int = 120,
    model: str = "text-embedding-3-small",
    table_mode: str = "row",        # "row" | "block" | "hybrid"
    list_mode: str = "item",        # "item" | "group"
    keep_path_prefix: bool = True,  # include [H1 > H2 > H3] prefix
    include_table_block_with_rows: bool = False,  # also emit full table next to row chunks
    debug: bool = False,
) -> List[str]:
    """
    FAST (single-pass) semantic chunker optimized for authoritative PDF-derived Markdown.
    - Emits atomic units: paragraph, list-item, table-row, figure.
    - Heading-aware path: # / ## / ### maintained as context.
    - Char-based cap with sentence/word fallback; no tokenization.
    - No cross-unit packing by default (preserves meaning for RAG).
    """
    t0 = time.perf_counter()

    # Approximate limits (chars)
    max_chars = _approx_limit_tokens_to_chars(max_tokens)

    # Normalize newlines
    text = re.sub(r"\r\n?", "\n", text).strip()
    lines = text.splitlines()
    n = len(lines)

    # Pre-pass: normalize pseudo headings into ATX (##)
    for i in range(n):
        ln = lines[i]
        if not RE_ATX_ONLY.match(ln) and _is_pseudo_heading(ln):
            lines[i] = _normalize_heading_line(ln)

    # Heading state
    h = ["", "", "", "", "", ""]  # levels 1..6
    def set_heading(level: int, title: str):
        nonlocal h
        h[level-1] = title.strip()
        for k in range(level, 6):
            h[k] = ""
    def path_str() -> str:
        parts = [x for x in h if x]
        return " > ".join(parts)

    chunks: List[str] = []

    # Diagnostics
    total_tables = total_table_rows = total_lists = total_list_items = 0
    total_paragraphs = total_figures = 0

    i = 0
    while i < n:
        ln = lines[i]

        # --- Headings ---
        m = RE_ATX.match(ln)
        if m:
            level = len(m.group(1))
            title = m.group(2)
            set_heading(level, title)
            i += 1
            continue

        # Skip blank lines quickly
        if not ln.strip():
            i += 1
            continue

        # --- Table ---
        if RE_TABLE_LABEL.match(ln):
            label_line = ln.strip()
            i += 1
            # Expect a GitHub Markdown table block next
            tstart = i
            if i + 1 < n and RE_HAS_PIPE.search(lines[i]) and RE_MD_TABLE_DIV.match(lines[i+1]):
                # collect table lines
                i += 2
                while i < n and (RE_HAS_PIPE.search(lines[i]) or not lines[i].strip()):
                    # allow a trailing blank line but stop if next is not a table row
                    if not lines[i].strip() and (i + 1 >= n or not RE_HAS_PIPE.search(lines[i+1])):
                        break
                    i += 1
                tlines = lines[tstart:i]
                header, rows = _parse_md_table(tlines)
                cur_path = path_str() if keep_path_prefix else ""
                if header and rows:
                    total_tables += 1
                    total_table_rows += len(rows)
                    if table_mode in ("row", "hybrid"):
                        # emit one row per chunk (atomic)
                        for row in rows:
                            mapped = "; ".join(f"{h_}: {c}" for h_, c in zip(header, row))
                            row_text = f"{label_line}\n{mapped}"
                            _emit_under_cap_fast(cur_path, row_text, max_chars, chunks)
                    if table_mode in ("block", "hybrid") or include_table_block_with_rows:
                        full_block = label_line + "\n" + "\n".join(tlines)
                        _emit_under_cap_fast(cur_path, full_block, max_chars, chunks)
                else:
                    # fall back: emit as block (unparsed)
                    cur_path = path_str() if keep_path_prefix else ""
                    block = label_line + "\n" + "\n".join(tlines)
                    _emit_under_cap_fast(cur_path, block, max_chars, chunks)
                # consume trailing blank lines
                while i < n and not lines[i].strip():
                    i += 1
                continue
            else:
                # Label without proper table — emit label as paragraph
                cur_path = path_str() if keep_path_prefix else ""
                _emit_under_cap_fast(cur_path, label_line, max_chars, chunks)
                i = tstart
                continue

        # --- Figure ---
        if RE_FIGURE_LABEL.match(ln):
            label_line = ln.strip()
            i += 1
            # The next non-empty paragraph is the figure description (per your rules)
            desc_lines = []
            while i < n and lines[i].strip():
                desc_lines.append(lines[i])
                i += 1
            cur_path = path_str() if keep_path_prefix else ""
            body = label_line + ("\n" + " ".join(desc_lines) if desc_lines else "")
            _emit_under_cap_fast(cur_path, body, max_chars, chunks)
            total_figures += 1
            # consume trailing blanks
            while i < n and not lines[i].strip():
                i += 1
            continue

        # --- List block ---
        if RE_LIST_START.match(ln):
            total_lists += 1
            while i < n and RE_LIST_START.match(lines[i]):
                item_line = lines[i].rstrip()
                cur_path = path_str() if keep_path_prefix else ""
                _emit_under_cap_fast(cur_path, item_line, max_chars, chunks)
                total_list_items += 1
                i += 1
            # consume trailing blanks
            while i < n and not lines[i].strip():
                i += 1
            continue

        # --- Paragraph block (no hard wraps inside; ends at blank or structural start) ---
        pstart = i
        while i < n:
            nxt = lines[i]
            if not nxt.strip():
                break
            if RE_ATX.match(nxt) or RE_LIST_START.match(nxt) or RE_TABLE_LABEL.match(nxt) or RE_FIGURE_LABEL.match(nxt):
                break
            # Break if we detect start of a GitHub table header/divider combo ahead
            if i + 1 < n and RE_HAS_PIPE.search(lines[i]) and RE_MD_TABLE_DIV.match(lines[i+1]):
                break
            i += 1
        para_lines = [ln_.strip() for ln_ in lines[pstart:i]]
        para = " ".join(para_lines).strip()
        if para:
            cur_path = path_str() if keep_path_prefix else ""
            _emit_under_cap_fast(cur_path, para, max_chars, chunks)
            total_paragraphs += 1
        # consume trailing blanks
        while i < n and not lines[i].strip():
            i += 1

    # No cross-unit merges (preserves atomic semantics).
    # Optionally, you could merge only if two consecutive chunks came from the same paragraph split by _emit_under_cap_fast.

    # ---- Summary logs ----
    if debug or retrieval_logger.isEnabledFor(logging.INFO):
        retrieval_logger.info(
            "Chunked (single-pass) → %d chunks | tables=%d rows=%d lists=%d items=%d paras=%d figures=%d",
            len(chunks), total_tables, total_table_rows, total_lists, total_list_items, total_paragraphs, total_figures
        )
        if chunks:
            first = chunks[0]
            retrieval_logger.info("First chunk path=%r preview=%r", _extract_path(first) or "-", _preview(first))
            if len(chunks) > 1:
                ridx = random.randrange(len(chunks))
                rnd = chunks[ridx]
                retrieval_logger.info("Random chunk #%d path=%r preview=%r", ridx, _extract_path(rnd) or "-", _preview(rnd))

    return chunks

# ---------------- Convenience: with metadata (section path) ----------------
def chunk_markdown_financial_with_meta_v2(
    text: str,
    **kwargs
) -> List[Dict[str, Any]]:
    chunks = chunk_markdown_financial_reports(text, **kwargs)
    out: List[Dict[str, Any]] = []
    for c in chunks:
        if c.startswith("[") and "]\n" in c:
            path, _rest = c[1:].split("]\n", 1)
            out.append({"text": c, "section_path": path})
        else:
            out.append({"text": c, "section_path": ""})
    return out

# New: richer metadata variant (non-breaking; optional)
def chunk_markdown_financial_with_meta_v3(
    text: str,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    Adds 'kind' when detectable: 'paragraph'|'list_item'|'table_row'|'table_block'|'figure' (best-effort).
    """
    chunks = chunk_markdown_financial_reports(text, **kwargs)
    out: List[Dict[str, Any]] = []
    for c in chunks:
        path = ""
        body = c
        if c.startswith("[") and "]\n" in c:
            path, body = c[1:].split("]\n", 1)
        kind = "paragraph"
        if body.lstrip().startswith("Table:"):
            # crude heuristic: a single line with mapping => row; if pipes appear => block
            if "|" in body:
                kind = "table_block"
            else:
                kind = "table_row"  # mapping form "Col: Val; ..."
        elif body.lstrip().startswith("Figure:"):
            kind = "figure"
        elif RE_LIST_START.match(body.strip()):
            kind = "list_item"
        out.append({"text": c, "section_path": path, "kind": kind})
    return out

# ---------------- Backwards-compatible aliases ----------------
def chunk_markdown_financial(text: str, **kwargs) -> List[str]:
    return chunk_markdown_financial_reports(text, **kwargs)

def chunk_markdown(text: str) -> List[str]:
    return chunk_markdown_financial_reports(text)
