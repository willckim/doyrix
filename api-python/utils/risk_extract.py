# utils/risk_extract.py
from typing import Dict, Any, List, Tuple, Optional
import re

_SENTENCE_RE = re.compile(r"(?s)(.*?\.)(\s+|$)")
_RISK_CUES = [
    "risk", "uncertain", "uncertainty", "could", "may", "might",
    "adverse", "material adverse", "exposure", "vulnerab", "depend",
    "volatil", "fluctuat", "subject to", "regulatory", "litigation",
    "supply", "cost pressures", "competition", "macroeconomic"
]

def _sentences_with_pages(section_content: List[Dict[str, Any]]) -> List[Tuple[int, str]]:
    out: List[Tuple[int, str]] = []
    for item in section_content or []:
        txt = (item.get("full") or item.get("snippet") or "").strip()
        page = item.get("page")
        if not txt or not page:
            continue
        for m in _SENTENCE_RE.finditer(txt):
            s = m.group(1).strip()
            if s:
                out.append((page, s))
    return out

def extract_top_risks_from_item_1a(sections: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    one_a = next((s for s in sections if (s.get("title") or "").lower().startswith("item 1a")), None)
    if not one_a:
        return []
    scored: List[Tuple[float, int, str]] = []
    for page, sent in _sentences_with_pages(one_a.get("content") or []):
        s_l = sent.lower()
        score = sum(1.0 for cue in _RISK_CUES if cue in s_l)
        score += min(len(sent)/200.0, 1.0)
        if len(sent) < 40: score -= 0.25
        if score > 0.8:
            scored.append((score, page, sent))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [{"text": sent, "page": page} for _, page, sent in scored[:limit]]
