import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_DOMAIN_RE = re.compile(r"\b\w[\w\-]*\.(?:com|org|net|io|xyz|info|co|ai|app|gg|me|rs|ly)\S*\b", re.IGNORECASE)
_BAD_BRAND_RE = re.compile(
    r"(?:\bOn\s*Chain\s*News\b.*?\bBingX\b|\bBingX\b\s*partner\b|\bBingX\s*Zone\b|\bBybit\b\s*partner\b|\bOKX\b\s*partner\b)",
    re.IGNORECASE
)

_BAD_TAIL_RE = re.compile(r"(?:\|\s*)?(?:On\s*Chain\s*News|Crypto\s*News)\s*(?:\|\s*)?(?:BingX|Bybit|OKX)\s*$", re.IGNORECASE)

_AFFILIATE_DOMAIN_RE = re.compile(
    r"\b(?:bingxzone\.com|bingx\.com/\S*partner\S*|bit\.ly/\S+|t\.me/\S+\?start=\S+)\b",
    re.IGNORECASE,
)

def remove_branding(text: str) -> str:
    if not text:
        return ""
    text = _BAD_BRAND_RE.sub("", text)
    text = _BAD_TAIL_RE.sub("", text)
    text = _AFFILIATE_DOMAIN_RE.sub("", text)
    return normalize_whitespace(text)

@dataclass
class CleanResult:
    text: str
    removed_urls: List[str]
    expanded_links: List[str]

def normalize_whitespace(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()

def fix_money_artifacts(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\$(\d+),\$(\d+)([KMB])\b", r"$\1.\2\3", text)
    text = re.sub(r"\b(\d+),\$(\d+)([KMB])\b", r"$\1.\2\3", text)
    # $1,5B -> $1.5B / $276,3M -> $276.3M
    text = re.sub(r"\$(\d+),(\d)([KMB])\b", r"$\1.\2\3", text)
    text = re.sub(r"\$(\d+),(\d{1,2})([KMB])\b", r"$\1.\2\3", text)
    def _fix_dots(m):
        s=m.group(0)
        parts=s.split(".")
        if len(parts)==3 and all(p.isdigit() for p in parts):
            return f"{parts[0]},{parts[1]}.{parts[2]}"
        return s
    text = re.sub(r"\b\d{1,3}\.\d{3}\.\d{2}\b", _fix_dots, text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r",\s+,", ", ", text)
    return text

def remove_rt_shell(text: str) -> str:
    text = re.sub(r"^\s*(rt)\s+(от|from)\s*[:\-]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bpic\.?\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()

def remove_handles(text: str) -> str:
    text = re.sub(r"@\w+", "", text)
    return text

def remove_empty_attribution(text: str) -> str:
    text = re.sub(r"\bиз\s*(?:,\s*){1,}\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bот\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bсогласно\s*[.,]\s*", "согласно ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+([,;:])", r"\1", text)
    return normalize_whitespace(text)

def strip_urls(text: str) -> Tuple[str, List[str]]:
    urls = _URL_RE.findall(text)
    cleaned = _URL_RE.sub("", text)
    cleaned = _DOMAIN_RE.sub("", cleaned)
    return normalize_whitespace(cleaned), urls

def best_link(urls: List[str]) -> Optional[str]:
    if not urls:
        return None
    for u in urls:
        if "t.co/" not in u:
            return u
    return urls[0]

def clean_source_text(raw: str) -> CleanResult:
    raw = normalize_whitespace(raw or "")
    raw = remove_rt_shell(raw)
    raw = fix_money_artifacts(raw)
    cleaned, urls = strip_urls(raw)
    cleaned = remove_handles(cleaned)
    cleaned = remove_branding(cleaned)
    cleaned = remove_empty_attribution(cleaned)
    return CleanResult(text=cleaned, removed_urls=urls, expanded_links=[])

def clean_after_ai(text: str) -> str:
    text = normalize_whitespace(text or "")
    text = fix_money_artifacts(text)
    text = remove_empty_attribution(text)
    text = re.sub(r"^\s*конечно\s*$", "", text, flags=re.IGNORECASE)
    return normalize_whitespace(text)