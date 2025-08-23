import re
from typing import Dict, Any, List, Optional, Tuple

# --- Simple money parsing helpers -------------------------------------------------

# $3.93 billion, $1,975, 1.2 bn, 500 million, etc.
RE_AMOUNT = re.compile(
    r"""
    (?P<cur>[$€])?\s*
    (?P<num>[0-9][\d,]*(?:\.\d+)?)
    \s*
    (?P<unit>billion|million|thousand|bn|mm|m|k)?
    """,
    re.IGNORECASE | re.VERBOSE,
)

UNIT_MULT = {
    "billion": 1_000_000_000,
    "bn": 1_000_000_000,
    "million": 1_000_000,
    "mm": 1_000_000,
    "m": 1_000_000,
    "thousand": 1_000,
    "k": 1_000,
}

def _to_float(num_str: str) -> float:
    return float(num_str.replace(",", ""))

def _amount_to_usd(num_str: str, unit: Optional[str]) -> Optional[float]:
    try:
        val = _to_float(num_str)
    except Exception:
        return None
    if unit:
        u = unit.lower()
        mult = UNIT_MULT.get(u)
        if mult:
            return val * mult
    # No unit: ambiguous — return the literal numeric (treat as whole dollars)
    return val

def _format_human_usd(val: float) -> str:
    # Compact human format: $1.23B / $456.7M / $12.3K / $123
    absval = abs(val)
    if absval >= 1_000_000_000:
        return f"${val/1_000_000_000:.2f}B"
    if absval >= 1_000_000:
        return f"${val/1_000_000:.2f}M"
    if absval >= 1_000:
        return f"${val/1_000:.2f}K"
    return f"${val:,.0f}"

def _best_amount(text: str) -> Optional[Tuple[str, float]]:
    """
    Return (pretty_str, numeric_usd) for the largest amount found in the text.
    """
    best: Optional[Tuple[str, float]] = None
    for m in RE_AMOUNT.finditer(text):
        num = m.group("num")
        unit = m.group("unit")
        cur = m.group("cur") or "$"
        usd = _amount_to_usd(num, unit)
        if usd is None:
            continue
        pretty = f"{cur}{num}{(' ' + unit) if unit else ''}".strip()
        if best is None or usd > best[1]:
            best = (pretty, usd)
    return best

# --- Headline fields (cash, total debt) ------------------------------------------

# Prefer statements like "... cash and cash equivalents of $31.0 billion"
RE_CASH = re.compile(
    r"""(?is)\b
        cash\s+(?:and\s+cash\s+equivalents|&\s*equivalents)?
        (?:\s+of|[:])?\s*
        (?P<amount>(?:[$€]\s*)?[0-9][\d,]*(?:\.\d+)?(?:\s*(?:billion|million|thousand|bn|mm|m|k))?)
    """,
    re.VERBOSE,
)

RE_DEBT = re.compile(
    r"""(?is)\b
        total\s+debt
        (?:\s+(?:was|of))?
        (?:\s*[:])?\s*
        (?P<amount>(?:[$€]\s*)?[0-9][\d,]*(?:\.\d+)?(?:\s*(?:billion|million|thousand|bn|mm|m|k))?)
    """,
    re.VERBOSE,
)

def _first_match_amount(pages: List[Dict[str, Any]], pat: re.Pattern) -> Optional[Tuple[str, float]]:
    # Scan pages in order and return first reasonable amount (by magnitude)
    for p in pages:
        t = p.get("text") or ""
        m = pat.search(t)
        if not m:
            continue
        amt_text = m.group("amount")
        hit = _best_amount(amt_text)
        if hit:
            return hit
    return None

# --- Instrument extraction --------------------------------------------------------

# Lines that *look* like actual instruments (not narrative):
INSTRUMENT_KEYWORDS = [
    "convertible", "senior", "notes", "note", "debenture", "bond",
    "term loan", "revolving", "credit facility", "asset-backed", "asset backed",
    "secured", "unsecured", "loan", "facility"
]

RE_COUPON = re.compile(r"(\d+(?:\.\d+)?)\s*%")
RE_DUE = re.compile(r"\bdue\s+(on\s+)?([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{4})", re.IGNORECASE)
RE_CUR_STR = re.compile(r"\b(USD|EUR|GBP)\b", re.IGNORECASE)

def _looks_like_instrument_line(line: str) -> bool:
    l = line.lower()
    return any(k in l for k in INSTRUMENT_KEYWORDS)

def _extract_instrument_from_line(line: str) -> Optional[Dict[str, Any]]:
    if not _looks_like_instrument_line(line):
        return None

    # Amount: pick the largest amount on the line
    best = _best_amount(line)
    if not best:
        # Without an amount it's very likely narrative; skip
        return None
    amount_pretty, _ = best

    # Coupon / Maturity / Currency
    coupon = None
    m = RE_COUPON.search(line)
    if m:
        coupon = f"{m.group(1)}%"

    maturity = None
    m = RE_DUE.search(line)
    if m:
        maturity = m.group(2)

    currency = None
    if "€" in line:
        currency = "EUR"
    elif "$" in line:
        currency = "USD"
    else:
        m = RE_CUR_STR.search(line)
        if m:
            currency = m.group(1).upper()

    # Name: strip excessive whitespace; prefer part before "due ..."
    name = line.strip()
    if " due " in name.lower():
        name = re.split(r"(?i)\bdue\b", name, maxsplit=1)[0].strip()

    # Final sanity: require a keyword in the (cleaned) name
    if not _looks_like_instrument_line(name):
        return None

    return {
        "name": name[:120],
        "coupon": coupon or "",
        "currency": currency or "",
        "maturity": maturity or "",
        "amount": amount_pretty,
        "pages": [],  # filled by caller
    }

def _dedup_instruments(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for it in items:
        key = (it.get("name",""), it.get("amount",""), it.get("maturity",""))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out

# --- Public API ------------------------------------------------------------------

def extract_capital_structure(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extracts:
      - cash (and cash equivalents)
      - total_debt
      - net_cash (only if both amounts convertible to USD)
      - instruments: list of dicts with {name, coupon, currency, maturity, amount, pages}
    """
    out: Dict[str, Any] = {}

    # 1) Cash & Total Debt
    cash_hit = _first_match_amount(pages, RE_CASH)
    debt_hit = _first_match_amount(pages, RE_DEBT)

    if cash_hit:
        out["cash"] = cash_hit[0]
    if debt_hit:
        out["total_debt"] = debt_hit[0]

    # Net cash only if both are in a comparable USD numeric form
    try:
        cash_num = None if not cash_hit else cash_hit[1]
        debt_num = None if not debt_hit else debt_hit[1]
        if cash_num is not None and debt_num is not None:
            out["net_cash"] = _format_human_usd(cash_num - debt_num)
    except Exception:
        pass

    # 2) Instruments — scan per page to attach page numbers
    instruments: List[Dict[str, Any]] = []
    for p in pages:
        pg = p.get("page")
        txt = (p.get("text") or "")
        for raw_line in txt.splitlines():
            line = raw_line.strip()
            if not line or len(line) < 8:
                continue
            inst = _extract_instrument_from_line(line)
            if inst:
                inst["pages"] = [pg] if isinstance(pg, int) else []
                instruments.append(inst)

    # Clean up / de-duplicate
    instruments = _dedup_instruments(instruments)

    # Filter out any residual narrative by requiring both a keyword (already ensured) and an amount (ensured)
    if instruments:
        out["instruments"] = instruments

    return out
