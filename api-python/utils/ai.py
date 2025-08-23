import os, time
from typing import List, Dict, Any
from dotenv import load_dotenv, find_dotenv
from openai import OpenAI, OpenAIError

load_dotenv(find_dotenv())

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("OPENAI_API_KEY is missing. Put it in api-python/.env, then restart uvicorn.")

# Models to try (env override first)
_DEFAULT_SUMMARY_MODEL = os.getenv("DOYRIX_OPENAI_MODEL_SUMMARY", "gpt-5-mini").strip()
_FALLBACK_MODEL = os.getenv("DOYRIX_OPENAI_MODEL_FALLBACK", "gpt-4.1-mini").strip()

client = OpenAI(api_key=api_key)

# Families that typically DO NOT support custom temperature
_NO_TEMP_PREFIXES = ("gpt-4.1", "gpt-5", "o1", "o3", "o4", "gpt-4o", "gpt-4o-mini")

def _supports_temperature(model_id: str) -> bool:
    m = (model_id or "").lower().strip()
    return not any(m.startswith(p) for p in _NO_TEMP_PREFIXES)

def _truncate(s: str, max_chars: int) -> str:
    return s if len(s) <= max_chars else s[: max_chars - 3] + "..."

def _chat_call(
    model_id: str,
    messages: List[Dict[str, Any]],
    want_tokens: int,
    allow_temp: bool,
    temp: float = 0.2,
):
    """
    Call chat.completions with best-guess params, then transparently retry
    if the model rejects temperature or a token-parameter name.
    """
    # First attempt: use max_completion_tokens (newer models)
    kwargs = dict(model=model_id, messages=messages, max_completion_tokens=want_tokens)
    if allow_temp and _supports_temperature(model_id):
        kwargs["temperature"] = temp

    try:
        return client.chat.completions.create(**kwargs)
    except OpenAIError as e:
        msg = str(e).lower()

        # If temperature is not supported: remove it and retry
        if "param': 'temperature" in msg or "unsupported value: 'temperature'" in msg:
            kwargs.pop("temperature", None)
            try:
                return client.chat.completions.create(**kwargs)
            except OpenAIError as e2:
                msg = str(e2).lower()
                # fall through to other fixes below using e2
                e = e2

        # If 'max_completion_tokens' is not supported, try 'max_tokens'
        if "param': 'max_completion_tokens" in msg or "unsupported parameter: 'max_completion_tokens" in msg:
            kwargs.pop("max_completion_tokens", None)
            kwargs["max_tokens"] = want_tokens
            return client.chat.completions.create(**kwargs)

        # Re-raise for outer handler (context/rate errors handled there)
        raise

def summarize_section(title: str, chunks: List[str], pages: List[int]) -> str:
    if not chunks:
        return f"- (no content for {title})"

    # Initial sizing (will shrink on demand)
    MAX_CHUNKS = 3
    PER_CHUNK_LIMIT = 2800
    PROMPT_HARD_CAP = 12000
    MAX_COMP_TOKENS = 700

    chunks = chunks[:MAX_CHUNKS]
    # keep pages aligned with chunks
    pages = pages[: len(chunks)]
    bullets_goal = 5 if sum(len(c) for c in chunks) < 8000 else 8

    system_msg = (
        "You are a precise financial analyst. Produce tight, factual bullets. "
        "Keep inline page tags like [p12] next to claims. Prefer concrete figures, "
        "YoY/QoQ deltas, drivers, and material risks."
    )

    def build_user_msg(per_chunk_limit: int, hard_cap: int) -> str:
        items_loc = [f"[p{p}] " + _truncate(t, per_chunk_limit) for t, p in zip(chunks, pages)]
        user = (
            f"Section Title: {title}\n\n"
            "Source Excerpts (each starts with a page tag):\n" + "\n\n".join(items_loc) +
            f"\n\nOutput {bullets_goal} bullets max."
        )
        combo_len = len(system_msg) + 2 + len(user)
        if combo_len > hard_cap:
            overflow = combo_len - hard_cap
            user = _truncate(user, max(1000, len(user) - overflow))
        return user

    model_try_order = []
    for mid in (_DEFAULT_SUMMARY_MODEL, _FALLBACK_MODEL):
        if mid and mid not in model_try_order:
            model_try_order.append(mid)

    per_chunk = PER_CHUNK_LIMIT
    hard_cap = PROMPT_HARD_CAP
    want_tokens = MAX_COMP_TOKENS

    for attempt in range(6):  # up to 6 attempts with shrink/backoff
        user_msg = build_user_msg(per_chunk, hard_cap)
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
        for model_id in model_try_order:
            try:
                rsp = _chat_call(
                    model_id=model_id,
                    messages=messages,
                    want_tokens=want_tokens,
                    allow_temp=True,  # will be stripped automatically if unsupported
                )
                return (rsp.choices[0].message.content or "").strip()
            except OpenAIError as e:
                lmsg = str(e).lower()

                # Too big → shrink and retry
                if ("maximum context length" in lmsg) or ("too long" in lmsg) or ("context_length_exceeded" in lmsg):
                    per_chunk = max(800, int(per_chunk * 0.7))
                    hard_cap = max(6000, int(hard_cap * 0.85))
                    want_tokens = max(250, int(want_tokens * 0.8))
                    continue

                # Transient issues → backoff and retry
                if ("rate limit" in lmsg) or ("service unavailable" in lmsg) or ("timeout" in lmsg) or ("overloaded" in lmsg) or (" 503" in lmsg):
                    time.sleep(0.6 + 0.25 * attempt)
                    continue

                # Permission/model issues → try the next model (no crash)
                if ("model_not_found" in lmsg) or ("you can't access" in lmsg) or ("insufficient_quota" in lmsg):
                    continue

                # Other invalid-request/unsupported-parameter → surface message
                if ("unsupported parameter" in lmsg) or ("invalid_request_error" in lmsg):
                    return f"- (summary unavailable: {e.__class__.__name__}: {str(e)})"

                # Unknown error: try next model / next cycle
                continue

        # Backoff between cycles
        time.sleep(0.4 + 0.25 * attempt)

    return "- (summary unavailable: retries_exhausted)"
