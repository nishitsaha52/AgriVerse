import re

_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(all\s+)?(previous|prior|system)\s+instructions?\b", re.I),
    re.compile(r"\b(reveal|print|repeat)\s+(the\s+)?(system|developer)\s+prompt\b", re.I),
    re.compile(r"\b(system|developer)\s+message\s*:", re.I),
    re.compile(r"\byou\s+are\s+(chatgpt|an?\s+ai\s+assistant)\b", re.I),
)


def contains_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) is not None for pattern in _PROMPT_INJECTION_PATTERNS)
