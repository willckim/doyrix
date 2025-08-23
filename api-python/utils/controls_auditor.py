import re
from typing import Dict, Any, List

RE_EFFECTIVE = re.compile(r"\b(disclosure controls and procedures|internal control over financial reporting).*?\b(effective|not effective)\b", re.I|re.S)
RE_WEAKNESS  = re.compile(r"\bmaterial weakness(es)?\b", re.I)
RE_AUDITOR   = re.compile(r"\b(PricewaterhouseCoopers|PwC|Deloitte|KPMG|Ernst\s*&\s*Young|Grant Thornton|BDO)\b", re.I)

def extract_controls_auditor(sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    sec = next((s for s in sections if (s.get("title") or "").lower().startswith("item 9a")), None)
    if not sec:
        # sometimes Item 9 carries the language; include it too
        sec = next((s for s in sections if (s.get("title") or "").lower().startswith("item 9.")), None)
    if not sec:
        return {}

    text = " ".join((c.get("full") or c.get("snippet") or "") for c in sec.get("content", []))
    res: Dict[str, Any] = {"pages": [sec.get("start_page")] if sec.get("start_page") else []}

    m = RE_EFFECTIVE.search(text)
    if m:
        res["opinion"] = m.group(2).lower()  # "effective" or "not effective"

    res["material_weakness"] = bool(RE_WEAKNESS.search(text))
    aud = RE_AUDITOR.search(text)
    if aud:
        res["auditor_name"] = aud.group(1)

    return res
