from typing import Dict, Any, List, Optional, Tuple
import re

Number = Optional[float]

KPI_NAMES = {
    "revenue": [r"net\s+sales", r"revenue"],
    "net_income": [r"net\s+income", r"net\s+earnings"],
    "eps": [r"earnings\s+per\s+share", r"eps"],
    "free_cash_flow": [r"free\s+cash\s+flow"],
    "cash": [r"cash\s+and\s+cash\s+equivalents", r"cash\s+and\s+cash-equivalents"],
}

NUM_RE = re.compile(r"\$?\(?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)\)?")


def _to_float(s: str) -> Number:
    try:
        s = s.replace(",", "")
        neg = s.startswith("(") and s.endswith(")")
        s = s.strip("()$")
        v = float(s)
        return -v if neg else v
    except Exception:
        return None


def extract_kpis(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Best-effort scrape of KPIs from MD&A and Financial Statements.
    Expects `doc` shape to include:
      - doc["sections"]: { section_title: {"pages": [int,...]}, ... }
      - doc["pages"]: [ {"page": int, "text": str}, ... ]
    Returns: {"kpis":[{name,value,unit,yoy,qoq,pages:[]}], "segments": []}
    """
    kpis: List[Dict[str, Any]] = []

    sections = doc.get("sections", {})
    target_keys = [
        "Item 7. MANAGEMENT’S DISCUSSION AND ANALYSIS",
        "Item 8. FINANCIAL STATEMENTS",
        "Consolidated Statements",
    ]

    # Collect likely pages to scan
    pages_to_scan: List[int] = []
    for key, val in sections.items():
        if any(tk.lower() in key.lower() for tk in target_keys):
            if isinstance(val, dict):
                pages_to_scan += val.get("pages", [])
    pages_to_scan = sorted(set(pages_to_scan))

    # Build page→text map
    text_by_page: Dict[int, str] = {}
    for p in doc.get("pages", []):
        if isinstance(p, dict) and isinstance(p.get("page"), int):
            text_by_page[p["page"]] = p.get("text", "")

    def scan_for(term_patterns: List[str], pages: List[int]) -> Tuple[Number, List[int]]:
        hits: List[Tuple[float, int]] = []
        for pn in pages:
            t = text_by_page.get(pn, "")
            if not t:
                continue
            if any(re.search(pat, t, re.I) for pat in term_patterns):
                lines = [ln for ln in t.splitlines() if any(re.search(pat, ln, re.I) for pat in term_patterns)]
                for ln in lines:
                    m = NUM_RE.search(ln)
                    if m:
                        val = _to_float(m.group(1))
                        if val is not None:
                            hits.append((val, pn))
        if hits:
            val, _ = hits[-1]  # assume last is current period
            return val, [h[1] for h in hits]
        return None, []

    for name, pats in KPI_NAMES.items():
        val, pages = scan_for(pats, pages_to_scan)
        if val is not None:
            kpis.append({
                "name": name,
                "value": val,
                "unit": "USD",
                "yoy": None,  # compute later once prior column parsed
                "qoq": None,  # for 10-Q only
                "pages": pages,
            })

    return {"kpis": kpis, "segments": []}
