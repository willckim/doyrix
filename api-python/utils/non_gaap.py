# utils/non_gaap.py
from __future__ import annotations
import re
from typing import Dict, Any, List, Tuple, Optional

# --- Headings & boundaries --------------------------------------------------------

# Lines that likely start a Non-GAAP / reconciliation block
HEAD_RE = re.compile(
    r"""(?ix)
    ^\s*
    (?:                               # typical headings
        (?:non[\-\s]?gaap) .* (?:reconcil(?:iation|e)) |
        (?:reconcil(?:iation|e)) \s+ of \s+ (?:gaap|non[\-\s]?gaap) .* |
        (?:non[\-\s]?gaap) \s+ (?:financial \s+ measures|measures)
    ).{0,160}$
    """
)

# Section break or another big heading (stop capturing on these)
SECTION_BREAK_RE = re.compile(
    r"""(?imx)
    ^\s*item\s+\d{1,2}[A-Z]?\.\b |            # SEC Item headers
    ^\s*(?:part\s+[ivx]+|table\s+of\s+contents)\b |
    ^\s*[A-Z0-9][A-Z0-9 \-,'/&()]{10,}\s*$    # shouty line/major header heuristic
    """
)

# Try to detect a period in a heading (e.g., "for the year ended December 31, 2024")
PERIOD_RE = re.compile(
    r"""(?i)\bfor\s+the\s+(?:three|six|nine|twelve|year|quarter|month|months|period)
        \s+ (?:ended|ending)\s+ [A-Za-z]+\s+\d{1,2},\s+\d{4}\b""",
)

# Pull a likely metric from a heading (e.g., "Adjusted EBITDA", "Net Income", etc.)
METRIC_HINTS = [
    r"adjusted\s+ebitda",
    r"ebitda",
    r"net\s+income",
    r"net\s+loss",
    r"operating\s+income",
    r"operating\s+loss",
    r"gross\s+profit",
    r"gross\s+margin",
    r"free\s+cash\s+flow",
    r"cash\s+flows?",
    r"revenue",
    r"earnings\s+per\s+share|eps",
]
METRIC_INFER_RE = re.compile(r"(?i)(" + r"|".join(METRIC_HINTS) + r")")

# --- Row parsing -----------------------------------------------------------------

# Split a label/value line. Use the LAST numeric-ish token as the value.
# Handles $, %, commas, parentheses (for negatives), leading/trailing whitespace, etc.
LINE_VALUE_RE = re.compile(
    r"""(?mx)
    ^\s*
    (?P<label>[A-Za-z].{0,120}?)      # reasonably short label starting with a letter
    \s{2,}                            # 2+ spaces or tab-like gap
    (?P<rest>.+?)\s*$                 # take the rest; we'll pick the last numeric token
    """
)

NUM_TOKEN_RE = re.compile(
    r"""(?x)
    (?:
        \$?\(?-?[\d,]*\.?\d+\)?%?     # e.g., 1,234  (1,234) -123  45.6%  $1,234
    )
    """
)

def _last_numeric_token(text: str) -> Optional[str]:
    nums = NUM_TOKEN_RE.findall(text)
    if not nums:
        return None
    return nums[-1].strip()

def _parse_block_lines(lines: List[str]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for ln in lines:
        m = LINE_VALUE_RE.match(ln)
        if not m:
            continue
        label = m.group("label").strip(" :\u2013\u2014-")  # trim punctuation and dashes
        val_text = m.group("rest")
        val = _last_numeric_token(val_text)
        if not val:
            continue
        rows.append({"label": label, "value": val})
    return rows

# --- Block extraction -------------------------------------------------------------

def _collect_blocks_from_text(text: str) -> List[Tuple[str, List[str]]]:
    """
    Return list of (heading, lines) blocks from a single page's text.
    We detect a heading via HEAD_RE, then accumulate following lines
    until an obvious section break or a new heading.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    i = 0
    blocks: List[Tuple[str, List[str]]] = []
    n = len(lines)

    while i < n:
        # find the next heading
        if not HEAD_RE.match(lines[i]):
            i += 1
            continue

        heading = lines[i].strip()
        i += 1
        body: List[str] = []

        while i < n:
            ln = lines[i]
            # Stop if we hit a new major heading or SEC "Item X." line
            if HEAD_RE.match(ln) or SECTION_BREAK_RE.match(ln):
                break
            # Otherwise, accumulate
            body.append(ln)
            i += 1

        # Clean trailing empties
        while body and not body[-1].strip():
            body.pop()

        if body:
            blocks.append((heading, body))

    return blocks

def _infer_metric_and_period(heading: str) -> Tuple[str, str]:
    metric = "Non-GAAP Reconciliation"
    period = ""

    if heading:
        m = METRIC_INFER_RE.search(heading)
        if m:
            metric = m.group(1).strip().title()

        p = PERIOD_RE.search(heading)
        if p:
            period = p.group(0)

    return metric, period

# --- Public API ------------------------------------------------------------------

def extract_non_gaap(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Scan section content for Non-GAAP / reconciliation blocks and return a list of:
      {
        "metric": str,
        "period": str,
        "recon": [ {"label": str, "value": str}, ... ],
        "pages": [int, ...]
      }
    The parser works per page, so each block references the page it was found on.
    """
    results: List[Dict[str, Any]] = []

    for s in sections or []:
        for item in s.get("content", []):
            page = item.get("page")
            txt = (item.get("full") or item.get("snippet") or "") or ""
            if not txt.strip():
                continue

            # Find one or more reconciliation blocks on this page
            blocks = _collect_blocks_from_text(txt)
            for heading, body_lines in blocks:
                rows = _parse_block_lines(body_lines)
                if not rows:
                    # Some reconciliations are laid out as true tables (not line-value).
                    # We skip empty bodies here; table extractor (if enabled) will help elsewhere.
                    continue
                metric, period = _infer_metric_and_period(heading)
                results.append({
                    "metric": metric,
                    "period": period,
                    "recon": rows,
                    "pages": [page] if isinstance(page, int) else [],
                })

    return results
