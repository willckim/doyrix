import re
from typing import Dict, Any, List

_KEYS = {
    "foreign_currency": ["foreign currency", "fx", "exchange rate", "currency risk"],
    "interest_rate": ["interest rate", "rates", "duration", "sensitivity"],
    "commodity": ["commodity", "raw material", "lithium", "nickel", "cobalt"],
    "credit": ["counterparty", "credit risk", "receivables"],
    "var": ["value at risk", "var ", "VaR"],
}

_SENT = re.compile(r"(?s)(.*?\.)(\s+|$)")

def _pick_sentences(text: str, cues: List[str], minlen=60) -> List[str]:
    out: List[str] = []
    low = text.lower()
    for m in _SENT.finditer(text):
        s = m.group(1).strip()
        if len(s) < minlen: 
            continue
        s_low = s.lower()
        if any(c in s_low for c in cues):
            out.append(s)
    return out

def extract_market_risk(sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    sec = next((s for s in sections if (s.get("title") or "").lower().startswith("item 7a")), None)
    if not sec:
        return {}
    full = " ".join((c.get("full") or c.get("snippet") or "") for c in sec.get("content", []))
    out: Dict[str, Any] = {}
    for key, cues in _KEYS.items():
        sents = _pick_sentences(full, cues)
        if sents:
            out[key] = sents[:6]
    return out
