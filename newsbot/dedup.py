import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "over", "under", "will",
    "та", "і", "й", "але", "що", "це", "в", "у", "на", "про", "як", "до", "не", "за", "від", "з", "по",
    "и", "но", "что", "это", "в", "на", "про", "как", "до", "не", "за", "от", "из", "по",
}

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_AT_RE = re.compile(r"@\w+", re.IGNORECASE)
_HASH_RE = re.compile(r"#\w+", re.IGNORECASE)
_NON_RE = re.compile(r"[^a-zа-яіїє0-9\s$%.-]", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")

def _now() -> float:
    return time.time()

def normalize_text(text: str) -> str:
    t = (text or "").lower()
    t = _URL_RE.sub(" ", t)
    t = _AT_RE.sub(" ", t)
    t = _HASH_RE.sub(" ", t)
    t = _NON_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    words = [w for w in t.split() if w not in STOP and len(w) > 2]
    return " ".join(words)

def cache_key(text: str) -> str:
    """
    Ключ для AI-cache: sha256 от нормализованного текста.
    Один инфоповод из разных источников даст один ключ → ускорение.
    """
    norm = normalize_text(text)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()

def simhash64(text: str) -> int:
    norm = normalize_text(text)
    if not norm:
        return 0
    v = [0] * 64
    for token in norm.split():
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        for i in range(64):
            v[i] += 1 if ((h >> i) & 1) else -1
    fp = 0
    for i in range(64):
        if v[i] > 0:
            fp |= (1 << i)
    return fp

def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()

@dataclass
class DedupResult:
    ok: bool
    reason: str

def is_duplicate(state: Dict[str, Any], raw_text: str, link: Optional[str], max_hamming: int = 6) -> DedupResult:
    """
    Дедуп:
    - по ссылке (если есть)
    - по похожести текста (simhash)
    """
    if link:
        seen_links = state.setdefault("seen_links", {})
        if link in seen_links:
            return DedupResult(False, "dup_link")

    fp = simhash64(raw_text)
    seen = state.setdefault("seen_fps", [])
    for old in seen[-800:]:
        if hamming(fp, old) <= max_hamming:
            return DedupResult(False, "dup_similar")

    return DedupResult(True, "ok")

def mark_seen(state: Dict[str, Any], raw_text: str, link: Optional[str]) -> None:
    """
    Теперь seen_links хранит timestamp (для TTL-очистки в state.py).
    """
    ts = _now()
    if link:
        state.setdefault("seen_links", {})[link] = ts

    state.setdefault("seen_fps", []).append(simhash64(raw_text))

    # ограничиваем рост
    if len(state["seen_fps"]) > 3000:
        state["seen_fps"] = state["seen_fps"][-2000:]
