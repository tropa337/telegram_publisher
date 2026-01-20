import re
from datetime import datetime, timezone
from html import unescape
from typing import Dict, List, Optional

import feedparser

from ..dedup import \
    normalize_text  # используем твою нормализацию для сравнения
from ..types import NewsItem

# --- regex ---
HTML_RE = re.compile(r"<[^>]+>")

# подпись типа: "— Coin Bureau (@coinbureau) Jan 10, 2026"
# (ловим и отдельной строкой, и если прилепилась в конец)
SIGNATURE_ANYWHERE_RE = re.compile(r"\s*—\s*[^—\n]*\(@\w+\)[^\n]*", re.IGNORECASE)

# любые ссылки
LINK_RE = re.compile(
    r"https?://\S+|www\.\S+|t\.me/\S+|x\.com/\S+|twitter\.com/\S+",
    re.IGNORECASE
)

# img теги и alt
IMG_TAG_RE = re.compile(r"<img[^>]*>", re.IGNORECASE)
IMG_ALT_RE = re.compile(r'<img[^>]*\salt="([^"]+)"[^>]*>', re.IGNORECASE)


def _extract_img_alt(html: str) -> str:
    """
    Достаёт текст твита, который rss.app иногда кладёт в <img alt="...">.
    """
    if not html:
        return ""
    alts = IMG_ALT_RE.findall(html)
    alts = [unescape(a).strip() for a in alts if a and a.strip()]
    return "\n".join(alts).strip()


def _remove_img_tags(html: str) -> str:
    """
    Убираем <img ...> полностью, чтобы alt не превращался в дубль при strip_html.
    """
    if not html:
        return ""
    return IMG_TAG_RE.sub("", html)


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    text = unescape(raw)
    # 🔥 сначала убираем картинки, чтобы не было дубля alt-текста
    text = _remove_img_tags(text)
    text = HTML_RE.sub("", text)
    return text.strip()


def _strip_links(text: str) -> str:
    if not text:
        return ""
    return LINK_RE.sub("", text).strip()


def _clean_text(text: str) -> str:
    """
    - вырезаем подписи "— Name (@nick) date" где угодно
    - убираем пустые строки
    - нормализуем переносы
    """
    if not text:
        return ""

    t = SIGNATURE_ANYWHERE_RE.sub("", text)

    lines = []
    for ln in t.splitlines():
        s = ln.strip()
        if not s:
            continue
        lines.append(s)

    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def _entry_datetime(entry) -> datetime:
    dt_struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not dt_struct:
        return datetime.now(timezone.utc)
    return datetime(
        dt_struct.tm_year, dt_struct.tm_mon, dt_struct.tm_mday,
        dt_struct.tm_hour, dt_struct.tm_min, dt_struct.tm_sec,
        tzinfo=timezone.utc
    )


def _extract_image_url(entry) -> Optional[str]:
    media = getattr(entry, "media_content", None)
    if media and isinstance(media, list):
        url = (media[0].get("url") or media[0].get("src"))
        if url:
            return url

    enclosures = getattr(entry, "enclosures", None)
    if enclosures and isinstance(enclosures, list):
        first = enclosures[0]
        url = getattr(first, "href", None) or getattr(first, "url", None)
        if url:
            return url

    # fallback img src
    candidates = []
    content = getattr(entry, "content", None)
    if content and isinstance(content, list):
        for v in content:
            if hasattr(v, "value"):
                candidates.append(v.value)
    summary = getattr(entry, "summary", None)
    if summary:
        candidates.append(str(summary))

    for html in candidates:
        m = re.search(r'src="([^"]+)"', html)
        if m:
            return m.group(1)
    return None


def fetch_twitter_rss(feeds: Dict[str, str], since_ts: float, auth_token: Optional[str] = None) -> List[NewsItem]:
    out: List[NewsItem] = []

    for label, url in feeds.items():
        try:
            # Если нужна авторизация для rss.app (добавь токен в .env)
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            feed = feedparser.parse(url, request_headers=headers)
            if getattr(feed, "bozo", False):
                print(f"⚠️ Feed parse error: {label}")
                continue
        except Exception as e:
            print(f"❌ Failed to fetch feed {label}: {e}")
            continue

        for entry in getattr(feed, "entries", []):
            created = _entry_datetime(entry)
            ts = created.timestamp()
            if ts <= since_ts:
                continue

            raw_title = getattr(entry, "title", "") or ""
            raw_summary = getattr(entry, "summary", "") or ""

            alt_text = _extract_img_alt(raw_summary)

            title = _clean_text(_strip_links(_strip_html(raw_title)))
            summary = _clean_text(_strip_links(_strip_html(raw_summary)))
            alt_clean = _clean_text(_strip_links(_strip_html(alt_text))) if alt_text else ""

            nt = normalize_text(title)
            ns = normalize_text(summary)
            na = normalize_text(alt_clean)

            parts = []
            if title:
                parts.append(title)

            if summary and ns and ns != nt and nt not in ns:
                parts.append(summary)

            if alt_clean and na:
                joined_norm = normalize_text("\n\n".join(parts))
                if na != joined_norm and joined_norm not in na and na not in joined_norm:
                    parts.append(alt_clean)

            raw_text = "\n\n".join([p for p in parts if p]).strip()
            raw_text = _clean_text(raw_text)
            raw_text = _strip_links(raw_text)
            raw_text = re.sub(r"[ \t]{2,}", " ", raw_text).strip()

            if not raw_text:
                continue

            media_url = _extract_image_url(entry)
            
            # 🔥 entry.id или entry.link - используем как уникальный ID
            entry_id = getattr(entry, "id", None) or getattr(entry, "link", None)
            source_link = getattr(entry, "link", None)

            out.append(
                NewsItem(
                    source=f"twitter_rss:{label}",
                    created_at=created,
                    raw_text=raw_text,
                    source_link=source_link,
                    media=media_url,
                )
            )

    return out