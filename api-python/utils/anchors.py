# utils/anchors.py
import re
from typing import List, Dict, Tuple, Any, Sequence, Union

# Line-anchored SEC item matcher (case-insensitive, multiline)
SEC_ITEM_RE = re.compile(r'(?im)^\s*Item\s+(?P<num>\d{1,2}[A-Z]?)\.\s+(?P<title>[^\n]+?)\s*$')

# Looks like "..... 45" at the end of a line
_TOC_LINE_RE = re.compile(r'\.{3,}\s*\d{1,4}\s*$')

def looks_like_toc(text: str) -> bool:
    t = text.lower()
    return ("table of contents" in t) or (t.count(" . ") > 10) or (t.count(".....") > 8)

def _is_probable_toc_line(line: str) -> bool:
    return bool(_TOC_LINE_RE.search(line))

def _is_dense_item_page(page_text: str, threshold: int = 5) -> bool:
    # a page listing many "Item X." lines is likely an index
    return len(list(SEC_ITEM_RE.finditer(page_text))) >= threshold

def _normalize_pages(
    pages: Sequence[Union[Tuple[int, str], Dict[str, Any]]]
) -> List[Tuple[int, str]]:
    """Accept (page_num, text) tuples OR {'page': n, 'text': '...'} dicts."""
    norm: List[Tuple[int, str]] = []
    for p in pages:
        if isinstance(p, tuple):
            page_num, page_text = p
        else:
            page_num = int(p.get("page", 0))
            page_text = str(p.get("text", "") or "")
        norm.append((page_num, page_text))
    return norm

def find_sec_anchors(
    pages: Sequence[Union[Tuple[int, str], Dict[str, Any]]],
    skip_toc_pages_up_to: int = 50
) -> List[Dict[str, Any]]:
    """
    pages: list of (page_num, page_text) OR [{"page": n, "text": "..."}]
    returns: [{"item": "7A", "title": "...", "page": 123, "pos": 456}, ...]
    """
    pages_norm = _normalize_pages(pages)
    seen = set()
    anchors: List[Dict[str, Any]] = []

    for page_num, page_text in pages_norm:
        # Skip classic TOC near the front
        if page_num <= skip_toc_pages_up_to and looks_like_toc(page_text):
            continue
        # Skip pages that are basically an index of many items
        if _is_dense_item_page(page_text):
            continue

        # Iterate matches, but filter out TOC-like lines
        for m in SEC_ITEM_RE.finditer(page_text):
            # Grab the exact matched line (for TOC-line filtering)
            line_start = page_text.rfind("\n", 0, m.start()) + 1
            line_end = page_text.find("\n", m.end())
            if line_end == -1:
                line_end = len(page_text)
            matched_line = page_text[line_start:line_end].strip()

            if _is_probable_toc_line(matched_line):
                continue

            num = m.group("num").upper()
            if num in seen:  # first real hit per item wins
                continue
            seen.add(num)

            anchors.append({
                "item": num,
                "title": m.group("title").strip(),
                "page": page_num,
                "pos": m.start()
            })

    anchors.sort(key=lambda a: (a["page"], a["pos"]))
    return anchors

def spans_from_anchors(anchors: List[Dict[str, Any]], last_page: int) -> List[Dict[str, Any]]:
    """
    returns: [{"item":"7A","title":"Item 7A. ...","start_page":p1,"end_page":p2}, ...]
    """
    spans: List[Dict[str, Any]] = []
    for i, a in enumerate(anchors):
        start_p = a["page"]
        end_p = anchors[i + 1]["page"] - 1 if i + 1 < len(anchors) else last_page
        if end_p < start_p:
            end_p = start_p
        spans.append({
            "item": a["item"],
            "title": f"Item {a['item']}. {a['title']}",
            "start_page": start_p,
            "end_page": end_p
        })
    return spans

def slice_sections(
    pages: Sequence[Dict[str, Any]],
    anchors: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Build rich sections from anchors; each section spans from its anchor page
    through the page before the next anchor, and includes per-page content.

    pages: [{"page": int, "text": str}, ...]
    anchors: output of find_sec_anchors(...)

    returns: [{
      "title": str, "start_page": int, "end_page": int,
      "content": [{"page": int, "snippet": str, "full": str}, ...]
    }, ...]
    """
    pages_list: List[Dict[str, Any]] = list(pages)
    if not anchors:
        # Fallback: single "Document" section (first few pages for preview)
        content = [{"page": p["page"], "snippet": (p.get("text") or "")[:1200]}
                   for p in pages_list[:8]]
        return [{
            "title": "Document",
            "start_page": 1,
            "end_page": pages_list[-1]["page"] if pages_list else 1,
            "content": content
        }]

    spans = spans_from_anchors(anchors, last_page=pages_list[-1]["page"] if pages_list else 1)
    page_by_num = {p["page"]: p for p in pages_list}

    sections: List[Dict[str, Any]] = []
    for span in spans:
        start_page = span["start_page"]
        end_page = span["end_page"]
        content_items = []
        for n in range(start_page, end_page + 1):
            p = page_by_num.get(n)
            if not p:
                continue
            t = (p.get("text") or "").strip()
            if not t:
                continue
            content_items.append({
                "page": n,
                "snippet": t[:1200],
                "full": t,
            })
        if content_items:
            sections.append({
                "title": span["title"],
                "start_page": start_page,
                "end_page": end_page,
                "content": content_items,
            })
    return sections
