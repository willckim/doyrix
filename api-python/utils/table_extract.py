# utils/table_extract.py
from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
import re

# --- Title patterns we care about -------------------------------------------------
FIN_TITLE_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("Consolidated Balance Sheets",
     re.compile(r"CONSOLIDATED\s+(BALANCE\s+SHEETS?|STATEMENTS?\s+OF\s+FINANCIAL\s+POSITION)", re.I)),
    ("Consolidated Statements of Operations",
     re.compile(r"CONSOLIDATED\s+STATEMENTS?\s+OF\s+(OPERATIONS|INCOME|LOSS)", re.I)),
    ("Consolidated Statements of Cash Flows",
     re.compile(r"CONSOLIDATED\s+STATEMENTS?\s+OF\s+CASH\s+FLOWS?", re.I)),
    ("Consolidated Statements of Stockholders’ Equity",
     re.compile(r"CONSOLIDATED\s+STATEMENTS?\s+OF\s+(CHANGES\s+IN\s+)?(STOCKHOLDERS’|STOCKHOLDERS'|SHAREHOLDERS’|SHAREHOLDERS')\s+EQUITY", re.I)),
    ("Consolidated Statements of Comprehensive Income",
     re.compile(r"CONSOLIDATED\s+STATEMENTS?\s+OF\s+COMPREHENSIVE\s+INCOME", re.I)),
    # generic fallbacks
    ("Balance Sheet", re.compile(r"\bBALANCE\s+SHEETS?\b", re.I)),
    ("Statement of Operations", re.compile(r"\bSTATEMENTS?\s+OF\s+(OPERATIONS|INCOME|LOSS)\b", re.I)),
    ("Statement of Cash Flows", re.compile(r"\bSTATEMENTS?\s+OF\s+CASH\s+FLOWS?\b", re.I)),
    ("Stockholders' Equity", re.compile(r"(STOCKHOLDERS’|STOCKHOLDERS'|SHAREHOLDERS’|SHAREHOLDERS')\s+EQUITY", re.I)),
]

# A broad “table-ish” page gate so we don’t scan every page in huge filings
_TABLE_GATE = re.compile(
    r"("
    r"consolidated\s+statements?.{0,60}(operations|income|loss|cash\s+flows?|comprehensive\s+income|stockholders[’']\s+equity)|"
    r"consolidated\s+balance\s+sheets?|"
    r"statements?.{0,60}(operations|income|loss|cash\s+flows?|comprehensive\s+income|stockholders[’']\s+equity)|"
    r"balance\s+sheets?"
    r")",
    re.I | re.S
)

# Numeric-ish token (amounts, percents, negatives in parentheses)
_NUM_TOKEN = re.compile(r"\(?\$?-?\d[\d,]*\.?\d*%?\)?")

# Common year tokens and period headers often present in table headers
_PERIOD_HINT = re.compile(
    r"(years?\s+ended|year\s+ended|as\s+of|three\s+months|twelve\s+months|six\s+months|nine\s+months|"
    r"dec(ember)?|sep(tember)?|mar(ch)?|jun(e)?|"
    r"201\d|202\d)",
    re.I
)

# --- tiny text normalizer ---------------------------------------------------------
def _normalize_text(t: str) -> str:
    # NBSP, thin/figure spaces → normal space; strip soft hyphen; collapse multiple spaces
    t = (t or "").replace("\xa0", " ").replace("\u2009", " ").replace("\u2007", " ").replace("\u202f", " ").replace("\xad", "")
    t = re.sub(r"[ \t]+", " ", t)
    return t

# --- numeric helpers --------------------------------------------------------------
def _is_numeric_cell(s: str) -> bool:
    if s is None:
        return False
    ss = s.strip()
    if ss in {"", "-", "—", "–"}:
        return True
    ss = ss.replace(",", "")
    ss = ss.replace("$", "")
    ss = ss.strip()
    if ss.startswith("(") and ss.endswith(")"):
        ss = ss[1:-1]
    if ss.endswith("%"):
        ss = ss[:-1]
    try:
        float(ss)
        return True
    except Exception:
        return False

def _numeric_column_indices(rows: List[List[str]], min_ratio: float = 0.55) -> List[int]:
    if not rows:
        return []
    width = max(len(r) for r in rows)
    idxs: List[int] = []
    for j in range(width):
        cells = [r[j] if j < len(r) else "" for r in rows]
        if not cells:
            continue
        num = sum(1 for c in cells if _is_numeric_cell(c))
        if num / len(cells) >= min_ratio:
            idxs.append(j)
    return idxs

# --- row/col parsing helpers ------------------------------------------------------
def _split_cols(line: str) -> List[str]:
    """
    Split a line into columns by tabs or 2+ spaces.
    If that yields <3 cols, try a numeric-tail split to peel off right-aligned amounts.
    """
    if "\t" in line:
        cols = [c.strip() for c in line.split("\t")]
    else:
        parts = [c.strip() for c in re.split(r"\s{2,}", line)]
        if len(parts) >= 3:
            cols = parts
        else:
            # Try to peel off numeric tokens at the end (right-aligned columns)
            nums = re.findall(_NUM_TOKEN, line)
            if len(nums) >= 2:
                first_num_start = line.find(nums[0])
                lead = line[:first_num_start].strip()
                tail = [n.strip() for n in nums]
                cols = ([lead] if lead else []) + tail
            else:
                cols = parts
    return [c for c in cols if c]

def _count_numeric_tokens(s: str) -> int:
    return len(_NUM_TOKEN.findall(s or ""))

def _looks_table_line(line: str) -> bool:
    """Heuristic: table row if 3+ columns OR at least two numeric tokens on the line."""
    cols = _split_cols(line)
    if len(cols) >= 3:
        return True
    return _count_numeric_tokens(line) >= 2

def _non_numeric_ratio(values: List[str]) -> float:
    if not values:
        return 1.0
    non_num = 0
    for c in values:
        cc = (c or "").replace(",", "").replace("(", "").replace(")", "").replace("$", "").strip().rstrip("%")
        if cc in {"—", "-", "–", ""}:
            continue
        try:
            float(cc)
        except Exception:
            non_num += 1
    return non_num / max(1, len(values))

def _clean_grid(grid: List[List[str]]) -> List[List[str]]:
    """Drop all-empty rows/cols; trim cells; normalize row widths."""
    rows = [[(c or "").strip() for c in r] for r in grid if any((c or "").strip() for c in r)]
    if not rows:
        return []
    max_w = max(len(r) for r in rows)
    rows = [r + [""] * (max_w - len(r)) for r in rows]
    keep_idx = []
    for j in range(max_w):
        if any(((r[j] if j < len(r) else "") or "").strip() for r in rows):
            keep_idx.append(j)
    return [[(r[j] if j < len(r) else "").strip() for j in keep_idx] for r in rows]

def _merge_two_line_header(rows: List[List[str]]) -> Tuple[List[str], List[List[str]]]:
    """
    If the first two rows are mostly non-numeric (labels) OR contain period hints,
    merge them into a single header. Else use first row as header.
    """
    if not rows:
        return [], []
    if len(rows) >= 2:
        r0, r1 = rows[0], rows[1]
        r0_txt = " ".join(r0)
        r1_txt = " ".join(r1)
        headerish = (_non_numeric_ratio(r0) + _non_numeric_ratio(r1)) / 2 >= 0.6
        periodish = _PERIOD_HINT.search(r0_txt) or _PERIOD_HINT.search(r1_txt)
        if headerish or periodish:
            merged: List[str] = []
            for a, b in zip(r0, r1):
                a = a.strip()
                b = b.strip()
                if a and b and a != b:
                    merged.append(f"{a} {b}")
                else:
                    merged.append(a or b)
            if len(r0) != len(r1):
                tail = r0[len(merged):] if len(r0) > len(r1) else r1[len(merged):]
                merged.extend(t.strip() for t in tail)
            return merged, rows[2:]
    return rows[0], rows[1:]

def _dedup_adjacent(rows: List[List[str]]) -> List[List[str]]:
    out: List[List[str]] = []
    prev: Optional[List[str]] = None
    for r in rows:
        if prev is None or r != prev:
            out.append(r)
        prev = r
    return out

def _unwrap_wrapped_rows(rows: List[List[str]]) -> List[List[str]]:
    """
    Merge lines where only the first column has text (wrapped account names) into the previous row's first cell.
    """
    out: List[List[str]] = []
    for r in rows:
        first = (r[0] if r else "").strip()
        others = [c.strip() for c in r[1:]]
        if out and first and not any(others):
            # append to prior row's first cell
            out[-1][0] = (out[-1][0] + " " + first).strip()
        else:
            out.append(r)
    return out

def _infer_title(text: str) -> Optional[str]:
    if not text:
        return None
    head = "\n".join(text.splitlines()[:60])  # look a bit deeper near top
    for label, pat in FIN_TITLE_PATTERNS:
        if pat.search(head):
            return label
    # fallback: most “shouty” line near the top with balance/statement keyword
    for ln in head.splitlines():
        ln_clean = ln.strip()
        if len(ln_clean) >= 12 and ln_clean.upper() == ln_clean and any(w in ln_clean for w in ["BALANCE", "STATEMENT", "STATEMENTS"]):
            return ln_clean
    return None

# --- segmentation of table blocks -------------------------------------------------
def _segment_table_blocks(text: str, min_rows: int = 3) -> List[List[List[str]]]:
    """
    Split page text into multiple table-like blocks (list of grids).
    A block is a run of “table-ish” lines separated by ≤1 non-table line.
    """
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    blocks: List[List[List[str]]] = []
    buf: List[List[str]] = []
    gap = 0

    def flush():
        nonlocal buf
        if len(buf) >= min_rows:
            grid = _clean_grid(buf)
            if grid and len(grid) >= min_rows:
                blocks.append(grid)
        buf = []

    for ln in lines:
        if ln.strip() == "":
            gap += 1
            if gap > 1 and buf:
                flush()
            continue
        if _looks_table_line(ln):
            buf.append(_split_cols(ln))
            gap = 0
        else:
            gap += 1
            if gap > 1 and buf:
                flush()
    if buf:
        flush()
    return blocks

# --- main API --------------------------------------------------------------------
def extract_tables_from_pages(pages: List[Dict[str, Any]], max_rows: int = 120) -> List[Dict[str, Any]]:
    """
    Very-lightweight “table-ish” extractor using text layout only.
    Returns a list of {title, header, rows, pages}.
    - Processes multiple table blocks per page
    - Accepts pages as [{'page': int, 'text': str}]
    """
    out: List[Dict[str, Any]] = []

    for page in pages:
        pg = page.get("page")
        txt: str = _normalize_text(page.get("text") or "")
        if not txt:
            continue

        # Only attempt pages that look like financial statement pages
        if not _TABLE_GATE.search(txt):
            continue

        title = _infer_title(txt) or "Financial table (detected)"
        blocks = _segment_table_blocks(txt, min_rows=3)
        if not blocks:
            continue

        for grid in blocks:
            if not grid or len(grid) < 2 or len(grid[0]) < 2:
                continue

            header, body = _merge_two_line_header(grid)
            body = [r for r in _dedup_adjacent(body) if any((c or "").strip() for c in r)]
            body = _unwrap_wrapped_rows(body)

            # Quality: require at least 2 numeric columns across the body to avoid narrative note snippets
            num_cols = _numeric_column_indices(body, min_ratio=0.55)
            if len(num_cols) < 2:
                continue

            # Prefer headers that look like periods/years; if not, still keep if numeric quality is strong
            header_text = " ".join(header) if header else ""
            if header and not _PERIOD_HINT.search(header_text):
                # if header lacks period hints, require stronger numeric signal
                if len(num_cols) < 3 and len(body) < 6:
                    continue

            # Cap rows to keep HTML manageable
            tb = body[:max_rows]

            out.append({
                "title": title,
                "header": header,
                "rows": tb,
                "pages": [pg] if isinstance(pg, int) else [],
            })

    return out
