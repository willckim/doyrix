# utils/parse_pdf.py
import time
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Union
import fitz

from metrics import extract_kpis
from utils.anchors import find_sec_anchors, slice_sections
from utils.risk_extract import extract_top_risks_from_item_1a

# OPTIONAL modules — provide graceful fallbacks if missing
try:
    from utils.table_extract import extract_tables_from_pages
except Exception:  # pragma: no cover
    extract_tables_from_pages = None  # we'll guard usage

try:
    from utils.market_risk import extract_market_risk          # expects sections list
except Exception:  # pragma: no cover
    def extract_market_risk(_sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {}

try:
    from utils.controls_auditor import extract_controls_auditor # expects sections list
except Exception:  # pragma: no cover
    def extract_controls_auditor(_sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {}

try:
    from utils.legal_extractors import extract_legal_items      # expects sections list
except Exception:  # pragma: no cover
    def extract_legal_items(_sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {"items": []}

try:
    from utils.capital_structure import extract_capital_structure
except Exception:  # pragma: no cover
    def extract_capital_structure(_pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {}

# NEW: Non-GAAP extraction (optional)
try:
    from utils.non_gaap import extract_non_gaap                # expects sections list
except Exception:  # pragma: no cover
    def extract_non_gaap(_sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return []


def _extract_pages(path: Union[str, Path]) -> List[Dict[str, Any]]:
    doc = fitz.open(str(path))
    # Preserve whitespace / ligatures if available (older PyMuPDF may not have these flags)
    flags = 0
    for name in ("TEXT_PRESERVE_LIGATURES", "TEXT_PRESERVE_WHITESPACE"):
        flags |= getattr(fitz, name, 0)

    pages: List[Dict[str, Any]] = []
    for i, page in enumerate(doc):
        try:
            txt = page.get_text("text", flags=flags)
        except TypeError:
            # Fallback for older versions that don't support flags arg
            txt = page.get_text("text")
        if not (txt or "").strip():
            txt = page.get_text("text")
        pages.append({"page": i + 1, "text": txt})
    return pages


def _citations_from_pages(pages: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    return [
        {"page": p["page"], "snippet": (p.get("text") or "").strip().replace("\n", " ")[:240]}
        for p in pages[:limit]
    ]


def _get_section_by_item(sections: List[Dict[str, Any]], item_prefix: str):
    ip = item_prefix.lower().strip()
    for s in sections:
        if (s.get("title") or "").lower().startswith(ip):
            return s
    return None


# --- Item 7/7A/8 rescue if anchors miss them -------------------------------------
_ITEM_RE = re.compile(r"(?im)^\s*item\s+(?P<num>7a|7|8)\.?\s*(?P<title>[^\n]{0,120})")

def _find_item_page(pages: List[Dict[str, Any]], item: str) -> Optional[int]:
    it = item.lower()
    for p in pages:
        text = p.get("text") or ""
        for m in _ITEM_RE.finditer(text):
            if m.group("num").lower() == it:
                return p["page"]
    return None

def _inject_synthetic_sections(sections: List[Dict[str, Any]], pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create minimal sections for Items 7 / 7A / 8 if missing, to unblock MD&A, 7A, and financial table scans."""
    titles_lower = [(s.get("title") or "").lower() for s in sections]
    want7  = all(not t.startswith("item 7.") for t in titles_lower)
    want7a = all(not t.startswith("item 7a") for t in titles_lower)
    want8  = all(not t.startswith("item 8.") for t in titles_lower)

    if not (want7 or want7a or want8):
        return sections

    by_page = {p["page"]: p for p in pages}
    last_page = max(by_page) if by_page else 1

    p7  = _find_item_page(pages, "7")
    p7a = _find_item_page(pages, "7a")
    p8  = _find_item_page(pages, "8")

    def make(title: str, start: Optional[int], end: Optional[int]):
        if not start or not end or start > end:
            return None
        content = [{"page": i, "snippet": (by_page[i].get("text") or "")[:1200]}
                   for i in range(start, end + 1) if i in by_page]
        return {"title": title, "start_page": start, "end_page": end, "content": content}

    new = list(sections)

    if want7 and p7:
        end = min([x for x in [p7a, p8] if x] or [last_page]) - 1
        end = max(end, p7)
        sec = make(
            "Item 7. Management’s Discussion and Analysis of Financial Condition and Results of Operations",
            p7, end
        )
        if sec: new.append(sec)

    if want7a and p7a:
        end = (p8 or last_page) - 1
        end = max(end, p7a)
        sec = make(
            "Item 7A. Quantitative and Qualitative Disclosures About Market Risk",
            p7a, end
        )
        if sec: new.append(sec)

    if want8 and p8:
        sec = make(
            "Item 8. Financial Statements and Supplementary Data",
            p8, last_page
        )
        if sec: new.append(sec)

    new.sort(key=lambda s: s.get("start_page", 10**9))
    return new


def parse_pdf_with_citations(
    path: Union[str, Path],
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
) -> Dict[str, Any]:

    # Non-PDF fallback
    if not str(path).lower().endswith(".pdf"):
        if progress_callback:
            progress_callback({"section": "Document", "progress": 100})
        return {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "doc_meta": {"pages": 1, "doc_type": "unknown", "anchors_found": 0},
            "sections": [{
                "title": "Document", "start_page": 1, "end_page": 1,
                "content": [{"page": 1, "snippet": "(non-PDF preview)"}]
            }],
            "sections_map": {"Document": {"pages": [1]}},
            "pages": [{"page": 1, "text": "(non-PDF)"}],
            "citations": [{"page": 1, "snippet": "(non-PDF)"}],
            "derived": {
                "kpis": [], "segments": [], "risks": [], "financials": [],
                "non_gaap": [], "market_risk": {}, "auditor": {}, "legal": {}
            },
            "capital_structure": {}
        }

    # 1) Pages
    pages = _extract_pages(path)

    # 2) Anchors + sections
    anchor_input = [(p["page"], p["text"]) for p in pages]  # find_sec_anchors expects (page_num, text)
    anchors = find_sec_anchors(anchor_input)
    sections = slice_sections(pages, anchors)

    # 2b) Rescue Items 7 / 7A / 8 if the anchor pass missed them
    sections = _inject_synthetic_sections(sections, pages)

    # Optional progress
    if progress_callback and sections:
        n = len(sections)
        for i, s in enumerate(sections, 1):
            progress_callback({"section": s["title"], "progress": int(round(i / n * 100))})

    # 3) Base analysis
    analysis: Dict[str, Any] = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "doc_meta": {
            "pages": max((p["page"] for p in pages), default=1),
            "doc_type": "10-K/10-Q detected" if anchors else "generic",
            "anchors_found": len(anchors),
        },
        "sections": sections,
        "sections_map": {s["title"]: {"pages": list(range(s["start_page"], s["end_page"] + 1))} for s in sections},
        "pages": pages,
        "citations": _citations_from_pages(pages),
        "derived": {}
    }

    # 4) KPIs / segments — pass sections_map as 'sections' for metrics.py compatibility
    try:
        kpi_payload = dict(analysis)
        kpi_payload["sections"] = analysis.get("sections_map", {})
        analysis["derived"].update(extract_kpis(kpi_payload))
    except Exception as e:
        analysis["derived"].update({"kpis": [], "segments": [], "_kpi_error": str(e)})

    # 5) Risks (Item 1A)
    try:
        analysis["derived"]["risks"] = extract_top_risks_from_item_1a(sections)
    except Exception as e:
        analysis["derived"]["risks"] = []
        analysis["derived"]["_risks_error"] = str(e)

    # 6) Financials (Item 8) — try Item 8 first, then fall back to scanning all pages
    try:
        fin_sec = _get_section_by_item(sections, "item 8")
        financials: List[Dict[str, Any]] = []
        if extract_tables_from_pages:
            if fin_sec:
                span_pages = [p for p in pages if fin_sec["start_page"] <= p["page"] <= fin_sec["end_page"]]
                financials = extract_tables_from_pages(span_pages) or []
            # Fallback: if Item 8 didn’t yield tables, scan all pages (the extractor has its own gate)
            if not financials:
                financials = (extract_tables_from_pages(pages) or [])[:4]
        analysis["derived"]["financials"] = financials
    except Exception as e:
        analysis["derived"]["financials"] = []
        analysis["derived"]["_financials_error"] = str(e)

    # 7) Non-GAAP reconciliations — pass whole sections list
    try:
        analysis["derived"]["non_gaap"] = extract_non_gaap(sections) or []
    except Exception as e:
        analysis["derived"]["non_gaap"] = []
        analysis["derived"]["_non_gaap_error"] = str(e)

    # 8) Market Risk (Item 7A) — pass whole sections list
    try:
        analysis["derived"]["market_risk"] = extract_market_risk(sections) or {}
    except Exception as e:
        analysis["derived"]["market_risk"] = {}
        analysis["derived"]["_market_risk_error"] = str(e)

    # 9) Controls & Auditor (Item 9A) — pass whole sections list
    try:
        analysis["derived"]["auditor"] = extract_controls_auditor(sections) or {}
    except Exception as e:
        analysis["derived"]["auditor"] = {}
        analysis["derived"]["_auditor_error"] = str(e)

    # 10) Legal / Contingencies (Item 3) — pass whole sections list
    try:
        analysis["derived"]["legal"] = extract_legal_items(sections) or {"items": []}
    except Exception as e:
        analysis["derived"]["legal"] = {"items": []}
        analysis["derived"]["_legal_error"] = str(e)

    # 11) Capital structure — scan everything
    try:
        analysis["capital_structure"] = extract_capital_structure(pages) or {}
    except Exception as e:
        analysis["capital_structure"] = {}
        analysis["derived"]["_capital_structure_error"] = str(e)

    return analysis
