from typing import List
from utils.ai import summarize_section

def two_pass_summary(title: str, chunks: List[str], pages: List[int]) -> str:
    minis = []
    for i, (c, p) in enumerate(zip(chunks, pages), 1):
        minis.append(summarize_section(f"{title} — excerpt {i}", [c], [p]))
    combined = "\n".join(minis)
    return summarize_section(f"{title} — consolidated", [combined], [pages[0] if pages else 1])
