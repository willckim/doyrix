import re
from typing import Dict, Any, List

_SENT = re.compile(r"(?s)(.*?\.)(\s+|$)")

def extract_legal_items(sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    sec = next((s for s in sections if (s.get("title") or "").lower().startswith("item 3")), None)
    if not sec:
        return {"items": []}
    text = " ".join((c.get("full") or c.get("snippet") or "") for c in sec.get("content", []))
    bullets: List[Dict[str, Any]] = []

    sents = [m.group(1).strip() for m in _SENT.finditer(text)]
    # Grab up to 3 meaningful sentences
    for s in sents:
        if len(s) < 60: 
            continue
        if any(k in s.lower() for k in ["legal proceeding", "litigation", "lawsuit", "settlement", "investigation", "regulatory"]):
            bullets.append({"title": "Legal Proceeding", "summary": s, "pages": [sec.get("start_page")]})
            if len(bullets) >= 3:
                break

    if not bullets and sents:
        bullets = [{"title": "Legal Proceedings", "summary": sents[0], "pages": [sec.get("start_page")]}]

    return {"items": bullets}
